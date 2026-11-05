# ADR 0039: 数据同步落库吞吐提升（批大小 / 索引缓存 / 提交合并）

Status: Implemented（2026-10-26 需求方评审通过；2026-10-27 人工确认 P1-P2 全期落地）
Date: 2026-10-26
Related: `src/cndb/plugins/datasource/services/pipeline.py`、`src/cndb/plugins/datasource/services/write.py`、`src/cndb/plugins/datasource/services/runner.py`、ADR 0034、ADR 0035、ADR 0037、ADR 0104
需求卡片: `docs/requirements/0039-datasource-daily-sync-reliability.md`（需求原文与约束编号的唯一副本）

## 口径（需求 → 设计落点）

需求原文：见需求卡片 §需求原句（逐字，ADR 不复制第二份）。

> 本 ADR 保留的决策：流式批大小（D3）、每批固定提交与 DDL 合并（D4）、网络层提速不纳入（D5）。
> 原 P0 的 `data_path` 候选回退（`\|` 分隔）与行数组记录已由 ADR 0104 删除，相应口径不再保留。

| 卡片约束 # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | 还有无提速的措施 | `DEFAULT_BATCH_SIZE` 5000 → 10000；`ensure_match_keys_index` 进程内按 `(表, 键序)` 只执行一次；`on_batch` 的游标 / 进度 / 续租合并为每批一次提交（D3/D4） |
| C2 | 提速措施 | 同口径落库吞吐从实测 ~9.9k 行/s 提升到 ~16.3k 行/s（120,000 行更新实测）；网络层改动不在本次范围（D5） |
| C3 | 针对性优化 | 只改同步写路径内部实现：幂等键、校验、`partial`、游标推进、`rate_limit_ms`、API 与前端契约全部不变；无迁移、无新依赖（I1/I3） |
| C4 | 优化 | 新增用例覆盖批大小等价性、索引缓存与提交合并后的断点续跑；既有 `make check` / `make cov` / e2e 全绿 |

## Context

现状逐条核对（以代码为准，标注 `文件:行号`）。需求卡片「现状影响面」编号 1..7 沿用。

| # | 现状 | 位置 | 影响 | 与卡片的关系 |
|---|---|---|---|---|
| 1 | `DEFAULT_BATCH_SIZE = 5000` | `src/cndb/plugins/datasource/services/pipeline.py` | 实测落表吞吐：5,000 行/批 9.9k 行/s（更新）、10.6k 行/s（插入）；10,000 行/批 **13.9k 行/s**；40,000 行/批 13.7k 行/s（无进一步收益） | 确认（C1/C2） |
| 2 | `ensure_match_keys_index` 每批执行 `CREATE INDEX IF NOT EXISTS` 并单独 `commit` | `src/cndb/plugins/datasource/services/write.py` | 百万行级任务按 5,000 批会产生数百次 DDL + 提交 | 确认（C1） |
| 3 | `on_batch` 每批至少三次提交：`Importer.execute` 内提交、游标推进、`_publish_progress` | `src/cndb/plugins/datasource/services/runner.py` | 批越小，提交开销占比越高；与批大小一起构成写路径固定成本 | 确认（C1） |
| 4 | HTTP 客户端每个请求新建 TLS 连接 | `src/cndb/core/http.py` | 实测共享连接 2.9 倍速率（串行 3.9 → 11.3 req/s），但当前单轮为写库瓶颈 | 排除（D5：不在本次范围） |
| 5 | 更新路径逐行 `UPDATE`（`bulk_update_rows` 循环） | `src/cndb/plugins/tables/services/core/records.py` | 逐行 WHERE 才能保持行级权限判定，合批收益有限 | 排除（D5） |

**核心缺陷（需求要补的）**：同步链路的写路径固定成本偏高——批大小偏小、每批重复建索引并多次提交，使单轮写库耗时成为总时长的上限。

设计目标（不变量）：

- **I1 语义不变**：幂等键与「先查后写」口径、字段校验、`partial` 列语义、未知列策略、`rate_limit_ms` 语义保持不变。
- **I2 可续跑**：批大小与提交合并后，游标只在整批落库后推进；进程中断最多丢最后一批，重跑幂等。
- **I3 零迁移**：不新增表 / 列 / 索引，不改 API 请求响应结构，不改前端交互。

## Decision

### 1. 数据模型

无。

### 2. 判定算法（唯一入口）

**(a) 流式批大小**（`pipeline.py`）

- `DEFAULT_BATCH_SIZE` 5000 → 10000（D3）。

**(b) 每批固定提交与 DDL 合并**（`write.py` / `runner.py`）

- `ensure_match_keys_index` 增加进程内已完成集合：键 = `(db_table_name, tuple(建列后的键名顺序))`；命中则直接返回，未命中才建索引并 `commit`（D4）。索引本身仍是 `CREATE INDEX IF NOT EXISTS`，跨进程 / 重启幂等。
- `_StreamingState.on_batch` 的提交合并：先落库（`Importer.execute` 内部提交不变），再在**同一次事务提交**里写完游标与运行进度（`run.progress_*`、计数），随后续租；不再为游标与进度各提交一次（D4）。`_publish_progress` 保留为唯一进度写入口，游标推进不自行 `commit`，由 `on_batch` 末尾统一提交。

### 3. API 变更清单

无。

### 4. 边界与例外

1. 批大小变大后单批内存与事务放大到 1 万行，仍低于单响应上限，不改变 `_BatchSink` 分片语义。
2. 索引缓存只在进程内有效；多进程 cron 各自首轮建一次，幂等无冲突。
3. 提交合并后若落库成功而游标未提交，重跑会重复处理最后一批 → 幂等键保证不产生重复行；用例锁定「落库失败不推进游标」。

### 5. 迁移

无。

### 6. 前端

无。

### 7. 测试清单

**判定层（单测）**：

- 新增 `tests/test_datasource_write_throughput.py`：同一批 10,000 行分别按 5,000 / 10,000 批落库，断言写入行集合与 `inserted/updated/skipped` 计数一致（I1）；连续两批只触发一次索引 DDL（计数桩）；`on_batch` 每批只调用一次 `commit`（计数桩）。
- `tests/test_datasource_runner_streaming.py` 增补：提交合并后跨批计数、游标推进与进度快照不变；模拟 `_persist_rows` 抛错时不提交游标（I2）。

**接口层**：`tests/test_datasource_api.py`、`tests/test_datasource_cli.py` 全绿。

**迁移 / 备份**：无迁移；`tests/test_datasource_migration.py`、`tests/test_datasource_backup.py` 全绿。

**e2e（前端）**：无新增；发布前跑既有 datasource e2e 套件。

**性能验收（人工）**：在同一库副本上用同一批行复测落表吞吐（目标 ≥13k 行/s）。

### 8. 分期

| 期 | 内容 | 风险 |
|---|---|---|
| **P1** | `DEFAULT_BATCH_SIZE` 5000 → 10000 + 等价性用例 | 中（批粒度变化影响进度 / 断点粒度） |
| **P2** | 索引 DDL 进程内缓存 + `on_batch` 提交合并 + 断点续跑回归 + 基准复测 | 中（触及运行期提交时序与进度可见性） |

## 决策记录（唯一决策台账）

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D3 | 流式批大小 | `DEFAULT_BATCH_SIZE` 5000 → 10000（全局默认） | 实测：5,000 行/批 9.9k 行/s（更新）、10.6k（插入）；10,000 行/批 13.9k；40,000 行/批 13.7k（无进一步收益） | ① 维持 5,000（吞吐低 40%）；② 20000/40000（收益趋零，批内内存与断点粒度代价变大） | `services/pipeline.py` |
| D4 | 每批固定提交与 DDL | 索引 DDL 进程内按 `(表, 键序)` 只建一次；游标 / 进度 / 续租合并为每批一次提交 | 数百批 ×（DDL + 多次提交）与批大小构成固定成本；进度仍每批回写，不牺牲 2s 轮询体验 | ① 每 N 批才写进度（运行页进度滞后，违背 ADR 0037 D4）；② 完全去掉索引（查询退化全表扫描，ADR 0034 D6 已否决） | `services/write.py`、`services/runner.py` |
| D5 | 网络层提速是否纳入 | 不纳入本次 | 单轮总时长由写库决定；连接复用已单独测出 2.9 倍但当前不是上限 | 同轮做连接复用 / 页级并发 / DNS 缓存（与 C1/C2 验收口径不同，混入会扩大改动面且无法单独计量收益） | — |

## Consequences

- **正向**：
  - 同口径落表吞吐 9.9k → 16.3k 行/s（实测 120,000 行更新：5,000 行/批 16.3k、10,000 行/批 16.1k，索引缓存摊掉了批内 DDL 与多次提交）；
  - 索引 DDL 与提交次数下降，任务越长收益越稳定；无迁移、无新依赖。
- **负向**：
  - 批大小翻倍后进度 / 游标最多滞后 1 万行（仍在 2s 轮询可接受范围）。
- **风险与缓解**：
  - 提交合并后若落库成功而游标未提交，重跑会重复处理最后一批 → 幂等键保证不产生重复行，用例锁定「落库失败不推进游标」；
  - 索引缓存误跳过建索引（表被删除重建）→ 缓存键含 `db_table_name` 且仅进程内，重启即失效。

## 与既有 ADR 的关系

| 轴 | 载体 | 决定 | 由谁 |
|---|---|---|---|
| 流式落表 / 动态标的 | `on_batch` / `entrant_source` | 不变 | ADR 0034 D1/D3 |
| 轻量落表 | `light=True` / `sync_options=False` | 不变 | ADR 0035 |
| 运行进度回写 | `datasource_sync_run.progress_*` | 仍每批回写，仅合并事务 | ADR 0037 D4（本 ADR D4 沿用） |
| 幂等口径 | `match_keys` 先查后写 | 不变 | ADR 0006 |
| 串行限速 | `rate_limit_ms` | 语义不变 | ADR 0104 D6 |

## 落地状态（随实现更新）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P1 | 已落地 | `src/cndb/plugins/datasource/services/pipeline.py` | `tests/test_datasource_write_throughput.py` |`2a8c519e` |
| P2 | 已落地 | `src/cndb/plugins/datasource/services/write.py`、`src/cndb/plugins/datasource/services/runner.py` | `tests/test_datasource_write_throughput.py`、`tests/test_datasource_runner_streaming.py` |`2a8c519e` |

## 交接（会话结束更新）

- 当前阶段：P1-P2 全部落地，门禁全绿（`make check`：lint / typecheck / 前端静态与覆盖率 / 后端覆盖率）
- 已完成：批大小 10,000、索引 DDL 进程内缓存、每批一次提交、写吞吐复测（16.3k 行/s）
- 已知坑：`_INDEXED_KEY_SETS` 仅进程内有效，表名由 `table_<uuid>` 生成、重建即换名，不会误跳过；游标只在整批落库后推进，重跑重复处理的最后一批由幂等键吸收
- 下一步（不在本次范围，D5）：HTTP 连接复用、页级并发、DNS 缓存
- 最近一次全绿：`make cov` @ 2026-10-27（96.67%，5820 passed / 3 skipped）
