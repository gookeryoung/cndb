# ADR 0034: 全市场快照式增量同步（流式落表 + 动态标的 + 批间续租）

Status: Implemented（2026-10-27 人工评审通过）
Date: 2026-10-25
Related: `src/cndb/plugins/datasource/services/pipeline.py`、`src/cndb/plugins/datasource/services/runner.py`、`src/cndb/plugins/datasource/services/scheduler.py`、`src/cndb/plugins/datasource/services/write.py`、`src/cndb/plugins/datasource/services/entrant_state.py`、`src/cndb/plugins/datasource/models.py`、`src/cndb/plugins/datasource/routers/sync_jobs.py`、`src/cndb/plugins/tables/services/core/records.py`、`src/cndb/alembic/versions/2a4c6e8f0b1d_drop_datasource_entrant_cursor.py`；上游 ADR 0006（适配器收敛），后续 ADR 0104（裁剪股市日线专用能力）
需求卡片: `docs/requirements/0034-market-daily-incremental-sync.md`（需求原文与约束编号的唯一副本）

## 口径（需求 → 设计落点）

需求原文：见需求卡片 §需求原句（逐字，ADR 不复制第二份）。

> 本 ADR 保留的决策：流式落表（D1）、标的动态来源（D3）、幂等键复合索引（D6）、大表存储结论（D7）、长任务执行与批间续租（D10）。
> 按标的回补水位（`backfill_date` + `datasource_entrant_cursor`）、并发 `workers`、`row_filter` / `row_defaults`、`url_hosts`、`rows_array` 等股市日线专用能力已由 ADR 0104 删除；本节与正文只描述现行口径。

| 卡片约束 # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | 参照 stock-strategy 的同步架构 | 复刻为声明式配置：`entrant_source` 动态标的 + `http_json` 既有声明能力 + 流式落表；不新增 provider、不引入依赖 |
| C2 | 全市场标的拉取到本地 | 动态标的来源查同工作区清单表目标字段 distinct 值（可 `prefix_in` 前缀过滤），与静态 `entrant_keys` 并集；千万行级数据走流式分批落表 |
| C3 | 增量拉取，并非每次全量 | `date` / `datetime` / `key_set` / `none` 四类游标按任务声明表达增量；窗口策略空响应不推进游标 |
| C4 | 数据库膨胀给出更好方式 | 直存 SQLite 宽表可承受；配套幂等键复合索引、轮末 WAL checkpoint、低峰 VACUUM / 备份体积说明（帮助文档）；不换存储引擎（D7） |

决策结论只在「决策记录」写一次；本节与正文不再罗列「已确认决策」。

## Context

现状逐条核对（以代码为准，标注 `文件:行号`）。沿用卡片「现状影响面」的编号，逐条给结论：

| # | 现状 | 位置 | 影响 | 与卡片的关系 |
|---|---|---|---|---|
| 1 | 管线全量攒内存：`run_pipeline` 把所有请求行累积进 `raw_rows`，`execute_job` 末尾一次性 `upsert_rows` | `src/cndb/plugins/datasource/services/pipeline.py`、`services/runner.py` | 千万行级任务内存不可承受；单次大事务也不利断点续跑 | 确认（C2/C3 需要流式分批落表） |
| 2 | `entrant_keys` 为静态 JSON 列表 | `src/cndb/plugins/datasource/models.py`（`entrant_keys` 列）、`services/runner.py:build_job_spec` | 全市场标的集不宜硬编码；新标的要随清单自动纳入 | 确认（C2 需要标的动态来源） |
| 3 | 动态表无幂等键复合索引：`find_rows_by_key` 按每 500 行批 OR 查询 | `src/cndb/plugins/tables/services/core/records.py`、`services/core/ddl.py`（`build_sa_table` 不建业务索引） | 千万行表上批量 OR 查询退化为全表扫描，落表极慢 | 确认（C2/C4 写入性能） |
| 4 | 租约 TTL 300s、无续期；手动「立即运行」HTTP 同步执行 | `src/cndb/plugins/datasource/services/scheduler.py`、`routers/sync_jobs.py` | 长任务会被判死锁遭抢占；HTTP 侧必超时 | 确认（C2 需要批间续租 + CLI 执行口径） |
| 5 | 分页空页即停（`stop_pages`）按 (entrant, window) 分组 | `services/pipeline.py` | 清单 / 快照翻页（page 递增到空页停）直接复用 | 确认（C1 清单 / 快照翻页） |

**核心缺陷（需求要补的）**：同步引擎是「小任务」形态——静态标的集、单值游标、串行请求、全量攒内存、无幂等索引；表达不了「全市场标的动态集 + 千万行流式落表」的大规模形态。

设计目标（不变量）：

- **I1 领域无关**：引擎扩展（游标 / 流式 / 动态标的 / 索引）不出现股票语义；`providers/`、`services/` 无 symbol / 快照 / K 线等领域词，业务配置只存在于 `examples/datasets` 的 JSON（守住 ADR 0006 D2）。
- **I2 幂等可重跑**：任意 run 中断重跑，已落库批次保留且幂等键命中只更新；窗口游标**只前进不后退**，空响应不推进。
- **I3 失败留痕不拖垮**：单请求失败（限流 / WAF / 格式）记 `failures`，不中断整轮 run；partial 结果照常落库推进（沿用 ADR 0006 I3）。
- **I4 批间续期**：长任务每批 `renew_lease`；续期失败（租约易主）即终止 run 并落 `failed` 留痕。
- **I5 存量兼容**：旧任务（无 `entrant_source`、游标为既有四策略）行为不变；迁移可 downgrade。
- **I6 引用完整性**：`entrant_source` 指向的来源表 / 字段被删时 run 落 `failed`（不静默空跑）。

## Decision

### 1. 数据模型

一次迁移（`src/cndb/alembic/versions/`）：

| 对象 | 变更 | 说明 |
|---|---|---|
| `datasource_sync_job` | 新列 `entrant_source: JSON NULL` | 结构 `{"table": "<表名>", "field": "<字段名>", "prefix_in": ["sh6", ...]?}`；NULL = 仅静态 `entrant_keys`（旧行为） |

> 按标的回补水位表 `datasource_entrant_cursor` 已由 ADR 0104 的单条 drop 迁移删除；`datasource_sync_job` 列结构不再变化。

### 2. 判定算法（关键机制）

**流式落表**（`services/pipeline.py` + `services/runner.py`）：

- `run_pipeline` 增加回调形态 `on_batch(rows)`：抓取循环内攒满 `batch_size`（默认 10000）行即回调；runner 侧回调执行 `upsert_rows`（既有 Importer 幂等路径）+ 窗口游标推进 + 进度回写，每批一次提交后 `renew_lease`；run 计数跨批累积。
- 中途失败：已 persist 批次保留（幂等重跑安全），游标停在最后成功批，异常照旧落 failed run 留痕（I3 口径：单请求失败继续、致命异常终止）。
- `preview_job` 保持原「小路径」全量内存形态（预览量小，不动）。

**标的动态来源**（`services/runner.py:build_job_spec`）：

- 解析 `entrant_source`：查同工作区 `DataTable`（按名）→ 目标字段 distinct 非空值 → 可选 `prefix_in` 前缀过滤；与静态 `entrant_keys` **并集去重**。
- 表 / 字段不存在 → run 落 `failed`（错误信息指明来源配置），不静默空跑（I6）。

**幂等键复合索引**（`services/write.py`）：

- 首次落表前（或 job 首次执行时）`CREATE INDEX IF NOT EXISTS ix_<table>_<cols> ON <物理表> (<db_column_name 列序>)`；非唯一、幂等；列取 `match_keys` 对应 `DataField.db_column_name`。

**租约续期**（`services/scheduler.py`）：

- `renew_lease(session, lease, now=...)`：校验 `lease_owner == owner` 后刷新 `lease_until = now + TTL`；`execute_job` 每批 persist 后调用；续期失败（租约易主）→ 抛错终止 run 留痕。

### 3. API 变更清单

| 端点 | 变更 |
|---|---|
| `POST/PUT /workspaces/{wid}/datasource/sync-jobs` | 无 schema 改动（`request_spec` / `cursor` 本为自由 JSON，`entrant_source` 随 payload 透传）；前端向导不提供配置入口 |
| `POST .../sync-jobs/{id}/run` | 语义不变；文档注明长任务建议 CLI `cndb sync tick` 执行（HTTP 等待有超时） |

### 4. 边界与例外

1. `entrant_source` 指向的表无行（如清单尚未首拉）：并集后为空 → run 零请求记 skipped（清单任务先行，属正常启动顺序，不判 failed）。
2. `preview_job` 与执行同口径解析标的来源，但不落库、不推进游标。
3. 租约续期只在有租约句柄时执行（HTTP 立即运行 / CLI tick 由调度器传入）；手动本地调试无租约时跳过。
4. 流式批大小与提交口径由 ADR 0039 调整为 10000 / 每批一次提交；本 ADR 只定义回调形态。

### 5. 测试清单

**判定层（单测）**：

- `tests/test_datasource_runner_streaming.py`：`on_batch` 分批落表、窗口游标推进、空响应不推进、`entrant_source` 动态标的、批间续租（失败 / 成功）、`light=True` 落表与 `llm_prompt` 全量路径。
- `tests/test_datasource_runner.py`：`execute_job` 流式落表与窗口游标推进、预览路径。
- `tests/test_datasource_row_ownership.py`：`fill_entrant(inplace=True)` 与 `on_batch` 浅拷贝的行所有权。
- `tests/test_datasource_write_throughput.py`：批大小与轻量落表断言。

**接口层**：`tests/test_datasource_api.py`、`tests/test_datasource_cli.py` 全绿。

**迁移 / 备份**：`tests/test_datasource_migration.py`（head 迁移与往返）、`tests/test_workspace_backup_v9.py`（备份格式）。

**e2e（前端）**：无新增（只读展示兼容由单测覆盖；不新增页面 / 视图形态）。

### 6. 分期

| 期 | 内容 | 风险 |
|---|---|---|
| **P0** | 本 ADR + 需求卡片评审（人工卡点） | 低 |
| **P1** | 引擎能力：`entrant_source` 迁移 + 流式落表 + 复合索引 + 续租 + 判定层 / 集成单测 | 高（流式改造触及管线主干，须保 I2/I5 兼容） |
| **P2** | 前端只读兼容（`entrant_source` 编辑时原样回传）+ 文档 | 低 |
| **P3** | 真源 smoke + 帮助文档大表维护节 + `make flow` 全绿收尾 | 中（第三方接口限流 / 格式漂移） |

## 决策记录（唯一决策台账）

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | 大规模任务的内存形态 | 流式分批落表（batch 10000）：抓取与落库交错，批粒度推进游标 + 续租，中途失败已落批保留 | 千万行级全量攒内存不可行；批粒度 = 最小安全断点 | ① 分 run 全量（单轮太长、失败全弃）；② 响应驱动无限流式生成器（分页语义复杂化，收益小） | `services/pipeline.py`、`services/runner.py` |
| D3 | 标的集合维护 | `entrant_source` 动态来源（查清单表 distinct，可选 `prefix_in` 过滤）与静态 `entrant_keys` 并集 | 全市场标的硬编码不可维护；新标的自动纳入；`prefix_in` 作为通用过滤能力保留 | ① 全静态列表（更新靠人工）；② 引擎内置全市场清单（领域词进引擎，违反 I1） | `models.py`（新列）、`services/runner.py` |
| D6 | 大表写入性能 | 按 `match_keys` 建非唯一复合索引（任务首跑幂等创建） | 无索引时千万行表批量 OR 查询全表扫描；非唯一不改变应用层幂等口径（ADR 0006 否决的是唯一约束） | ① 唯一索引 + `ON CONFLICT`（改写幂等路径，动摇 0006 口径）；② 不建索引（落表性能不可接受） | `services/write.py` |
| D7 | 大表存储结论 | 直存 SQLite 宽表；配套 D6 索引 + WAL checkpoint / 低峰 VACUUM / 备份体积文档 | SQLite 单库可承受百万~千万行宽表；保住表格 / 视图 / 图表全链路能力 | ① 外部文件（CSV/parquet + 路径引用，丧失全部表格能力）；② 按年分表（DataTable 无分区语义）；③ 独立库文件（连接层架构改动） | 帮助文档（P3） |
| D10 | 长任务执行方式 | 长任务走 CLI `cndb sync tick`（或 interval 调度），批间 `renew_lease`；「立即运行」HTTP 入口保留但不承诺长任务 | HTTP 同步等待必超时；租约 300s 无续期会被误抢占 | ① 调大 TTL（治标，仍有无界长任务）；② 后台任务队列（新基建，超出本卡范围） | `services/scheduler.py`、`services/runner.py` |

门禁：`Proposed` → `Accepted` 前本表不得有「待定」；结论只在本书出现，别处只引用编号。

## Consequences

- **正向**：同步引擎获得「大规模任务」形态（动态标的集 / 流式断点 / 幂等索引 / 批间续租），任何同类大规模 API（不限股票）可用配置接入；大表写入性能与库体积口径有明确文档。
- **负向**：管线主干从「攒全量」改「流式回调」，runner / pipeline 复杂度上升；`entrant_source` 一个 job 列的认知成本。
- **风险与缓解**：① 第三方限流 → 失败留痕下轮续跑（流式断点天然可续）；② 真实接口格式漂移 → P3 真源验证，配置级可改；③ 长任务超过租约 → 批间续租（D10）。

被否决的替代方案见「决策记录」对应行，此处不重复。

## 行业对照（可选）

无（不引入新领域模型；业务语义全在示例配置层）。

## 与既有 ADR 的关系（可选）

| 轴 | 载体 | 决定 | 由谁 |
|---|---|---|---|
| 适配器边界 | `providers/registry.py` 仅两 provider | 本 ADR 不触碰注册表；全部能力落在引擎服务层与 `http_json` 声明键 | ADR 0006 D2 |
| 增量游标 | `date` / `datetime` / `key_set` / `none` | 沿用既有四策略；`backfill_date` 已由 ADR 0104 删除 | ADR 0104 |
| 轻量落表 | `upsert_rows(light=True)` | 流式回调复用轻量落表 | ADR 0035 |
| 批大小 / 提交合并 | `DEFAULT_BATCH_SIZE` / `on_batch` 提交 | 每批一次提交 | ADR 0039 |

## 落地状态（随实现更新）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 | 已落地 | `docs/requirements/0034-market-daily-incremental-sync.md`、`docs/adr/0034-market-daily-snapshot-sync.md` | `tests/test_seed_datasource.py` | `0d61f94b` |
| P1 | 已落地 | `src/cndb/plugins/datasource/services/pipeline.py`、`src/cndb/plugins/datasource/services/runner.py`、`src/cndb/plugins/datasource/services/scheduler.py`、`src/cndb/plugins/datasource/services/write.py`、`src/cndb/plugins/datasource/services/entrant_state.py`、`src/cndb/plugins/datasource/models.py`、`src/cndb/alembic/versions/2a4c6e8f0b1d_drop_datasource_entrant_cursor.py` | `tests/test_datasource_runner_streaming.py`、`tests/test_datasource_runner.py`、`tests/test_datasource_migration.py` | `0d61f94b` |
| P2 | 已落地 | `src/cndb/cli/seed/datasource.py`、`frontend/src/api/datasource.ts`、`frontend/src/pages/datasource/DatasourcePage.tsx` | `tests/test_seed_datasource.py`、`frontend/src/pages/datasource/DatasourcePage.test.tsx` | `0d61f94b` |
| P3 | 已落地 | `frontend/src/pages/help/content/configuration.tsx`、`src/cndb/plugins/help/services/examples.py` | `tests/test_help_examples_api.py`、`frontend/src/pages/datasource/DatasourcePage.test.tsx` | `0d61f94b` |

> 状态只取「未开始 / 进行中 / 已落地」。标「已落地」的期必须有代码落点与测试文件；全期落地后由人确认 `Status` 是否改 `Accepted` / `Implemented`。`make adr-check` 会校验本表与代码、测试、CHANGELOG 的对应关系。

## 交接（会话结束更新）

- 当前阶段：P0-P3 全部落地，`Status` 已于 2026-10-27 经人工评审确认改 `Implemented`
- 已完成：引擎全量能力（`entrant_source` 动态标的 / 流式落表 / 幂等键复合索引 / 批间续租）；前端只读兼容 + 编辑时原样回传 `entrant_source`；帮助文档「大规模同步与增量」「大表与库体积维护」两节
- 已知坑：① `on_batch` 转发行对象不复制，依赖 ADR 0043 D2 的行所有权边界；② 标的来源表无行时零请求 skipped 属正常启动顺序；③ 长任务必须走 CLI / interval 调度，HTTP「立即运行」不承诺长任务
- 下一步：无（功能完结）。历史回补 / 并发 / 行过滤 / 行数组等能力已由 ADR 0104 删除，相关需求需重新立项
- 最近一次全绿：`make test` 5422 passed / 3 skipped、`make cov` 97.03%（门槛 95%）@ 2026-10-26；ADR 0104 裁剪后由该 ADR 的交接记录最新门禁结果
