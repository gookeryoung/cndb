# 需求卡片：数据源同步顶部展示多个运行中任务

- 编号：0041（与 ADR `docs/adr/0041-*.md` 同号，卡片存 `docs/requirements/0041-<topic>.md`）
- 来源 / 提出人：用户
- 日期：2026-10-26
- 关联 ADR：`docs/adr/0041-datasource-running-tasks-list.md`

> 本卡片是**需求原文与约束编号的唯一副本**：ADR 只引用 C1..Cn，不复制原文；需求澄清后先改这里，再同步 ADR「口径」表。

## 需求原句（逐字）

> 多个数据源同步任务都在运行时，是否应当在数据源同步顶部多行显示出来。

需求方确认（2026-10-26）：采用多行运行任务列表方案，按本卡片 C1..C6 实施。

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 「多个数据源同步任务都在运行时」 | 数据源同步页顶部在存在 ≥2 个 `last_status=running` 任务时，以**一行一个任务**的多行列表展示；仅 1 个运行时仍为该单行；无运行中任务时整块隐藏；同一任务不重复占行 | `frontend/src/pages/datasource/DatasourcePage.tsx` | 前端组件用例：0 / 1 / 2 / N 个运行任务 |
| C2 | 「在数据源同步顶部……显示出来」 | 每行展示：任务名、`progress_done/progress_total` 请求数、当前标的、已写入行数、`rows_per_second`、`elapsed_ms`、进度条；`progress_total == 0` 显示「准备中」且不显示速度；数值全部取服务端 `SyncRunOut`，前端不按浏览器时钟自行计算 | `DatasourcePage.tsx`、`frontend/src/pages/datasource/syncProgress.ts` | 前端组件用例逐字段断言 |
| C3 | 「顶部多行显示」 | 行序按本次运行开始时间倒序（最新开始在前），同一时间按任务 ID 倒序；常显最多 5 行，超过时显示「还有 N 个任务运行中」并可展开 / 收起；折叠只影响渲染，不停止未显示任务的轮询与完成提示 | `DatasourcePage.tsx`、`syncProgress.ts` | `syncProgress.test.ts` 排序 / 截断 + 页面展开用例 |
| C4 | 「多个……都在运行时」（运行期数据刷新） | 任务列表在任一任务 running 时保持 2s 轮询；对每个运行中任务按其 `job_id` 拉取最新一条运行记录并 2s 轮询，运行结束即停；复用现有 `GET /sync-jobs/{id}/runs?limit=1`，不新增后端端点 | `DatasourcePage.tsx`、`frontend/src/api/datasource.ts`、`src/cndb/plugins/datasource/routers/sync_jobs.py` | 前端用例断言每个任务各自取数；无接口变更 |
| C5 | 「多个……都在运行时」（收尾一致性） | 每个运行的最终状态（success / partial / failed）各自提示一次且仅一次，并自动移除该行；提示后刷新任务列表；页面刷新后仍能按 `last_status=running` 恢复全部行与轮询；任务列表先移除任务时不得丢失其完成提示（继续追踪到最新 run 落终态） | `DatasourcePage.tsx` | 前端用例：并发结束只提示各自一次、行自动移除、刷新恢复 |
| C6 | 「多个数据源同步任务都在运行时」 | 不改变「同一任务单飞」语义：同一任务重复触发仍由 DB 租约返回 409；不同任务可并行运行；不改运行记录、调度、抓取或落库行为 | `src/cndb/plugins/datasource/routers/sync_jobs.py`、`src/cndb/plugins/datasource/services/runner.py` | 既有后端用例保持全绿；前端 409 提示不变 |

约束编号在 ADR 中原样引用；不重编号、不合并。

## 现状影响面（候选，待 ADR 核实）

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | 单一「正在盯」任务状态 | `frontend/src/pages/datasource/DatasourcePage.tsx:86-88`、`140-150` | 只保留一个 `watchingJobId`，刷新后只取第一个 running 任务 |
| 2 | 顶部运行进度展示 | `frontend/src/pages/datasource/DatasourcePage.tsx:377-403` | 单条 Alert + 单进度条，无法并列多任务 |
| 3 | 完成提示去重 | `frontend/src/pages/datasource/DatasourcePage.tsx:88`、`155-170` | 单个 `notifiedRunRef`，并发结束会互相覆盖 |
| 4 | 任务列表与运行记录轮询 | `frontend/src/pages/datasource/DatasourcePage.tsx:96-103`、`143-149`；`frontend/src/api/datasource.ts:270-272` | 已有 2s 轮询能力，按 job 粒度取最新 run |
| 5 | 并行运行的后端语义 | `src/cndb/plugins/datasource/routers/sync_jobs.py:320-339`、`services/runner.py:297-317` | 同一任务租约单飞（409），不同任务可在后台并行 |
| 6 | 现有运行中展示用例 | `frontend/src/pages/datasource/DatasourcePage.test.tsx:344-355` | 断言单面板文案，需要兼容并扩展为多行 |

> 编号与 ADR「Context」表对齐：ADR 逐条给「确认 / 排除 / 新增」并补齐 `file:line`。本阶段只粗查，精查归 ADR。

## 未决问题

- 已确认（2026-10-26）：顶部采用多行运行任务列表；排序为最新开始在前；常显上限 5 行并支持展开；复用现有按任务查询运行记录，不新增聚合端点。
- 已确认（2026-10-26）：同一任务单飞（409）与后端运行语义不变。

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [x] 未决问题全部有结论，需求方确认（2026-10-26）
