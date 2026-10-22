# 需求卡片：主页工作区右侧「我的视图」收藏面板与双列排序

- 编号：0021（与 ADR `docs/adr/0021-home-favorite-views-panel.md` 同号）
- 来源 / 提出人：产品需求（会话提出）
- 日期：2026-10-22
- 关联 ADR：`docs/adr/0021-home-favorite-views-panel.md`

> 本卡片是**需求原文与约束编号的唯一副本**：ADR 只引用 C1..Cn，不复制原文；需求澄清后先改这里，再同步 ADR「口径」表。

## 需求原句（逐字）

> 主页，我的工作区右侧增加我的视图面板，用于展示个人收藏的视图列表，同样允许展开看详情。我的工作区和我的视图允许调整排序。

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 主页，我的工作区右侧增加我的视图面板 | `/w` 主页保持「我的工作区」列，桌面端（≥992px）右侧新增固定宽「我的视图」面板；<992px 上下堆叠，不横向溢出 | `frontend/src/pages/workspace/WorkspaceList.tsx`、`frontend/src/index.css` | 组件测试 + 视口截图 |
| C2 | 展示个人收藏的视图列表 | 「我的视图」只展示当前用户**手动收藏**的视图，跨工作区 / 跨表聚合；不自动收录私有视图全集、不按最近访问生成 | `src/cndb/plugins/accounts/`、`frontend/src/api/preferences.ts` | 接口层用例 |
| C3 | （收藏入口） | 数据表视图栏提供「收藏 / 取消收藏当前视图」入口（桌面图标按钮 + 移动端「更多」菜单项），收藏状态按当前用户持久化 | `frontend/src/pages/grid/gridViewBar.tsx`、`src/cndb/plugins/accounts/routers/preferences.py` | 前端单测 + 接口层用例 |
| C4 | 同样允许展开看详情 | 「我的视图」每行可展开，详情含视图类型、所属工作区 › 数据表、可见性档位 / 是否默认、筛选与排序条件数量，并提供「打开视图」深链 `/w/{wid}/tables/{tid}?view={vid}` | `frontend/src/pages/workspace/WorkspaceList.tsx`、`frontend/src/api/preferences.ts` | 组件测试 |
| C5 | 我的工作区和我的视图允许调整排序 | 两个面板均支持拖拽调整顺序：工作区在「已收藏 / 其他工作区」分组内拖拽，收藏视图整列拖拽；顺序按当前用户持久化，刷新 / 换设备保持 | `frontend/src/pages/workspace/WorkspaceList.tsx`、`src/cndb/plugins/accounts/services/preferences.py` | 前端单测（排序纯函数 + API 调用）+ 接口层用例 |
| C6 | （空态与失效清理） | 无收藏时展示空态并指引「在数据表视图栏点 ☆ 收藏」；视图被删除、转为不可见、所在表软删或用户失去表读权限后，面板不再展示且后端读取时剪枝失效 id | `src/cndb/plugins/accounts/services/preferences.py`、`frontend/src/pages/workspace/WorkspaceList.tsx` | 接口层用例（删除 / 失权后读取）+ 组件测试 |
| C7 | （权限边界） | 收藏只允许当前用户**可见且可读**的视图；收藏动作不改变视图配置、可见性、默认视图或表数据 | `src/cndb/plugins/tables/services/core/view_access.py` 复用、`src/cndb/plugins/accounts/services/preferences.py` | 接口层用例（私有视图 / 他人私有 / 不可读表） |

约束编号在 ADR 中原样引用；不重编号、不合并。

## 现状影响面（候选，待 ADR 核实）

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | 主页工作区列表单列布局 | `frontend/src/pages/workspace/WorkspaceList.tsx` | 需要改为左右双列 |
| 2 | 工作区收藏（pin）与排序 | `src/cndb/plugins/workspaces/routers/workspaces.py` | 现有排序为 pinned → id，需要叠加 per-user 自定义顺序 |
| 3 | 视图可见性判定 | `src/cndb/plugins/tables/services/core/view_access.py` | 收藏读取必须复用同一可见性口径 |
| 4 | 用户偏好 JSON | `src/cndb/plugins/accounts/models.py` | 现只有 `active_views`，可承载收藏与顺序 |
| 5 | 视图切换栏 | `frontend/src/pages/grid/gridViewBar.tsx` | 需要新增收藏入口 |

> 编号与 ADR「Context」表对齐：ADR 逐条给「确认 / 排除 / 新增」并补齐 `file:line`。本阶段只粗查，精查归 ADR。

## 未决问题

- [x] 「个人收藏的视图」= 新增手动星标收藏（已确认，非私有视图全集 / 非最近访问）
- [x] 排序方式 = 拖拽自定义顺序并持久化（已确认，非仅排序规则切换）
- [x] 布局 = 桌面端右侧固定宽分栏、窄屏上下堆叠（已确认，非可折叠侧栏 / Tab）

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [x] 未决问题全部有结论，需求方确认
