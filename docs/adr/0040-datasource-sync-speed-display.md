# ADR 0040: 数据源同步实时写入速度展示与端到端速度补齐

Status: Accepted（2026-10-26 需求方评审通过，按「完全补齐差距」执行）
Date: 2026-10-26
Related: `src/cndb/plugins/datasource/schemas.py`、`src/cndb/core/http.py`、`src/cndb/plugins/datasource/services/pipeline.py`、`src/cndb/plugins/tables/services/importing/importer.py`、`src/cndb/plugins/tables/services/core/records.py`、`frontend/src/api/datasource.ts`、`frontend/src/pages/datasource/DatasourcePage.tsx`、`examples/datasets/工作区-数据源示例/datasource.json`、`tests/test_api_fetch.py`、`tests/test_datasource_pipeline_concurrency.py`、`tests/test_datasource_api.py`、`frontend/src/pages/datasource/DatasourcePage.test.tsx`、ADR 0006 / 0034 / 0037 / 0039
需求卡片: `docs/requirements/0040-datasource-sync-speed-display.md`

## 口径（需求 → 设计落点）

需求原文：见需求卡片 §需求原句（逐字，ADR 不复制第二份）。

卡片约束沿用各自编号（C1..Cn），本表只补「设计怎么落地」，不重新拆句：

| 卡片约束 # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | 「同步过程中实时提示写入速度信息」 | D1/D2：`SyncRunOut` 增加服务端计算的 `elapsed_ms` / `rows_per_second`（零迁移），前端进度条区域展示「已写入行数 · 行/秒 · 已用时」 |
| C2 | 「和~/stock-strategy对比，同步速度方面是否还存在差距」 | 本文「行业对照」给出同机基准与端到端口径：抓取 20 vs 37.6 请求/秒；落库 16.4-17.5k vs 约 1M 行/秒（参考项目不逐格校验）；同步速度验收以端到端为准 |
| C3 | 「请完全补齐差距」（允许增加库依赖） | D3/D4：运行级共享 HTTP 客户端（37 → 90 请求/秒）+ 腾讯回补任务限速 10ms；D5：一次校验、一次归一（复用校验产出的归一值），跳过同步链路预览与字段级 diff；D6：不新增库依赖（评估结论）；验收：抓取 ≥85 请求/秒、落库 ≥25k 行/秒、端到端 ≤192s |

决策结论只在「决策记录」写一次；本节与正文不再罗列「已确认决策」。

## Context

现状逐条核对（以代码为准，标注 `文件:行号`）。沿用卡片「现状影响面」的编号，逐条给结论；ADR 新发现的条目追加编号。

| # | 现状 | 位置 | 影响 | 与卡片的关系 |
|---|---|---|---|---|
| 1 | `SyncRunOut` 只有终态 `duration_ms` 与 `fetched/inserted/updated`，运行中不返回耗时与速度 | `src/cndb/plugins/datasource/schemas.py:126-163` | 前端只能显示累计行数，无法回答「现在多快 / 还要多久」 | 确认 C1 |
| 2 | 运行中进度 Alert 显示「已完成/总请求 · 当前标的 · 已写入 N 行」，无速度与用时 | `frontend/src/pages/datasource/DatasourcePage.tsx:376-400` | 用户看不到写入速度 | 确认 C1 |
| 3 | `fetch_json` 每次调用都 `with httpx2.Client(...)` 新建并关闭连接 | `src/cndb/core/http.py:581-585` | 无 TLS 会话复用；同机 200 请求基准 37.3 请求/秒，共享 Client 为 89.9 | 确认 C3 |
| 4 | 腾讯日线回补任务 `rate_limit_ms=50` | `examples/datasets/工作区-数据源示例/datasource.json:28`（及同构的回补任务） | 全局相邻请求最小间隔 50ms → 20 请求/秒硬上限，是当前端到端的 binding constraint | 确认 C3 |
| 5 | 流式落表每批走 `analyze`→`execute`：构建 `new_preview/update_preview/field_diffs` 并批量回查旧行，同步链路只消费 `new_rows/update_rows` 与计数 | `src/cndb/plugins/tables/services/importing/importer.py:226`、`importer.py:580-620` | 10k 行批次 `build_upsert` 0.123-0.129s，其中旧行回查 0.024-0.049s、diff 0.014-0.015s 属可去除开销 | 确认 C3 |
| 6 | 更新路径二次归一：行已在校验阶段逐格 `validate_value` 并产出 `ValidationResult.normalized`，写入阶段 `_normalize_values` 再逐格校验一次 | `src/cndb/plugins/tables/services/core/records.py:49-140`、`records.py:1010-1023`、`importer.py:686-700` | 10k 行批次二次归一 0.189-0.218s，占批次总耗时约 35%；SQL 写本身仅 0.05-0.08s | 确认 C3 |
| 7 | 参考项目以模块级 `STATE` 输出「N/M · X只/秒」实时文案，落库用主键 `ON CONFLICT` 且**不做逐格校验** | `~/stock-strategy/src/stock_strategy/core/sync.py:661-695`、`~/stock-strategy/src/stock_strategy/core/store.py:570-585` | 交互基准；其写入吞吐约 1M 行/秒，但数据质量防线与本平台不同级 | 新增 C1/C2 |

写路径分解（真实库副本 1.153M 行、10k 行/批、连续 4 轮更新，SQL echo 关闭）：

| 组成 | 耗时（每 10k 行） | 说明 |
|---|---|---|
| `Importer.analyze` | 0.297-0.336s | `validate_all` 0.167-0.203s 为必要校验；`build_upsert` 0.123-0.129s |
| 二次 `_normalize_values` | 0.189-0.218s | 与校验阶段重复的逐格校验与逐行字段表构建 |
| 写入与 link 预校验 | 0.05-0.08s | 分组 `executemany`，SQL 层不是瓶颈 |
| 批次总计 | 0.570-0.611s | 16.4-17.5k 行/秒 |

**核心缺陷（需求要补的）**：运行记录能表达「做了多少」，但不能表达「正在以多快速度做、已经做了多久」；同时抓取层每次请求重建 TLS 连接、示例任务限速偏保守，落库层又把已经校验过的值再校验一遍并构建无人消费的预览，导致端到端慢于参考项目约 1.9×。

设计目标（不变量）：

- **I1 展示口径**：运行中 `elapsed_ms` 单调不减且 `rows_per_second >= 0`；`status != running` 时 `elapsed_ms == duration_ms`，速度与最终计数自洽（误差仅来自取整）；ADR 0037 I3 的进度不变量不变。
- **I2 抓取语义不变**：每个请求仍逐次 `validate_url`（SSRF）、逐跳重定向校验、超时 / 重试 / 退避、空页停止、单请求失败不中断、`rate_limit_ms` 与 `workers` 语义、水位推进全部不变；共享 Client 只改变连接生命周期。
- **I3 落库语义不变**：逐格校验、行级写范围、软删跳过、link 写入、`partial` 列语义、`on_update` 自动填充、幂等匹配集合、`inserted/updated/skipped` 计数口径不变；「一次校验、一次归一」必须以等价性用例证明写入结果与旧路径逐行一致。
- **I4 默认行为不变**：`fetch_json(config)` 不传 Client 时与现状完全一致；`preview` / 归一复用缺省关闭，导入预览与接口契约不变；零迁移。

## Decision

### 1. 数据模型

无新表 / 新列 / 迁移。速度与耗时由现有 `fetched`、`started_at`、`duration_ms` 推导；归一复用只改内存数据结构，不改表结构。

### 2. 判定算法（唯一入口）

`SyncRunOut.from_model(run, *, now: dt.datetime | None = None)` 是速度计算的唯一入口（`now` 仅为测试注入）：

- `elapsed_ms = run.duration_ms`（`status != "running"`）否则 `max(0, (now - run.started_at).total_seconds() * 1000)`；
- `rows_per_second = round(run.fetched * 1000 / elapsed_ms, 1)`，仅当 `elapsed_ms >= 1000` 时计算，否则 `0.0`；
- 取整后若 `fetched > 0` 且结果为 `0.0`，按 `0.1` 输出；
- 运行历史、运行结果、CLI 一律经本入口，不各自计算。

### 3. API 变更清单

| 端点 | 变更 |
|---|---|
| `GET /v1/workspaces/{wid}/datasource/sync-jobs/{id}/runs` | `SyncRunOut` 新增只读字段 `elapsed_ms`（Int）、`rows_per_second`（Float） |
| `POST .../sync-jobs/{id}/run` | 响应内 `run` 复用同一 `SyncRunOut`，随之带出新字段（无契约破坏） |

### 4. 边界与例外

1. 运行中按服务端 UTC 时钟计算，前端只渲染，不使用浏览器时钟做差。
2. `progress_total == 0`（尚未展开计划）时前端显示「准备中」，不显示速度。
3. 运行失败 / 中断：`elapsed_ms` 取 `duration_ms`，速度按已写入行数计算，保留失败现场。
4. `fetched == 0` 时 `rows_per_second = 0.0`，不出现除零或 `NaN`。
5. 速度为计算值，不写回数据库；重启 / 多副本读数一致。

### 5. 迁移

无（零迁移）。`SyncRunOut` 为响应模型；归一复用为内存结构，不改 `datasource_sync_run` 与业务表。

### 6. 前端

| 层 | 文件 | 改动 |
|---|---|---|
| API 类型 | `frontend/src/api/datasource.ts` | `SyncRun` 增加 `elapsed_ms: number`、`rows_per_second: number` |
| 格式化工具 | `frontend/src/pages/datasource/syncProgress.ts`（新增） | `formatElapsed(ms)`（如 `1分40秒`）、`formatRate(v)`（如 `12.3 行/秒`） |
| 页面 | `frontend/src/pages/datasource/DatasourcePage.tsx` | 运行中 Alert 文案改为「`{done}/{total}` 请求 · 当前标的 … · 已写入 `{fetched}` 行 · `{rate}` · 已用时 `{elapsed}`」；`progress_total == 0` 时保持「准备中」；轮询间隔仍为 2s（ADR 0037 D5） |

### 7. 抓取层：连接复用与限速（P1）

- `src/cndb/core/http.py` 新增 `open_http_client(...)` 上下文管理器（`follow_redirects=False`），并把「给定 Client 发起一次请求」抽为内部函数；
- `fetch_json(config, *, client: httpx2.Client | None = None)`：传入 Client 时复用，不传时维持「新建 + 关闭」旧行为（I4）；每个请求仍设置本次 `headers` / `timeout` / `params`，仍逐次 `validate_url`；
- `run_pipeline` 在单次运行内打开一个共享 Client，构造缺省抓取器 `lambda config: fetch_json(config, client=client)`，保持既有优先级：显式注入 `fetch` > `plan.fetcher` > 缺省抓取器（I4）；退出（含异常）由上下文关闭连接；
- 示例任务：三支「腾讯回补」日线任务 `rate_limit_ms` 50 → 10（上限 100 请求/秒，实测共享连接可达 90-104 请求/秒）；新浪快照 / 股票清单 / 大模型任务不动；触发对端风控时由既有长退避与「疑似限流」提示兜底，必要时把任务限速调回。

### 8. 落库层：一次校验、一次归一（P2）

- `Importer.analyze` 新增 `preview: bool = True`；为 `False` 时 `_build_upsert_result` 仍产出 `new_rows/update_rows/new_count/update_count/multi_key_conflicts`，跳过 `_fetch_old_rows_by_ids`、`_build_field_diffs` 与 `new_preview/update_preview`；
- `preview=False` 时 `update_rows` 条目额外携带 `result.normalized`（db_column → 已校验值）；`records.bulk_update_rows` 新增 `reuse_normalized: bool = False`：启用时按「物理列 / link / auto_fill」预编译计划直接取用已校验值，只补 `on_update` 自动填充，不再调用 `validate_value` 二次逐格归一；缺省路径行为不变（I3/I4）；
- `_normalize_values` 的逐行 `field_map` 构建与 auto_fill 配置解析改为批级预编译计划（同样只影响传入计划的调用方），降低创建路径与未复用路径的固定开销；
- 仅 `services/write.py::upsert_rows` 在 `light=True`（数据源同步）时传 `preview=False` 与 `reuse_normalized=True`；导入接口 / 前端预览不传；
- 不引入唯一索引 / `ON CONFLICT`：SQL 层实测不是瓶颈（裸 `executemany` 50 万行/秒级），且会推翻 ADR 0006 的幂等口径。

### 9. 测试清单

**判定层（单测）**：`SyncRunOut.from_model` 的运行中 / 已结束 / 失败三态（注入 `now`）、`elapsed_ms < 1000` 走 0、`fetched == 0` 不除零；`formatElapsed` / `formatRate` 边界（0、59s、1h+）。

**接口层**：`GET .../runs` 返回新字段且结束值等于 `duration_ms`；`POST /run` 响应带新字段；运行中字段随批单调增长（沿用 runner 流式桩）。

**抓取层**：`fetch_json` 传入共享 Client 时不新建、不关闭 Client，且仍逐请求 `validate_url`；`run_pipeline` 一次运行只创建一个共享 Client（spy `open_http_client`），显式 `fetch` 注入时不创建；异常路径 Client 被关闭。

**落库层（等价性）**：`preview=False` 与默认模式的 `new_rows/update_rows` 与 `inserted/updated/skipped` 完全等价；`reuse_normalized=True` 与旧路径在 `date` / `datetime`（含 `on_update` 自动填充）/ `number`（scale）/ `select` / `link` 字段上的物理列值与关联表写入逐行一致；未知字段 / 软删 / 行级写范围 / `partial` 列语义不变；默认路径仍逐格校验（spy `validate_value` 次数）。

**迁移 / 备份**：无迁移；既有迁移 / 备份往返用例保持全绿。

**e2e（前端）**：不新增（现有 e2e 不跑真实同步；进度与速度由组件单测覆盖）。

**基准（人工复测，不作 CI 门槛）**：同机同口径复测抓取请求/秒、10k 行落库行/秒、3.83M 行端到端耗时，结果回填「行业对照」。

### 10. 分期

| 期 | 内容 | 风险 |
|---|---|---|
| **P0** | 速度字段（计算入口 + API）+ 前端展示与格式化工具 | 低（零迁移、只加只读字段） |
| **P1** | 运行级共享 Client + 腾讯回补任务限速 50 → 10ms | 中（连接生命周期与线程安全；用既有抓取 / 并发用例兜底） |
| **P2** | `preview=False` + 归一复用 + 批级预编译归一计划 | 中（需等价性用例证明写入结果不变，防止误伤导入预览） |

## 决策记录（唯一决策台账）

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | 速度口径 | 运行中展示**累计平均写入速度** = 已写入行数 / 已用时，服务端计算 | 轮询 2s 下累计值稳定可读；参考项目同为累计「只/秒」 | 前端按相邻轮询差值算瞬时速度（抖动大、刷新即失真）；新增速度列（纯展示引入写放大与迁移） | `schemas.py`、`DatasourcePage.tsx` |
| D2 | 展示载体 | 复用现有运行中 Alert + 进度条，追加「行/秒 · 已用时」 | 现有位置已被用户认知，改动面最小 | 独立图表 / SSE / WebSocket（运维与前端复杂度不划算） | `DatasourcePage.tsx` |
| D3 | 抓取连接 | 单次运行共享一个 `httpx2.Client`，逐请求保留 SSRF / 超时 / 重试 / 重定向语义 | 同机基准：每请求新 Client 37.3 请求/秒 → 共享 Client 89.9（10 线程） | 进程级全局 Client（生命周期与测试隔离难）；单纯加大 `workers`（限速才是硬上限）；自建 DNS 缓存（实测无收益） | `core/http.py`、`pipeline.py` |
| D4 | 示例任务限速 | 腾讯回补日线任务 50ms → 10ms（上限 100 请求/秒） | 端到端补齐要求抓取 ≤153s，需 ≥65 请求/秒；共享连接实测 90-104，10 线程下 100 上限可达 | 维持 50ms（20 请求/秒成为硬瓶颈）；保持 20ms（上限 50，抓取 199s 无法补齐） | `datasource.json` |
| D5 | 落库提速 | 一次校验、一次归一：`preview=False` + `reuse_normalized=True` + 批级归一计划；逐格校验不放宽 | 二次归一 0.189-0.218s、预览回查与 diff 0.038-0.064s，占批次约 40%；SQL 写仅 0.05-0.08s；预计 24-28k 行/秒 | 撤掉逐格校验（数据质量回退，违反 I3）；唯一索引 `ON CONFLICT`（SQL 非瓶颈，且推翻 ADR 0006 口径） | `importer.py`、`records.py`、`write.py` |
| D6 | 新增依赖 | 不新增库依赖 | 实测瓶颈是 Python 逐格归一与重复校验，换 JSON / SQLite 驱动无对应收益；用户已授权，但本方案评估为不需要 | 引入 orjson / msgspec 等（解析与校验不是本次热点；增加打包与供应链成本） | 无 |
| D7 | 字段落点 | 速度 / 耗时为响应模型计算字段，不入库 | 无消费方需要历史速度；避免迁移与写放大 | 持久化到运行表（需迁移、每批多写两列） | `schemas.py` |
| D8 | 对标验收口径 | 「同步速度」以**端到端同口径耗时**验收（同机、腾讯日线、3.83M 行），不把参考项目无校验的裸 SQL 写入当作验收项 | 两者数据质量防线不同级；端到端才是用户感知指标 | 用裸写入行/秒对齐（不可比，将迫使放弃校验） | ADR「行业对照」 |

门禁：`Proposed` → `Accepted` 前本表不得有「待定」；结论只在本书出现，别处只引用编号。

## Consequences

- **正向**：运行中可见写入速度与已用时；抓取约 2.4×（37 → 90 请求/秒）；落库预计 16.4-17.5k → 24-28k 行/秒；端到端从实测 370.4s 压到约 155-170s，补齐参考项目约 192s 的水平。
- **负向**：共享 Client 把运行期连接集中在单点，需保证退出即关闭；归一复用要求「校验产出的 `normalized`」与写入语义严格对齐，等价性测试成本上升。
- **风险与缓解**：限速降到 10ms 可能触发对端风控 —— 保留长退避与「疑似限流」提示，必要时任务限速调回；归一复用误伤导入预览 —— 只由数据源同步显式启用，默认路径不变并有用例锁定；基准受机器与网络波动影响 —— 只做同机前后对比，不作为 CI 门槛。

## 行业对照

基准口径（2026-10-26，同机、腾讯日线 800 根、10 线程、SQLite WAL/NORMAL）：

| 维度 | stock-strategy | cndb 现状 | 差距 | 本设计（P1/P2 后） |
|---|---|---|---|---|
| 抓取吞吐（请求/秒） | 37.6（`urllib` 每请求新建连接、无全局限速） | 约 20（限速 50ms + 每请求新 Client）；基准 37.3 | 约 1.9× | 共享 Client 89.9（10 线程）/ 104.3（16 线程），限速 10ms 时上限 100 |
| 落库吞吐（行/秒） | 约 1.0M（主键 `WITHOUT ROWID` + `executemany ON CONFLICT`，**无逐格校验**） | 16.4-17.5k（10k 行更新批实测；逐格校验 + 字段类型 + 关联字段） | 约 60× | 目标 ≥25k（去重复归一与预览后估算 24-28k） |
| 端到端（约 3.83M 行 / 9,956 请求） | 约 192s（7,000 标的 × 800 根 ≈ 5.6M 行，抓取 186s + 写入 6s） | 实测 370.4s（约 10.3k 行/秒，抓取受 20 请求/秒限制） | 约 1.9× | 抓取约 111s、落库约 153s，折算 155-170s，**补齐到参考项目水平** |

落库绝对行速差距（约 60×）的定性结论：参考项目的 1M 行/秒建立在「信任源站、不做逐格校验」之上，与 cndb 通用平台（字段类型 / 必填 / 选项 / 关联 / 行级权限）不是同一口径；按 D8 的端到端口径补齐，不把裸写入行速作为验收项。因此「是否还存在差距」的答案是：**端到端差距本次补齐；裸写入行速差距属校验能力的固有成本，不在验收口径内。**

来源：本机基准脚本（`/tmp/cmp_fetch.py`、`/tmp/cmp_write.py`、`/tmp/bench_breakdown.py`，随交接清理）；`~/stock-strategy` 源码 `core/sync.py`、`core/store.py`。

## 与既有 ADR 的关系

| 轴 | 载体 | 决定 | 由谁 |
|---|---|---|---|
| 运行进度与轮询 | `datasource_sync_run.progress_*`、前端 2s 轮询 | 进度语义与轮询频率沿用，不新增通道 | ADR 0037 D4/D5 |
| 抓取并发 / 限速 | `request.workers`、`rate_limit_ms` | 语义不变，只调示例任务取值 | ADR 0034 D5 |
| 网络层 | `core/http.py` | 本次补上 ADR 0039 交接中「连接复用」这一遗留项 | ADR 0039 交接 |
| 落库幂等 | 先查后写 + 非唯一索引 | 不引入唯一索引 / `ON CONFLICT` | ADR 0006、ADR 0034 D6 |

## 落地状态（随实现更新）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 | 已落地 | `src/cndb/plugins/datasource/schemas.py`、`frontend/src/api/datasource.ts`、`frontend/src/pages/datasource/syncProgress.ts`、`frontend/src/pages/datasource/DatasourcePage.tsx` | `tests/test_datasource_sync_speed.py`、`tests/test_datasource_api.py`、`frontend/src/pages/datasource/syncProgress.test.ts`、`frontend/src/pages/datasource/DatasourcePage.test.tsx` | `5cc0a440` |
| P1 | 已落地 | `src/cndb/core/http.py`、`src/cndb/plugins/datasource/services/pipeline.py`、`examples/datasets/工作区-数据源示例/datasource.json` | `tests/test_api_fetch.py`、`tests/test_datasource_pipeline_concurrency.py`、`tests/test_seed_datasource.py` | `5cc0a440` |
| P2 | 已落地 | `src/cndb/plugins/tables/services/importing/importer.py`、`src/cndb/plugins/tables/services/core/records.py`、`src/cndb/plugins/datasource/services/write.py` | `tests/test_import_preview_and_reuse.py`、`tests/test_datasource_write_throughput.py`、`tests/test_import_light_mode_equivalence.py` | `5cc0a440` |

## 交接（会话结束更新）

- 当前阶段：P0-P2 已落地（2026-10-26），待人工做真源端到端复测
- 已完成：P0 速度字段与前端展示、P1 共享客户端与示例任务限速 10ms、P2 预览关闭与归一复用；写路径实测 10,000 行更新批 16.4-17.5k → 24.8-26.8k 行/秒
- 下一步（待人工）：① 在存量实例重跑腾讯日线回补，按 D8 口径记录端到端耗时并回填「行业对照」；② 观察限速 10ms 是否触发对端风控，必要时把任务 `rate_limit_ms` 调回
- 已知坑：基准为同机单次测量，绝对吞吐受网络与机器负载影响，只做同机横向对比；`preview=False` / 归一复用只能由数据源同步链路传入，防止导入预览回归；共享 Client 必须在异常路径也关闭；`bulk_update_rows(reuse_normalized=True)` 对 `updates` 条目里没有 `normalized` 的字段仍走逐格校验，不改变数据质量
- 最近一次全绿：`make check` @ `5cc0a440`（2026-10-26，后端 5482 passed / 覆盖率 96.99%）
