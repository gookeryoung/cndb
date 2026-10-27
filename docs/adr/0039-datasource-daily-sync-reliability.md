# ADR 0039: 数据源同步失败修复（data_path 候选回退）与落库吞吐提升

Status: Implemented（2026-10-26 需求方评审通过；2026-10-27 人工确认 P0-P2 全期落地）
Date: 2026-10-26
Related: `src/cndb/plugins/datasource/providers/http_json.py`、`src/cndb/plugins/datasource/providers/base.py`、`src/cndb/plugins/datasource/services/pipeline.py`、`src/cndb/plugins/datasource/services/write.py`、`src/cndb/plugins/datasource/services/runner.py`、`examples/datasets/工作区-数据源示例/datasource.json`、ADR 0033、ADR 0034、ADR 0035、ADR 0037
需求卡片: `docs/requirements/0039-datasource-daily-sync-reliability.md`（需求原文与约束编号的唯一副本）

## 口径（需求 → 设计落点）

需求原文：见需求卡片 §需求原句（逐字，ADR 不复制第二份）。

| 卡片约束 # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | 大量错误：行数组记录要求 data_path 指向一个数组 | `data_path` 改为「候选路径列表」语义（`\|` 分隔），`rows_array` 按声明顺序取第一个命中数组的候选；**路径缺失 / `null` 记为无数据返回 `[]`**（不再报错），只有命中的节点存在但非数组才 `ProviderError`（D1/D2） |
| C2 | 股市日线，存在大量错误 | `data_path` 候选回退消除「该品种没有这条序列即请求失败」；示例回补任务改不复权单路径 `day`（ADR 0053 C9/D7），不再按品种拆任务 |
| C3 | 还有无提速的措施 | `DEFAULT_BATCH_SIZE` 5000 → 10000；`ensure_match_keys_index` 进程内按 `(表, 键序)` 只执行一次；`on_batch` 的进度 / 水位 / 续租合并为每批一次提交（D3/D4） |
| C4 | 提速措施 | 同口径落库耗时从实测 370s 降到约 236s（实测 120,000 行更新 16.3k 行/s，3.83M 行推算）；网络层改动不在本次范围（D5） |
| C5 | 针对性优化 | 只改解析分支与同步写路径内部实现：幂等键、校验、`partial`、水位、`workers` / `rate_limit_ms`、API 与前端契约全部不变；无迁移、无新依赖（I1/I3） |
| C6 | 大量错误 / 优化 | 存量实例按「删旧任务 → 重跑 `cndb seed`」或前端「数据源同步」编辑生效；旧的三条板块回补任务需人工删除（ADR 0053 D10），写入「交接」 |
| C7 | 存在大量错误 | 新增用例覆盖候选回退、批大小等价性、索引缓存与提交合并后的断点续跑；既有 `make check` / `make cov` / e2e 全绿 |

## Context

现状逐条核对（以代码为准，标注 `文件:行号`）。需求卡片「现状影响面」编号 1..7 沿用。

| # | 现状 | 位置 | 影响 | 与卡片的关系 |
|---|---|---|---|---|
| 1 | `parse` 把单个 `data_path` 交给 `rows_array_to_rows`，`_resolve_path` 未命中得 `None` 后直接抛错 | `src/cndb/plugins/datasource/providers/http_json.py:109`、`:232` | 腾讯响应缺目标键（如北交所品种只回 `data: {bj920010: {}}`）时整条请求失败，该标的零入库 | 确认（C1） |
| 2 | 腾讯回补任务的 `data_path` 固定为 `data.{entrant}.qfqday` | `examples/datasets/工作区-数据源示例/datasource.json` | 同上；现由 ADR 0053 改为不复权单路径 `data.{entrant}.day`，该键对多数品种存在，但北交所 / 无该序列品种仍缺失 | 确认（C1/C2） |
| 3 | 回补任务原按前缀拆分（`sh60`/`sz00`/`sz30`/`sh5`/`sz1` 与 `sh68`/`sh69`） | `examples/datasets/工作区-数据源示例/datasource.json` | 拆分原为量纲与 `data_path` 兜底；ADR 0053 C5 合并为全市场单任务、不复权单路径 | 确认（C2 已由 0053 收口） |
| 4 | 运行记录实测：job「腾讯回补 · 主板创业板ETF」本轮 6,319 个计划 / 4,933 成功 / **1,386 失败（21.9%）**，失败原因全部是 `行数组记录要求 data_path 指向一个数组` | `datasource_sync_run.detail.failures` | 失败标的无法推进水位，每轮重复失败，基金历史数据始终为空 | 确认（C1） |
| 5 | 真源抽样 644 个标的（按前缀分层）：股票有 `qfqday` 占 99.1%；基金/ETF 为 0%~83%，`day` 恒存在 | 线上接口 + 本仓库「股票清单」表实测（2026-10-26） | 失败集中在基金/ETF；示例因此改不复权单路径 `day`（ADR 0053 D7），候选回退保留为通用能力 | 确认（C1/C2） |
| 6 | `DEFAULT_BATCH_SIZE = 5000` | `src/cndb/plugins/datasource/services/pipeline.py:39` | 实测落表吞吐：5,000 行/批 9.9k 行/s（更新）、10.6k 行/s（插入）；10,000 行/批 **13.9k 行/s**；40,000 行/批 13.7k 行/s（无进一步收益） | 确认（C3/C4） |
| 7 | `ensure_match_keys_index` 每批执行 `CREATE INDEX IF NOT EXISTS` 并单独 `commit` | `src/cndb/plugins/datasource/services/write.py:135` | 3.83M 行按 5,000 批约 760 次 DDL + 提交 | 确认（C3） |
| 8 | `on_batch` 每批至少三次提交：`Importer.execute` 内提交、`_advance_backfill`、`_publish_progress` | `src/cndb/plugins/datasource/services/runner.py:710`、`:748`、`:729` | 批越小，提交开销占比越高；与批大小一起构成写路径固定成本 | 确认（C3） |
| 9 | `rows_array_to_rows` 对空数组返回 `[]`（既有用例锁定） | `src/cndb/plugins/datasource/providers/http_json.py:235`、`tests/test_datasource_http_json.py:77` | 候选回退需要定义「空数组算不算命中」 | 新增（D2） |
| 10 | `来源` / `复权方式` 为文本列，无 select 取值约束 | `examples/datasets/工作区-数据源示例/股市日线.csv:1` | 新增「腾讯不复权」取值不需要改字段配置或迁移 | 新增（C2） |
| 11 | HTTP 客户端每个请求新建 TLS 连接 | `src/cndb/core/http.py:581` | 实测共享连接 2.9 倍速率（串行 3.9 → 11.3 req/s），但当前单轮为写库瓶颈 | 排除（D6：不在本次范围） |
| 12 | 「股市日线（腾讯回补 · 全市场）」运行实测：`symbol=bj920010` / `bj920002` / `bj920007` 报 `行数组记录要求 data_path 指向一个数组` | 生产运行记录 + 真源单请求复验（2026-10-27）：`{"code":11,"data":"","msg":"No dispatch info found"}` | 北交所品种无日线可用响应（`data` 为空串，路径解析得 `None`），单路径解析把「无数据」当失败；该标的水位不推进、每轮重复失败 | 新增（C1：D2 修订） |

**核心缺陷（需求要补的）**：`data_path` 只能表达「唯一响应路径」，而第三方接口对**同一类资源**会因品种不同返回不同键（`qfqday` 或 `day`）；同步任务无法声明「先取前复权、没有则取不复权」，于是把「该品种没有这条序列」误判为请求失败，既丢数据又反复重试。同时落库链路的固定成本（5,000 行批、每批 DDL 与多次提交）使单轮写库耗时成为总时长的上限。

设计目标（不变量）：

- **I1 语义不变**：幂等键与「先查后写」口径、字段校验、`partial` 列语义、未知列策略、`workers` / `rate_limit_ms` 语义保持不变（示例的幂等键与来源列由 ADR 0053 修订）。
- **I2 可续跑**：批大小与提交合并后，回补水位/游标只在整批落库后推进；进程中断最多丢最后一批，重跑幂等。
- **I3 零迁移**：不新增表 / 列 / 索引，不改 API 请求响应结构，不改前端交互。

## Decision

### 1. 数据模型

无。`RequestSpec.data_path` 类型仍为 `str | None`，语义扩展为「`|` 分隔的候选路径列表」；`data_path` 本身（JSON 键路径）不允许含 `|`。

### 2. 判定算法（唯一入口）

**(a) 候选路径解析**（`src/cndb/plugins/datasource/providers/http_json.py`）

- 新增模块级私有函数 `_rows_array_from_candidates(payload: Any, data_path: str | None, layout: Mapping[str, str | int] | None) -> list[dict[str, Any]]`：
  1. 按 `|` 切分并去空白，得到候选列表（单路径即长度 1 的列表）；候选为空时按整段 payload 解析（既有行为）；
  2. 依声明顺序对每个候选执行 `_resolve_path`：
     - 命中**非空 list** → 立即用它调用既有 `rows_array_to_rows(payload, candidate=None, layout)` 返回；
     - 命中**空 list** → 记为「已有空命中」，继续尝试下一候选（D2）；
     - **未命中 / 值为 `null`** → 记为「无数据」，继续尝试下一候选（D2 修订：北交所等品种只回空对象，不再报错）；
     - 命中存在但非 list（字典 / 标量）→ 记入「形态不符」；
  3. 存在形态不符的候选 → `ProviderError("行数组记录要求 data_path 指向一个数组（命中非数组的候选: a.b）")`；
  4. 全部候选缺失 / 空 / `null` → 返回 `[]`（合法无数据响应，不报错，落空批不推进水位）。
- `HttpJsonProvider.parse` 的 `record_mode == "rows_array"` 分支改走该函数；`columns` 分支与 `rows` 分支不变（D1）。
- `data_path` 模板渲染仍由 `_build_config` 对整串做 `render_text`（如 `data.{entrant}.a|data.{entrant}.b` 的每个占位符都会被替换），`rows_array` 自定义 handler 原样透传渲染结果。

**(b) 示例任务口径**（`examples/datasets/工作区-数据源示例/datasource.json`）

- 回补任务由 ADR 0053 收敛为**一条全市场任务**，取不复权单路径 `data.{entrant}.day`，`row_defaults` 不再含「来源 / 复权方式」（ADR 0053 D6/D7）；`(a)` 的候选回退保留为通用声明能力，示例不必再声明候选。
- 幂等键为 `[股票代码, 日期]`（ADR 0053 D6），快照与回补命中同一行。
- 其余字段（`workers` 10、`rate_limit_ms` 50、`record_layout`、`field_mapping`、`cursor`）原样保留。

**(c) 写路径吞吐**（`pipeline.py` / `write.py` / `runner.py`）

- `DEFAULT_BATCH_SIZE` 5000 → 10000（D4）。
- `ensure_match_keys_index` 增加进程内已完成集合：键 = `(db_table_name, tuple(建列后的键名顺序))`；命中则直接返回，未命中才建索引并 `commit`（D5）。索引本身仍是 `CREATE INDEX IF NOT EXISTS`，跨进程/重启幂等。
- `_StreamingState.on_batch` 的提交合并：先落库（`Importer.execute` 内部提交不变），再在**同一次事务提交**里写完水位 / 游标与运行进度（`run.progress_*`、计数），随后续租；不再为水位与进度各提交一次（D5）。`_publish_progress` 保留为唯一进度写入口，`_advance_backfill` 改为不自行 `commit`，由 `on_batch` 末尾统一提交。

### 3. API 变更清单

无。`request_spec.data_path` 仍是字符串，仅取值语法扩展；`GET/POST/PUT /sync-jobs` 的请求响应结构不变。

### 4. 边界与例外

1. 路径缺失 / `null` / 空数组都算「无数据」：返回 `[]` 落空批、水位不推进、运行记 success（北交所 `bj92xxxx` 这类只回 `data: ""` / 无该键的品种不再每轮失败）。
2. 只有候选命中的节点存在且非 list（字典 / 标量）才 `ProviderError`，消息列出这些候选。
3. 第一候选返回空数组、第二候选有数据时取第二（D2）。
4. 候选顺序即优先级，配置写错会静默改口径（取到 `[]` 而非报错）；`record_layout` 要求各候选形态同构（如 6 列行数组）。示例使用单路径 `data.{entrant}.day`（ADR 0053 D7）。
5. `data_path` 为 `None` 时保持原行为（整段 payload 必须是数组，非数组报错）。
6. 批大小变大后单批内存与事务放大到 1 万行，仍远低于单响应上限（800 根/标的 × 组内标的数），不改变 `_BatchSink` 分片语义。
7. 索引缓存只在进程内有效；多进程 cron 各自首轮建一次，幂等无冲突。

### 5. 迁移

无。

### 6. 前端

无。`data_path` 是文本输入（`frontend/src/pages/datasource/DatasourcePage.tsx:1043`），新语法向后兼容；存量任务编辑时原值原样回传。

### 7. 测试清单

**判定层（单测）**：

- `tests/test_datasource_http_json.py` 增补：
  - 响应只有 `day` 时，`data_path="data.{entrant}.a|data.{entrant}.b"` 的候选语义按序命中（示例自身用单路径 `day`）；
  - 首候选存在但为空数组、次候选有数据 → 取次候选；
  - 候选路径全部缺失（含北交所 `data: {bj920010: {}}`）→ 返回 `[]` 不报错；
  - 单路径缺失 → 返回 `[]` 不报错（2026-10-27 修订，D2）；
  - 候选命中的节点存在但非数组 → `ProviderError`，消息含该候选；
  - 全部候选为空数组 → 返回 `[]` 不报错。
- `tests/test_seed_datasource.py`：回补任务名、`data_path`（单路径 `day`）、`match_keys=[股票代码, 日期]`、不含「来源 / 复权方式」常量列逐项断言（ADR 0053 C5-C10）。

**接口层**：`tests/test_datasource_api.py`、`tests/test_datasource_cli.py` 全绿（`data_path` 语法扩展不破坏保存/预览）。

**写路径等价 / 断点**：

- 新增 `tests/test_datasource_write_throughput.py`：同一批 10,000 行分别按 5,000 / 10,000 批落库，断言写入行集合与 `inserted/updated/skipped` 计数一致（I1）；连续两批只触发一次索引 DDL（计数桩）；`on_batch` 每批只调用一次 `commit`（计数桩）。
- `tests/test_datasource_runner_streaming.py` 增补：提交合并后跨批计数、水位推进与进度快照不变；模拟 `_persist_rows` 抛错时不提交水位（I3）。

**迁移 / 备份**：无迁移；`tests/test_datasource_migration.py`、`tests/test_datasource_backup.py` 全绿。

**e2e（前端）**：无新增；发布前跑既有 datasource e2e 套件。

**性能验收（人工）**：在现有 3.83M 行库副本上用同一批行复测落表吞吐（目标 ≥13k 行/s）与单轮计时（目标 ≤270s）；修复后重跑真源，失败数归零（除真异常）。

### 8. 分期

| 期 | 内容 | 风险 |
|---|---|---|
| **P0** | `data_path` 候选回退 + 单测；种子回补任务口径对齐（单任务、不复权单路径，ADR 0053）+ 种子用例 | 低（解析分支局部改动，配置变更可回退） |
| **P1** | `DEFAULT_BATCH_SIZE` 5000 → 10000 + 等价性用例 | 中（批粒度变化影响进度/断点粒度） |
| **P2** | 索引 DDL 进程内缓存 + `on_batch` 提交合并 + 断点续跑回归 + 基准复测 | 中（触及运行期提交时序与进度可见性） |

## 决策记录（唯一决策台账）

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | 修复方式的整体选型 | `data_path` 支持 `\|` 分隔的候选路径，按序取第一个命中（非空优先）数组，`rows_array` 用新入口 | 失败主因是「同一资源多种键」，属声明式配置能表达的范畴；单路径配置沿用同一实现 | ① 静默返回空行（未命中即报错的做法已被 D2 修订否决）；② 在 provider 里按前缀硬编码回退（不可配置、换接口即失效）；③ 不扩能力只改示例路径（遇到同类接口仍需改代码） | `providers/http_json.py:parse` |
| D2 | 「无数据」与「形态不符」的判定 | 空数组 / 路径缺失 / `null` 都算命中但无数据：继续尝试下一候选，全部如此返回 `[]`；只有节点存在且非数组才报错 | 北交所品种只回 `data: {bj92xxxx: {}}`（2026-10-27 实测），把无数据当故障会让该标的每轮重复失败、水位永不推进；返回 `[]` 属合法无数据响应 | ① 首候选为空即返回 `[]`（会漏数据）；② 空数组 / 缺失也报错（即修复前的行为，重复失败）；③ 缺失一律报错但只对候选语义放宽（单路径仍失败，北交所问题不解决） | `providers/http_json.py:_rows_array_from_candidates` |
| D3 | 流式批大小 | `DEFAULT_BATCH_SIZE` 5000 → 10000（全局默认） | 实测：5,000 行/批 9.9k 行/s（更新）、10.6k（插入）；10,000 行/批 13.9k；40,000 行/批 13.7k（无进一步收益） | ① 维持 5,000（吞吐低 40%）；② 20000/40000（收益趋零，批内内存与断点粒度代价变大） | `services/pipeline.py:39` |
| D4 | 每批固定提交与 DDL | 索引 DDL 进程内按 `(表, 键序)` 只建一次；水位 / 进度 / 续租合并为每批一次提交 | 760 批 ×（DDL + 多次提交）与批大小构成固定成本；进度仍每批回写，不牺牲 2s 轮询体验 | ① 每 N 批才写进度（运行页进度滞后，违背 ADR 0037 D4）；② 完全去掉索引（查询退化全表扫描，ADR 0034 D6 已否决） | `services/write.py:135`、`services/runner.py:710` |
| D5 | 网络层提速是否纳入 | 不纳入本次 | 单轮总时长由写库决定（3.83M 行 ÷ 10.3k 行/s ≈ 370s，与实测一致）；连接复用已单独测出 2.9 倍但当前不是上限 | 同轮做连接复用 / 页级并发 / DNS 缓存（与 C3/C4 验收口径不同，混入会扩大改动面且无法单独计量收益） | — |

## Consequences

- **正向**：
  - 21.9% 的失败归零（缺首选序列时回退到次序列；示例改为多数品种存在的 `day`）；
  - 「无数据」不再计为失败：北交所 `bj92xxxx` 等只回空对象的品种记 success、零入库，不再每轮重复失败（D2 修订）；
  - 基金/ETF 历史日线首次可完整入库；
  - 同口径落表吞吐 9.9k → 16.3k 行/s（实测 120,000 行更新：5,000 行/批 16.3k、10,000 行/批 16.1k，索引缓存摊掉了批内 DDL 与多次提交），3.83M 行单轮估算约 236s（原 370s）；
  - 索引 DDL 与提交次数下降，任务越长收益越稳定；无迁移、无新依赖。
- **负向**：
  - 示例回补任务收敛为一条全市场任务（ADR 0053 D5），存量实例需人工删旧的三条板块任务后重种；
  - 批大小翻倍后进度/水位最多滞后 1 万行（仍在 2s 轮询可接受范围）；
  - `data_path` 语法扩展引入「`|` 为分隔符」的约定，路径本身不能含 `|`；
  - 路径写错（缺失）不会再报错，而是静默按「无数据」落空批 → 只能从「入库 0 行且水位不动」的运行记录发现。
- **风险与缓解**：
  - 候选顺序写错会静默改变取数口径 → 需要多形态的资源由种子用例逐项断言候选顺序；
  - 配置路径拼错被当成无数据 → 运行记录保留 `fetched/inserted` 与每标的水位，长期零增长即为信号；
  - 提交合并后若落库成功而水位未提交，重跑会重复处理最后一批 → 幂等键保证不产生重复行，用例锁定「落库失败不推进水位」；
  - 索引缓存误跳过建索引（表被删除重建）→ 缓存键含 `db_table_name` 且仅进程内，重启即失效。

## 与既有 ADR 的关系

| 轴 | 载体 | 决定 | 由谁 |
|---|---|---|---|
| `rows_array` 记录形态与 `data_path` 模板 | `request_spec.record_mode` / `data_path` | 形态不变，`data_path` 增加候选语义 | ADR 0033（本 ADR D1 扩展） |
| 板块前缀拆任务与按标的水位 | `entrant_source.prefix_in` / `cursor=backfill_date` | 前缀能力保留；示例回补合并为一条全市场任务（ADR 0053 D5） | ADR 0034、ADR 0053 |
| 轻量落表 | `light=True` / `sync_options=False` | 不变 | ADR 0035 |
| 运行进度回写 | `datasource_sync_run.progress_*` | 仍每批回写，仅合并事务 | ADR 0037 D4（本 ADR D4 沿用） |
| 幂等口径 | `match_keys` 先查后写 | 不变；示例键改 `[股票代码, 日期]`（ADR 0053 D6） | ADR 0006、ADR 0053 |

## 落地状态（随实现更新）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 | 已落地 | `src/cndb/plugins/datasource/providers/http_json.py`、`examples/datasets/工作区-数据源示例/datasource.json` | `tests/test_datasource_http_json.py`、`tests/test_seed_datasource.py` |`2a8c519e` |
| P1 | 已落地 | `src/cndb/plugins/datasource/services/pipeline.py` | `tests/test_datasource_write_throughput.py` |`2a8c519e` |
| P2 | 已落地 | `src/cndb/plugins/datasource/services/write.py`、`src/cndb/plugins/datasource/services/runner.py` | `tests/test_datasource_write_throughput.py`、`tests/test_datasource_runner_streaming.py` |`2a8c519e` |

## 交接（会话结束更新）

- 当前阶段：P0-P2 全部落地，门禁全绿（`make check`：lint / typecheck / 前端静态与覆盖率 / 后端 96.98% 覆盖率，5464 passed）
- 已完成：候选路径回退与单测（5 例变异验证必失败）、批大小 10,000、索引 DDL 进程内缓存、每批一次提交、写吞吐复测（16.3k 行/s，3.83M 行 ≈236s）；2026-10-27 修订 D2：路径缺失 / `null` 按「无数据」返回 `[]`（北交所 `bj92xxxx` 不再整轮失败）
- 待人工：① 真源重跑确认失败标的归零（本机未连真源）；② 存量实例删除三条旧板块回补任务后重跑 `cndb seed`（口径同 ADR 0053 D10）
- 已知坑：`record_layout` 要求候选形态同构（6 列行数组共用）；路径缺失已按「无数据」返回 `[]`（D2 修订，2026-10-27），配置写错不再报错，只能从「入库 0 行 + 水位不动」发现；`_INDEXED_KEY_SETS` 仅进程内有效，表名由 `table_<uuid>` 生成、重建即换名，不会误跳过
- 下一步（不在本次范围，D5）：HTTP 连接复用（实测串行 3.9 → 11.3 req/s）、页级并发、按缺口算 `limit`、`wal_checkpoint(TRUNCATE)` 与 DNS 缓存
- 最近一次全绿：`make cov` @ 2026-10-27（96.67%，5820 passed / 3 skipped；D2 修订后）
