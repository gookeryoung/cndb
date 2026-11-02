# ADR 0037: 数据同步拉取提速与运行进度

Status: Implemented（已评审；2026-10-27 人工确认 P0-P2 全期落地）
Date: 2026-10-26
Related: `src/cndb/plugins/tables/services/core/records.py`、`src/cndb/plugins/tables/services/importing/importer.py`、`src/cndb/plugins/datasource/{models,schemas,routers,services}`、`frontend/src/pages/datasource/`、ADR 0006 / 0034 / 0035
需求卡片: `docs/requirements/0037-datasource-sync-progress-speed.md`
> 本 ADR 已合并原 ADR 0040（数据同步实时写入速度展示与端到端速度补齐），口径 / 决策 / 落地状态见文末「续作」小节（编号 0040 不复用）。

## 口径（需求 → 设计落点）

需求原文：见需求卡片 §需求原句（逐字，ADR 不复制第二份）。

卡片约束沿用各自编号（C1..Cn），本表只补「设计怎么落地」，不重新拆句：

| 卡片约束 # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | 拉取速度显著慢于参考项目 | D2：`find_rows_by_key` 的 `OR (k1 AND k2…)` 改按行值 `IN`；D3：`bulk_update_rows` 归一一次 + 按列签名分组 `executemany`，语义（行级权限、软删、link、计数）不变 |
| C2 | 运行中显示进度 | D4：运行记录新增 `progress_total` / `progress_done` / `progress_entrant`，批间回写并提交；运行历史端点返回，前端运行期间 2s 轮询 |
| C3 | 修复「慢且无进度」的可用性问题 | D1：`POST /run` 建运行记录后立即返回（202），执行转后台线程并续租；前端据运行状态轮询收尾 |

决策结论只在「决策记录」写一次；本节与正文不再罗列「已确认决策」。

## Context

现状逐条核对（以代码为准，标注 `文件:行号`）。

| # | 现状 | 位置 | 影响 | 与卡片的关系 |
|---|---|---|---|---|
| 1 | 幂等匹配按 500 键拼一个巨型 `OR (k1 AND k2 AND …)`，每块重新构造 SQL | `records.py:934-958` | 5000 行批次实测 0.54s，占单批 0.9s 的 60% | 确认 C1 |
| 2 | `bulk_update_rows` 每行先预校验再解析一次，再逐行 `UPDATE`；5000 行即 5000 条语句 | `records.py:968-1043` | 每行 normalize 两次 + 5000 次解析/执行，单批 1.1s | 确认 C1 |
| 3 | `POST /run` 同步执行到跑完才返回；前端 axios 全局超时 30s | `routers/sync_jobs.py:312-331`、`frontend/src/api/client.ts:95` | 全市场回补一轮 >10 分钟，前端 30s 即报「运行失败」，服务端仍在跑 | 确认 C3 |
| 4 | 运行记录只在结束时写 `fetched/inserted/updated`，无请求级进度 | `models.py:136-164`、`runner.py:664-707` | 运行中只能看到按钮 loading | 确认 C2 |
| 5 | 管线已有分组并发与全局限速，但 `_run_group` 逐请求串行且不回传进度 | `services/pipeline.py:216-250` | 无请求完成计数可给 UI | 新增 C2 |
| 6 | 参考项目以线程池并发逐标的拉取、`done/total` 进度条 + 2s 轮询 | `~/stock-strategy/src/stock_strategy/core/sync.py:657-718`、`frontend/src/app/Layout.tsx:25-103` | 交互基准 | 新增 C2 |

**核心缺陷（需求要补的）**：同步运行是「黑盒同步请求」——落库吞吐受应用层逐行 SQL 制约，运行中既无请求级进度也无法在前端 30s 超时内收到响应。

设计目标（不变量）：

- **I1 抓取语义不变**：分页/分组并发/`rate_limit_ms`/空页停止/失败不中断/水位推进与租约续期均不改；仅改运行调度与落库 SQL 形态。
- **I2 落库语义不变**：幂等键匹配集合、冲突行取 `min(id)`、软删行不更新、行级写范围过滤、link 写入、`inserted/updated` 计数口径与现有测试完全一致。
- **I3 可观测**：运行中任意时刻可从 `GET /sync-jobs/{id}/runs` 读到 `progress_done/progress_total`，且 `progress_done <= progress_total`；结束后 `progress_done == 已完成请求数`。
- **I4 单飞不变**：同一 job 任意时刻至多一个执行者；后台执行沿用 DB 租约，退出即释放。

## Decision

### 1. 数据模型

`datasource_sync_run` 新增三列（均 `NOT NULL DEFAULT`，存量零迁移）：

| 列 | 类型 | 口径 |
|---|---|---|
| `progress_total` | Integer | 本轮计划请求数（`len(build_requests)`），0 表示尚未展开 |
| `progress_done` | Integer | 已完成请求数（成功 + 失败），每批落库时回写 |
| `progress_entrant` | String(64) | 最近完成的标的（UI 展示「当前标的」），空串表示无 |

`job.last_status` 在运行开始时写 `running`（前端刷新页面后可据任务列表恢复轮询）。

### 2. 判定算法（唯一入口）

- 落库批量化入口仍是 `records.find_rows_by_key` / `records.bulk_update_rows`，不新增旁路：
  - `find_rows_by_key`：每块先对全部键走行值 `tuple_(*cols).in_(chunk)`；SQLite 行值 IN 对 NULL 永不命中，含 None 的键再由 `OR + IS NULL` 兜底（`IS NULL` 语义不变）；块大小 500。
  - `bulk_update_rows`：进入事务前一次性 `_normalize_values` 并缓存；无 link 值且无行级写范围的行按归一列集合签名分组，`UPDATE … WHERE id = :_rid AND _trashed = 0` 走 `executemany`，`result.rowcount` 累加（SQLite 的 executemany rowcount 为实际影响行数之和）；有 link 值的行保持逐行写（link 需按行 id 写关联表）；`row_scope` 非空时整组退回逐行 `UPDATE`——行级过滤条件可能含 `in` / `not_in` 的 expanding 参数，SQLAlchemy 不允许与 `executemany` 同用。
- 运行入口：
  - 新增 `runner.create_run` / `runner.start_job`（建记录 + `job.last_status=running` + 提交后 `spawn` 后台）；`runner.execute_run_in_background` 用绑定同一 engine 的 session 工厂重载 job/user/run，调 `execute_job(..., existing_run=run, lease=lease)`，`finally` 释放租约。
  - `execute_job` 新增可选 `existing_run` 参数（后台路径复用已建记录；调度 / CLI 不传时行为不变）。
  - `run_pipeline` 新增可选 `progress: RequestProgress`（线程安全计数）：展开后 `set_total(len(plans))`，每个请求结束（成功或失败）`tick(entrant)`；runner 在 `_StreamingState.on_batch` 把计数与累计计数写入 run 并提交。

### 3. API 变更清单

| 端点 | 变更 |
|---|---|
| `POST /v1/workspaces/{wid}/datasource/sync-jobs/{id}/run` | 由同步执行改为「建运行记录 + 释放请求」：抢租约成功后返回 200，`run.status=running`；执行在后台线程 |
| `GET /v1/workspaces/{wid}/datasource/sync-jobs/{id}/runs` | 返回新增 `progress_total` / `progress_done` / `progress_entrant` |

### 4. 边界与例外

1. 后台执行异常仍由 `execute_job` 落 `failed` 记录，不漏留痕；租约在后台线程 `finally` 释放。
2. 后台线程 session 通过 `db.get_bind()` 新建工厂（测试库为共享内存 engine，生产为同一 engine），不引用请求期 session。
3. `progress_done` 只由主线程按批回写，避免并发写同一 session；批间隔内进度最多滞后一批（≤5000 行）。
4. 无流式批次（空结果 / llm_prompt 单请求）时，最终 `progress_done = progress_total` 由收尾统一写入。
5. 前端轮询间隔 2s，运行结束后自动停止并提示最终统计；页面刷新后按 `job.last_status == running` 恢复轮询。

### 5. 迁移

单条 alembic 迁移（`down_revision = a9d4e8f1c2b6`）为 `datasource_sync_run` 加三列，服务端默认值补齐存量行；`downgrade` 删除三列。

### 6. 前端

| 层 | 文件 | 改动 |
|---|---|---|
| API 类型 | `frontend/src/api/datasource.ts` | `SyncRun` 增加 `progress_total/progress_done/progress_entrant` |
| 页面 | `frontend/src/pages/datasource/DatasourcePage.tsx` | 运行中显示进度条（已完成/总请求、当前标的、已写入行数、百分比）；运行期每 2s 轮询运行历史；运行开始/结束提示；任务列表「上次运行」显示运行中；刷新页面后按 `last_status=running` 恢复轮询 |

### 7. 测试清单

**判定层（单测）**：`find_rows_by_key` 行值 IN 路径与含 None 键回退、`bulk_update_rows` executemany 分组（不同列集合 / 软删跳过 / 行级权限 / link 行回退 / 计数）。

**接口层**：`POST /run` 立即返回 running 记录（后台同步桩）、轮询 runs 得到最终 success、进度字段随批更新、运行历史返回新字段。

**迁移 / 备份**：`test_datasource_migration` 新增/降级三列；`test_migration_missing_model_columns` head 同步。

**e2e（前端）**：不新增（进度展示由组件单测覆盖；现有数据源 e2e 不变）。

### 8. 分期

| 期 | 内容 | 风险 |
|---|---|---|
| **P0** | `records` 两条批量化 + 单测 | 低（语义不变，有既有用例兜底） |
| **P1** | 运行记录进度列 + 迁移 + 管线/runner 回写 | 中（迁移 head 变更需同步测试常量） |
| **P2** | `POST /run` 转后台 + 前端进度轮询 | 中（线程与测试库 StaticPool，测试用同步桩） |

## 决策记录（唯一决策台账）

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | 长任务运行方式 | 端点建记录后立即返回，后台线程执行并沿用租约 | 前端 axios 30s 超时；参考项目同为用户可关闭页面 | 保持同步 + 前端只加轮询（30s 后必报失败，服务端仍在跑，误导用户） | `routers/sync_jobs.py`、`services/runner.py` |
| D2 | 匹配查询批量化 | 按行值 `tuple IN` 分块，含 None 回退旧形态 | 实测 5000 键 0.54s → 约 0.10s；SQL 语义等价 | 保留 OR 链（线性膨胀，随批次变慢） | `records.py` |
| D3 | 更新批量化 | 归一一次 + 按列签名分组 executemany | 实测 5000 行更新 1.1s → 约 0.09s；rowcount 语义等价 | SQL 暂存表 `UPDATE…FROM`（跨方言、冲突行/权限语义需重验，收益边际） | `records.py` |
| D4 | 进度载体 | run 表三列 + 批间回写，前端轮询 | 与参考项目 `done/total` 同构；无需 SSE/WS | 进程内全局状态（多副本不可见）、SSE（运维复杂度） | `models.py`、`pipeline.py`、`runner.py`、`DatasourcePage.tsx` |
| D5 | 前端轮询频率 | 2s，运行结束即停 | 参考项目同为 2s；一次运行请求量很小 | 1s（无收益）、5s（体验滞后） | `DatasourcePage.tsx` |

门禁：`Proposed` → `Accepted` 前本表不得有「待定」；结论只在本书出现，别处只引用编号。

## Consequences

- **正向**：单批落库约 0.9s → 0.45s（≈2×）；全市场回补一轮从十几分钟降到约一半；运行中可见请求级进度；长任务不再被 30s 前端超时误报失败。
- **负向**：新增后台线程与三列迁移；进度最多滞后一个批次。
- **风险与缓解**：后台线程与请求 session 隔离（新建工厂 + 仅主线程回写）；测试用同步桩（沿用导入后台任务的既有约定）；迁移 downgrade 可回退。

## 落地状态（随实现更新）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 | 已落地 | `src/cndb/plugins/tables/services/core/records.py` | `tests/test_import_pipeline.py` | `f976829b` |
| P1 | 已落地 | `src/cndb/plugins/datasource/models.py`、`src/cndb/plugins/datasource/services/pipeline.py`、`src/cndb/plugins/datasource/services/runner.py`、`src/cndb/alembic/versions/c4d5e6f7a8b9_add_datasource_sync_run_progress.py` | `tests/test_datasource_runner.py`、`tests/test_datasource_migration.py`、`tests/test_datasource_pipeline_concurrency.py` | `f976829b` |
| P2 | 已落地 | `src/cndb/plugins/datasource/routers/sync_jobs.py`、`src/cndb/plugins/datasource/schemas.py`、`frontend/src/pages/datasource/DatasourcePage.tsx` | `tests/test_datasource_api.py`、`frontend/src/pages/datasource/DatasourcePage.test.tsx` | `f976829b` |

## 交接（会话结束更新）

- 当前阶段：P0-P2 全部落地
- 已完成：需求卡片、ADR、批量化落库、运行进度三列与迁移、`POST /run` 转后台、前端进度轮询
- 下一步：无（真实数据源全量回补的提速与进度可观测性由人工演练验收）
- 已知坑：测试库为 StaticPool 单连接内存库，后台执行必须在测试中同步化（`tests/test_datasource_api.py` 的 `sync_background_spawn` fixture）；新增迁移后同步 `test_migration_missing_model_columns.HEAD_REVISION`；`bulk_update_rows` 的 `executemany` 不能叠加 `row_scope`（`in` / `not_in` 为 expanding 参数），带权限时必须逐行更新，见判定算法一节
- 最近一次全绿：`make check` @ 2026-10-26（后端 5440 passed / 覆盖率 96.98%，前端覆盖率达标）

## 续作：数据同步实时写入速度展示与端到端速度补齐（原 ADR 0040，已并入本 ADR）

> 原独立文件已删除，编号 0040 不复用（追溯：`git log -- docs/adr/0040-datasource-sync-speed-display.md`）。下列各节保留原 ADR 的约束 / 决策编号，代码与提交里的 `ADR 0040 Cx / Dx` 指的就是本节。
> 需求卡片：`docs/requirements/0040-datasource-sync-speed-display.md`（需求原文与约束编号的唯一副本）

### 口径（原 ADR 0040）

需求原文：见需求卡片 §需求原句（逐字，ADR 不复制第二份）。

卡片约束沿用各自编号（C1..Cn），本表只补「设计怎么落地」，不重新拆句：

| 卡片约束 # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | 「同步过程中实时提示写入速度信息」 | D1/D2：`SyncRunOut` 增加服务端计算的 `elapsed_ms` / `rows_per_second`（零迁移），前端进度条区域展示「已写入行数 · 行/秒 · 已用时」 |
| C2 | 「和~/stock-strategy对比，同步速度方面是否还存在差距」 | 本文「行业对照」给出同机基准与端到端口径：抓取 20 vs 37.6 请求/秒；落库 16.4-17.5k vs 约 1M 行/秒（参考项目不逐格校验）；同步速度验收以端到端为准 |
| C3 | 「请完全补齐差距」（允许增加库依赖） | D3/D4：运行级共享 HTTP 客户端（37 → 90 请求/秒）+ 腾讯回补任务限速 10ms；D5：一次校验、一次归一（复用校验产出的归一值），跳过同步链路预览与字段级 diff；D6：不新增库依赖（评估结论）；验收：抓取 ≥85 请求/秒、落库 ≥25k 行/秒、端到端 ≤192s |

决策结论只在「决策记录」写一次；本节与正文不再罗列「已确认决策」。

### Decision（原 ADR 0040）

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
- 仅 `services/write.py::upsert_rows` 在 `light=True`（数据同步）时传 `preview=False` 与 `reuse_normalized=True`；导入接口 / 前端预览不传；
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

### 决策记录（原 ADR 0040）

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

### 与既有 ADR 的关系（原 ADR 0040）

| 轴 | 载体 | 决定 | 由谁 |
|---|---|---|---|
| 运行进度与轮询 | `datasource_sync_run.progress_*`、前端 2s 轮询 | 进度语义与轮询频率沿用，不新增通道 | ADR 0037 D4/D5 |
| 抓取并发 / 限速 | `request.workers`、`rate_limit_ms` | 语义不变，只调示例任务取值 | ADR 0034 D5 |
| 网络层 | `core/http.py` | 本次补上 ADR 0039 交接中「连接复用」这一遗留项 | ADR 0039 交接 |
| 落库幂等 | 先查后写 + 非唯一索引 | 不引入唯一索引 / `ON CONFLICT` | ADR 0006、ADR 0034 D6 |

### 落地状态（原 ADR 0040）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 | 已落地 | `src/cndb/plugins/datasource/schemas.py`、`frontend/src/api/datasource.ts`、`frontend/src/pages/datasource/syncProgress.ts`、`frontend/src/pages/datasource/DatasourcePage.tsx` | `tests/test_datasource_sync_speed.py`、`tests/test_datasource_api.py`、`frontend/src/pages/datasource/syncProgress.test.ts`、`frontend/src/pages/datasource/DatasourcePage.test.tsx` | `5cc0a440` |
| P1 | 已落地 | `src/cndb/core/http.py`、`src/cndb/plugins/datasource/services/pipeline.py`、`examples/datasets/工作区-数据源示例/datasource.json` | `tests/test_api_fetch.py`、`tests/test_datasource_pipeline_concurrency.py`、`tests/test_seed_datasource.py` | `5cc0a440` |
| P2 | 已落地 | `src/cndb/plugins/tables/services/importing/importer.py`、`src/cndb/plugins/tables/services/core/records.py`、`src/cndb/plugins/datasource/services/write.py` | `tests/test_import_preview_and_reuse.py`、`tests/test_datasource_write_throughput.py`、`tests/test_import_light_mode_equivalence.py` | `5cc0a440` |

### 交接（原 ADR 0040）

- 当前阶段：P0-P2 已落地（2026-10-26），待人工做真源端到端复测
- 已完成：P0 速度字段与前端展示、P1 共享客户端与示例任务限速 10ms、P2 预览关闭与归一复用；写路径实测 10,000 行更新批 16.4-17.5k → 24.8-26.8k 行/秒
- 下一步（待人工）：① 在存量实例重跑腾讯日线回补，按 D8 口径记录端到端耗时并回填「行业对照」；② 观察限速 10ms 是否触发对端风控，必要时把任务 `rate_limit_ms` 调回
- 已知坑：基准为同机单次测量，绝对吞吐受网络与机器负载影响，只做同机横向对比；`preview=False` / 归一复用只能由数据同步链路传入，防止导入预览回归；共享 Client 必须在异常路径也关闭；`bulk_update_rows(reuse_normalized=True)` 对 `updates` 条目里没有 `normalized` 的字段仍走逐格校验，不改变数据质量
- 最近一次全绿：`make check` @ `5cc0a440`（2026-10-26，后端 5482 passed / 覆盖率 96.99%）
