# ADR 0037: 数据源同步拉取提速与运行进度

Status: Accepted（已评审）
Date: 2026-10-26
Related: `src/cndb/plugins/tables/services/core/records.py`、`src/cndb/plugins/tables/services/importing/importer.py`、`src/cndb/plugins/datasource/{models,schemas,routers,services}`、`frontend/src/pages/datasource/`、ADR 0006 / 0034 / 0035
需求卡片: `docs/requirements/0037-datasource-sync-progress-speed.md`

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
