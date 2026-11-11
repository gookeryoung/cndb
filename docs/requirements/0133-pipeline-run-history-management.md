# 需求卡片：质量检查运行历史支持删除 / 清空 / 滚动翻页

- 编号：0133（无独立 ADR，S1 方案并入本卡片）
- 来源 / 提出人：用户（会话 2026-11-11）
- 日期：2026-11-11
- 关联 ADR：无（不改数据模型、不改备份口径；沿用 ADR 0076 / 0080 / 0114 既有边界）

> 本卡片是**需求原文与约束编号的唯一副本**：ADR 只引用 C1..Cn，不复制原文；需求澄清后先改这里，再同步 ADR「口径」表。

## 需求原句（逐字）

> 质量检查运行历史需支持删除、清空以及翻页滚动查看。

## 已确认口径（2026-11-11 需求方确认）

| # | 问题 | 结论 |
|---|---|---|
| Q1 | 删除 / 清空权限 | 工作区 `owner` / `editor` 可操作；`viewer` 只读，不显示入口，后端 403 |
| Q2 | 「清空」范围 | 跟随当前过滤：选中规则 → 清空该规则全部历史；未选中 → 清空当前检查域（数据表 / 文档）全部历史 |
| Q3 | 进行中的运行 | 禁止删除：单条删除活跃运行返回 409；清空范围内存在活跃运行时整体拒绝并提示等待结束 |
| Q4 | 翻页交互 | 右栏固定高度内部滚动，滚动到底自动加载下一页，显示「已加载 N / 共 M 次」 |

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 「删除」 | 新增 `DELETE /{wid}/pipeline-runs/{run_id}`：`editor` 门槛；按工作区 + 运行 ID 定位（跨工作区 404）；活跃状态（`pending` / `running`）返回 409；删除运行前显式删除其 `pipeline_finding`；成功 204 | `src/cndb/plugins/pipeline/routers/workflows.py` | `tests/test_pipeline_api.py`：删除成功 / 发现物级联 / 活跃拒绝 / 越权与跨工作区 |
| C2 | 「清空」 | 新增 `DELETE /{wid}/pipeline-runs?workflow_id=&domain=`：`editor` 门槛；过滤口径与 `GET /pipeline-runs` 一致（`workflow_id` 与 `domain` 同时给定时取交集）；范围内存在活跃运行时 409 且不删任何行；成功返回 `{deleted: n}`，发现物经子查询一并删除 | `routers/workflows.py`、`schemas.py` | 接口测试：按规则 / 按域 / 全量清空；活跃拒绝；发现物无残留；非法 domain 400 |
| C3 | 隐含（前端 API） | `frontend/src/api/pipelines.ts` 增加 `removeRun(wid, runId)` 与 `clearRuns(wid, {workflow_id?, domain?})`，并补清空响应类型 | `frontend/src/api/pipelines.ts`、`frontend/src/api/index.ts` | 前端类型检查 + 单测 |
| C4 | 「删除」 | 运行行新增删除入口：`owner/editor` 可见；`Popconfirm` 二次确认；点击不触发行跳转；活跃运行按钮禁用并提示「运行中不可删除」 | `frontend/src/pages/pipelines/PipelinesPage.tsx` | 前端单测：删除确认、调用接口、viewer 隐藏、活跃禁用 |
| C5 | 「清空」 | 右栏标题区新增「清空」按钮：`owner/editor` 可见；文案随当前过滤说明范围（选中规则 / 当前域全部）；显示将删除的运行数；二次确认；成功后刷新历史与规则「最近运行」摘要 | `PipelinesPage.tsx` | 前端单测：确认调用、范围参数、viewer 隐藏、空历史禁用 |
| C6 | 「翻页滚动查看」 | 右栏运行历史改为固定高度内部滚动容器；分页大小 20，滚动到底（距底部 ≤ 64px）自动加载下一页；底部显示加载中 / 「已显示全部」；切换规则或域时重置滚动位置与已加载页；按 ID 去重防止轮询期间新运行插入造成重复行 | `PipelinesPage.tsx`、`index.css` | 前端单测：滚动触发下一页、总数展示、过滤切换重置、去重 |
| C7 | 隐含（权限与轮询） | 删除 / 清空后失效 `['pipelines', wid]` 查询；运行中记录仍按 1.5s 轮询；`viewer` 不出现任何写入口 | `PipelinesPage.tsx` | 前端单测：viewer 视角 |
| C8 | 隐含（测试与文档） | 同轮补后端接口测试、前端单测与 e2e 1 条；CHANGELOG 记条目；无迁移、无备份口径变化 | `tests/`、`frontend/`、`CHANGELOG.md` | `make check-fast` / `make flow` |

约束编号在 ADR 中原样引用；不重编号、不合并。

## 现状影响面（候选）

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | 工作区运行历史列表 | `src/cndb/plugins/pipeline/routers/workflows.py:499-520` | 新增删除 / 清空端点复用同一过滤口径 |
| 2 | 运行响应 schema | `src/cndb/plugins/pipeline/schemas.py:133-137` | 新增清空响应 `{deleted}` |
| 3 | 运行详情 helpers | `routers/workflows.py:444-449` | 单条删除复用工作区定位 |
| 4 | 前端运行历史 API | `frontend/src/api/pipelines.ts:235-240` | C3 新增封装 |
| 5 | 前端运行历史区 | `frontend/src/pages/pipelines/PipelinesPage.tsx:92-129`、`540-579` | C4-C7 行入口、清空、滚动加载 |
| 6 | 运行历史样式 | `frontend/src/index.css:6383-6460`、`6739-6773` | 滚动容器与底部状态行 |
| 7 | 既有前后端测试 | `tests/test_pipeline_api.py:512-652`、`frontend/src/pages/pipelines/PipelinesPage.test.tsx` | 回归 + 新增 |
| 8 | 既有 e2e | `frontend/tests/e2e/critical/pipelines.spec.ts` | 新增 1 条删除 / 清空用例 |

## 未决问题

- [x] ① 删除 / 清空权限：`owner/editor`（Q1）
- [x] ② 清空范围：跟随当前过滤（Q2）
- [x] ③ 进行中的运行：禁止删除（Q3）
- [x] ④ 翻页交互：滚动到底自动加载（Q4）
- [x] ⑤ 是否需要数据迁移 / 备份口径调整：不需要（只增删运行与发现物行，表结构不变）

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [x] 需求方确认卡片后进入实现（2026-11-11 确认）
