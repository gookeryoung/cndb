# ADR 0041: 数据源同步顶部运行中任务多行列表

Status: Implemented（2026-10-26 需求方评审通过；2026-10-27 人工确认 P0-P1 全期落地）
Date: 2026-10-26
Related: `frontend/src/pages/datasource/DatasourcePage.tsx`、`frontend/src/pages/datasource/syncProgress.ts`、`frontend/src/pages/datasource/DatasourcePage.test.tsx`、`frontend/src/pages/datasource/syncProgress.test.ts`、`frontend/src/api/datasource.ts`、`src/cndb/plugins/datasource/routers/sync_jobs.py`、`src/cndb/plugins/datasource/services/runner.py`、ADR 0006 / 0034 / 0037 / 0040
需求卡片: `docs/requirements/0041-datasource-running-tasks-list.md`

## 口径（需求 → 设计落点）

需求原文：见需求卡片 §需求原句（逐字，ADR 不复制第二份）。

卡片约束沿用各自编号（C1..Cn），本表只补「设计怎么落地」，不重新拆句：

| 卡片约束 # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | 「多个数据源同步任务都在运行时」 | 顶部运行区由单条 Alert 改为任务列表：每个运行中任务一行；0 个运行任务整块不渲染，1 个渲染单行；同一任务同一时刻最多一行 |
| C2 | 「在数据源同步顶部……显示出来」 | 行内复用 ADR 0037 / 0040 的服务端字段：请求进度、当前标的、已写入、`rows_per_second`、`elapsed_ms`、进度条；`progress_total == 0` 时显示「准备中」且不显示速度 |
| C3 | 「顶部多行显示」 | 按 `last_run_at` 倒序（同刻按任务 ID 倒序）；常显 5 行，超出显示「还有 N 个任务运行中」并可展开 / 收起；折叠只影响显示，不停止隐藏任务的轮询与完成提示 |
| C4 | 「多个……都在运行时」（运行期刷新） | 任务列表任一任务 running 时保持 2s 轮询；每个被追踪任务按 `job_id` 拉取最新 run（`GET /sync-jobs/{id}/runs?limit=1`）并 2s 轮询；复用现有端点，不新增聚合接口 |
| C5 | 「多个……都在运行时」（收尾一致性） | 每个 run 按其 `id` 去重提示一次终态并移除行；追踪集合保留到看到终态为止，避免任务列表先刷新导致漏提示；页面刷新按 `last_status=running` 恢复全部行 |
| C6 | 「多个数据源同步任务都在运行时」 | 后端零改动：同一任务仍由 DB 租约单飞（409），不同任务可并行；运行记录、调度、抓取、落库语义不变 |

决策结论只在「决策记录」写一次；本节与正文不再罗列「已确认决策」。

## Context

现状逐条核对（以代码为准，标注 `文件:行号`）。沿用卡片「现状影响面」的编号，逐条给结论；ADR 新发现的条目追加编号。

| # | 现状 | 位置 | 影响 | 与卡片的关系 |
|---|---|---|---|---|
| 1 | 前端用单个 `watchingJobId` 盯进度，刷新后只取任务列表里**第一个** running 任务 | `frontend/src/pages/datasource/DatasourcePage.tsx:86-88`、`DatasourcePage.tsx:140-150` | 第二个及之后的运行任务没有进度展示，先触发的任务会被后触发的覆盖 | 确认 C1 |
| 2 | 顶部只有一条 `Alert` + 单进度条 | `frontend/src/pages/datasource/DatasourcePage.tsx:377-403` | 页面模型无法并列表达多个运行任务 | 确认 C1 / C2 |
| 3 | 完成提示依赖单个 `notifiedRunRef` | `frontend/src/pages/datasource/DatasourcePage.tsx:88`、`DatasourcePage.tsx:155-170` | 并发结束时只会有最后一个被盯任务提示，其他完成结果静默丢失 | 确认 C5 |
| 4 | 任务列表在任一任务 running 时 2s 轮询；单个运行查询用 `runs?limit=1` 且终态即停 | `frontend/src/pages/datasource/DatasourcePage.tsx:96-103`、`DatasourcePage.tsx:143-149`；`frontend/src/api/datasource.ts:270-272` | 现有数据源足以支撑 N 行展示，无新接口需求 | 确认 C4 |
| 5 | 手动触发成功后只把新任务设为唯一被盯对象 | `frontend/src/pages/datasource/DatasourcePage.tsx:172-182` | 连点多个任务时，先前任务的进度从顶部消失 | 确认 C1 / C5 |
| 6 | `POST /sync-jobs/{id}/run` 用任务级租约单飞，抢占失败 409；后台线程执行 | `src/cndb/plugins/datasource/routers/sync_jobs.py:320-339`、`src/cndb/plugins/datasource/services/runner.py:297-317` | 不同任务并行运行是既有合法行为，前端单值模型与后端能力不匹配 | 确认 C6 |
| 7 | 现有用例断言单面板内的进度文案 | `frontend/src/pages/datasource/DatasourcePage.test.tsx:344-355` | 改为列表后需保留该断言并扩展并发场景 | 新增 |

**核心缺陷（需求要补的）**：前端的运行进度模型是单例（一个 `watchingJobId` + 一条运行查询 + 一个提示去重位），无法表达后端已支持的「多个不同任务并行运行」；除被盯任务外，其余任务只能在表格里看到一个「运行中」标签。

设计目标（不变量）：

- **I1 行集合完整**：凡处于 `last_status=running` 或刚由手动触发加入追踪的任务都有且只有一行；终态后该行必须移除；折叠不得改变行集合语义，只改变可见数量。
- **I2 展示口径一致**：行内进度、速度、耗时只读服务端 `SyncRunOut`（ADR 0040 I1）；前端不按浏览器时钟做差；`progress_total == 0` 显示「准备中」；同一任务的展示字段与现单行一致。
- **I3 轮询有界**：只轮询运行中 / 尚未看到终态的追踪任务，间隔 2s，终态即停；最多产生「运行任务数」条最新 run 查询，不轮询非运行任务的历史。
- **I4 提示恰好一次**：以 run `id` 为去重键，每个终态 run 只提示一次；并发完成互不覆盖；任务列表先移除任务不得造成漏提示。
- **I5 后端契约不变**：同一任务 409 单飞、不同任务并行、运行记录字段与调度 / 抓取 / 落库行为全部不变；零迁移、零新增端点。

## Decision

### 1. 数据模型

无新表 / 新列 / 枚举 / 迁移。前端只新增瞬态状态：追踪的任务 ID 集合、已完成 run ID 集合、运行列表展开标记；不持久化。

### 2. 判定算法（唯一入口）

运行列表的排序与截断收敛到 `frontend/src/pages/datasource/syncProgress.ts` 的纯函数，页面不得各写一套：

- `RUNNING_ROWS_LIMIT = 5`；
- `sortRunningJobs(jobs: SyncJob[]): SyncJob[]`：按 `last_run_at` 倒序，空值视为最早；同刻按 `id` 倒序；
- `visibleRunningJobs(jobs: SyncJob[], expanded: boolean): { visible: SyncJob[]; hidden: number }`：未展开时取前 5 条，`hidden = max(0, total - 5)`；展开时全量、`hidden = 0`。

追踪集合的唯一维护点在 `DatasourcePage`：

- 来源 = 任务列表中 `last_status === 'running'` 的 ID ∪ `POST /run` 响应立即加入的 ID；
- 当某任务最新 run 进入终态、完成提示后，从追踪集合移除该 ID；
- 追踪集合按 ID 去重；渲染时仅展示「最新 run 为 running」或「尚无最新 run 数据」的追踪任务，避免已终态但任务列表尚未刷新的行闪现。

### 3. API 变更清单

无新增 / 修改端点。复用：

| 端点 | 用途 |
|---|---|
| `GET /v1/workspaces/{wid}/datasource/sync-jobs` | 发现 `last_status=running` 的任务，任一运行中时 2s 轮询 |
| `GET /v1/workspaces/{wid}/datasource/sync-jobs/{id}/runs?limit=1` | 每个追踪任务取最新 run（进度 / 速度 / 耗时 / 终态），2s 轮询，终态即停 |
| `POST /v1/workspaces/{wid}/datasource/sync-jobs/{id}/run` | 手动触发；响应中的 `job` / `run` 用于立即加入追踪并预填最新 run 缓存 |

### 4. 边界与例外

1. 无运行中任务：顶部运行区完全不渲染，恢复表格原位置，不留空容器。
2. 同一任务重复触发：后端仍 409，前端沿用「任务可能正在执行」错误提示，不因多行展示而排队。
3. `progress_total == 0`：该行进度条显示「准备中」，不显示 `rows_per_second`；`elapsed_ms > 0` 仍显示已用时。
4. 某任务最新 run 查询失败：该行保留任务名与「进度读取失败」，任务列表轮询继续；下次轮询成功即恢复，不自动移除任务。
5. 完成先后竞态：任务列表把任务移出 running 时，追踪集合仍保留该 ID，直到其最新 run 查询返回终态；终态后按 run `id` 提示一次再移除。
6. 终态但任务列表滞后：该行不按陈旧 `last_status` 重新展示；若任务随后发起新 run（新 run `id`），按新 run 正常入列。
7. 超过 5 个运行任务：仅渲染前 5 行，其余以「还有 N 个任务运行中」计数；隐藏任务仍轮询、仍各自提示完成，展开后可见。
8. 服务重启遗留 `last_status=running`：沿用现有恢复口径（ADR 0037 D4），本次不引入额外陈旧状态清理。

### 5. 迁移

无。零迁移、零备份格式变化。

### 6. 前端

| 层 | 文件 | 改动 |
|---|---|---|
| 排序 / 截断工具 | `frontend/src/pages/datasource/syncProgress.ts` | 新增 `RUNNING_ROWS_LIMIT`、`sortRunningJobs`、`visibleRunningJobs`；格式化函数不变 |
| 页面 | `frontend/src/pages/datasource/DatasourcePage.tsx` | 移除单个 `watchingJobId` / `watchRunQuery` / `notifiedRunRef`；改为追踪 ID 集合 + 每任务最新 run 查询（`useQueries`）+ 每 run 一次提示；顶部把单条 Alert 改为纵向多行列表（保留容器 `data-testid="datasource-sync-progress"`，每行 `data-testid="datasource-sync-progress-{jobId}"`）；`POST /run` 成功后把返回的 `job` / `run` 写入缓存并立即加入追踪；加入展开 / 收起状态 |
| API 类型 | `frontend/src/api/datasource.ts` | 不改（`SyncRun` 已含 `elapsed_ms` / `rows_per_second`，ADR 0040 P0） |
| 样式 | `frontend/src/pages/datasource/DatasourcePage.tsx` 内联 `Space` / `Alert` 样式 | 行间距与现 Alert 的 12px 下边距一致；不新增全局 CSS |

### 7. 测试清单

**判定层（单测）**：`syncProgress.test.ts` 覆盖 `sortRunningJobs`（时间倒序、同刻 ID 倒序、空 `last_run_at`）、`visibleRunningJobs`（≤5 全显、>5 截断与 `hidden` 计数、展开全量）。

**前端组件**：`DatasourcePage.test.tsx` 覆盖：两个运行任务并列两行且各自进度 / 速度 / 用时正确；超过 5 个显示「还有 N 个」并可展开；无运行任务不渲染容器；一个任务先结束只移除该行、另一行继续且各提示一次；手动触发立即出现新行；页面刷新后按 `last_status=running` 恢复多行；既有单行进度文案断言保持通过。

**接口层**：无（端点与响应契约不变）。

**迁移 / 备份**：无（零迁移）；既有迁移与备份往返用例保持全绿。

**e2e（前端）**：不新增。真实并发同步依赖外部数据源，不进入 e2e；现有 `frontend/tests/e2e/critical/datasource.spec.ts` 不点「立即运行」，保持不改。

### 8. 分期

| 期 | 内容 | 风险 |
|---|---|---|
| **P0** | 排序 / 截断工具 + 追踪集合 + 每任务最新 run 查询 + 顶部多行渲染（含进度字段） | 低（只读展示，复用现有端点） |
| **P1** | 完成提示按 run 去重与自动移除、手动触发立即入列、超过 5 行展开 / 收起 | 中（完成竞态与任务列表刷新先后；用追踪集合兜底） |

## 决策记录（唯一决策台账）

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | 整体方案 | 顶部由单条 Alert 改为「运行中任务列表」，一行一任务 | 后端本就允许多任务并行（任务级租约），单值前端模型与能力不匹配；用户需要同时看到各任务进度 | 保持单条 Alert 轮流切换（后触发覆盖先触发，仍看不到全部）；只在表格行加进度（展示面积不足，违背「顶部」）；只发完成 toast（运行中不可见） | `DatasourcePage.tsx` |
| D2 | 数据来源与轮询 | 复用任务列表 `last_status` + 每个任务 `runs?limit=1`，2s 轮询，终态即停 | 任务数通常为个位数；现有端点已返回全部所需字段；零后端改动、零迁移 | 新增 `GET /sync-jobs/running` 聚合端点（当前规模下省不了多少请求，却增加接口与兼容成本）；SSE / WebSocket（ADR 0037 D5 已否决，运维复杂度不划算）；全量轮询所有任务历史（无谓请求） | `DatasourcePage.tsx`、`frontend/src/api/datasource.ts` |
| D3 | 排序与常显上限 | `last_run_at` 倒序 + 同刻 ID 倒序；常显 5 行，超出折叠为「还有 N 个」并可展开 | 最新触发的任务必须立即可见；限制顶部高度避免挤压任务表；折叠可逆，信息不丢失 | 全量铺开（运行任务多时挤占表格）；固定截断不可展开（隐藏任务无法查看）；按任务 ID / 名称排序（与触发先后无关，新任务可能排到折叠区） | `syncProgress.ts`、`DatasourcePage.tsx` |
| D4 | 完成提示与移除 | 以 run `id` 为去重键，每 run 提示一次；追踪集合保留到终态后移除 | 并发完成时单 `notifiedRunRef` 会互相覆盖；任务列表与 run 查询各自轮询存在先后差，提前移出集合会漏提示 | 沿用单个 `notifiedRunRef`（丢并发提示）；结束不提示只靠行消失（用户无法确认成败）；终态后立即按任务列表移除（可能漏掉尚未取到的终态） | `DatasourcePage.tsx` |
| D5 | 手动触发入列 | `POST /run` 成功后用响应的 `job` / `run` 预填最新 run 缓存并立即加入追踪 | 避免等下一次任务列表轮询（最多 2s）才出现行；响应已带完整 `SyncRunOut` | 只 `invalidate` 任务列表（新任务最多延迟 2s 出现，且原先任务已被覆盖的问题仍在） | `DatasourcePage.tsx` |
| D6 | 后端并发语义 | 不改：同一任务租约单飞 409，不同任务并行；不新增排队 / 工作区级全局锁 | 现有租约已保证同一任务不重入；多任务并行是合法运行形态，本次只补前端可见性 | 同任务排队执行（改变运行语义与调度行为）；工作区全局串行（人为压低吞吐，且与 ADR 0034 租约设计冲突） | `sync_jobs.py`、`runner.py`（不改） |
| D7 | 实现边界 | 页面内实现追踪与列表，排序 / 截断抽到 `syncProgress.ts` 纯函数；不新建组件 / 路由 | 改动集中在单页，复用现有测试骨架；纯函数让排序与上限可独立单测 | 新建独立 `RunningSyncTasks` 组件（页面局部状态仍需回传，props 与测试面扩大，收益有限）；新增独立运行监控页（超出需求范围） | `DatasourcePage.tsx`、`syncProgress.ts` |

门禁：`Proposed` → `Accepted` 前本表不得有「待定」；结论只在本书出现，别处只引用编号。

## Consequences

- **正向**：所有并行任务在顶部同时可见，各自带请求进度、写入速度与耗时；并发完成不再漏提示；后端零改动、零迁移。
- **负向**：前端从单查询变为「运行任务数」条查询（N+1），状态从单值变为追踪集合 + 终态去重集合；顶部最多常显 5 行，页面结构比单条 Alert 复杂。
- **风险与缓解**：任务列表与 run 查询刷新先后可能造成漏提示 —— 追踪集合保留到终态、按 run ID 去重兜底；运行任务很多时请求数上升 —— 仅运行任务轮询、终态即停，且常显上限控制渲染量；服务重启遗留 running —— 沿用既有恢复口径，不在本次扩大范围。

## 与既有 ADR 的关系

| 轴 | 载体 | 决定 | 由谁 |
|---|---|---|---|
| 运行进度字段与轮询 | `progress_total/done/entrant`、2s 轮询 | 语义与频率沿用，改为按任务分别轮询 | ADR 0037 D4/D5 |
| 速度 / 用时展示 | `SyncRunOut.rows_per_second` / `elapsed_ms` | 行内展示复用同一计算入口，前端不另算 | ADR 0040 D1/D2 |
| 任务单飞与并行 | 任务级 DB 租约、后台线程 | 同一任务 409、不同任务并行，均不变 | ADR 0034 D10、ADR 0037 D1 |
| 数据源同步框架 | Provider × SyncJob × Cursor × Normalizer | 本次只改前端运行视图，不触碰框架 | ADR 0006 |

## 落地状态（随实现更新）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 | 已落地 | `frontend/src/pages/datasource/syncProgress.ts`、`frontend/src/pages/datasource/DatasourcePage.tsx` | `frontend/src/pages/datasource/syncProgress.test.ts`、`frontend/src/pages/datasource/DatasourcePage.test.tsx` | `d65568a4` |
| P1 | 已落地 | `frontend/src/pages/datasource/DatasourcePage.tsx` | `frontend/src/pages/datasource/DatasourcePage.test.tsx` | `d65568a4` |

## 交接（会话结束更新）

- 当前阶段：P0 / P1 已实现并通过门禁
- 已完成：需求卡片 0041、ADR 0041、顶部多行运行列表（排序 / 5 行折叠 / 按任务轮询 / run 级完成提示 / 手动触发立即入列）、`syncProgress.ts` 排序与截断纯函数及单测
- 下一步：发布时回填提交 sha；如需继续扩展（如聚合端点），另开 ADR
- 已知坑：任务列表与每任务 run 查询是两路 2s 轮询，完成提示必须靠 run ID 去重与追踪集合兜底；任务列表滞后于已观察终态时不得回填（否则行反复进出）；run 查询 key 必须带 `last_run_at`，同一任务新 run 才能绕开旧终态缓存；全量 vitest 并发高时，等待 toast 的用例需放宽超时
- 最近一次全绿：`make flow`（5482 passed / 3 skipped）、`make frontend-coverage`（核心 97.78% / 100%，全局 82.83%）；`make e2e` 本机未跑通（`:8000` 被其它项目占用，且 Playwright Chromium 缺 `libatk-1.0.so.0` 系统库），e2e 用例未改动，待 CI 兜底
