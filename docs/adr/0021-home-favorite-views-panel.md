# ADR 0021: 主页「我的视图」收藏面板与工作区 / 收藏视图自定义排序

Status: Implemented
Date: 2026-10-22
Related: `frontend/src/pages/workspace/WorkspaceList.tsx`, `frontend/src/pages/grid/gridViewBar.tsx`, `frontend/src/pages/grid/GridPage.tsx`, `frontend/src/index.css`, `src/cndb/plugins/accounts/models.py`, `src/cndb/plugins/accounts/routers/preferences.py`, `src/cndb/plugins/tables/services/core/view_access.py`, `src/cndb/plugins/tables/routers/views.py`, `src/cndb/plugins/workspaces/routers/workspaces.py`, `docs/adr/0003-view-visibility-permission-model.md`
需求卡片: `docs/requirements/0021-home-favorite-views-panel.md`（需求原文与约束编号的唯一副本）

## 口径（需求 → 设计落点）

需求原文：见需求卡片 §需求原句（逐字，ADR 不复制第二份）。

| 卡片约束 # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | 主页，我的工作区右侧增加我的视图面板 | `/w` 页改为双列：左列工作区（`minmax(0, 1fr)`），右列「我的视图」固定 340px；`<992px` 单列堆叠。面板独立卡片，含标题 / 计数 / 空态 |
| C2 | 展示个人收藏的视图列表 | 新增 per-user `favorite_views`（有序 view_id 列表），主页经 `GET /preferences/favorite-views` 聚合视图 + 表 + 工作区名，只展示手动收藏项 |
| C3 | （收藏入口） | 视图栏新增「收藏 / 取消收藏」：桌面端星标图标按钮，移动端「更多」菜单项；收藏走 `PUT /preferences/favorite-views` 全量替换 |
| C4 | 同样允许展开看详情 | 行内展开：视图类型、`工作区 › 数据表`、可见性档位 / 默认标记、筛选与排序条数；「打开视图」跳 `/w/{wid}/tables/{tid}?view={vid}` |
| C5 | 我的工作区和我的视图允许调整排序 | 两个面板均用 `@dnd-kit` 拖拽把手排序；工作区在「已收藏 / 其他工作区」组内拖拽，保存时按展示顺序扁平化；收藏视图整列拖拽。顺序写 `User.preferences`，跨设备保持 |
| C6 | （空态与失效清理） | 后端读取收藏时按可见性 + 表可读 + 表未软删剪枝并回写；前端空态文案指向视图栏星标 |
| C7 | （权限边界） | 收藏判定复用 `visible_view_filter` + `get_table_or_404(TableAction.READ)`；收藏不改 `DataView` 任何列，也不触发视图保存 |

决策结论只在「决策记录」写一次；本节与正文不再罗列「已确认决策」。

## Context

现状逐条核对（以代码为准，标注 `文件:行号`）。沿用卡片「现状影响面」的编号，逐条给结论；ADR 新发现的条目追加编号。

| # | 现状 | 位置 | 影响 | 与卡片的关系 |
|---|---|---|---|---|
| 1 | 主页是单列工具栏 + 工作区行列表；收藏分组为「已收藏 / 其他工作区」 | `frontend/src/pages/workspace/WorkspaceList.tsx:247-338` | 无右侧面板；需改双列并新增视图面板 | 确认 |
| 2 | 工作区排序固定为 `pinned → id`（后端 SQL 与前端 `filteredWorkspaces` 各一份） | `src/cndb/plugins/workspaces/routers/workspaces.py:97-102`、`frontend/src/pages/workspace/WorkspaceList.tsx:141-152` | 无 per-user 自定义顺序载体 | 确认 |
| 3 | 工作区收藏复用 `WorkspaceMember.pinned` | `src/cndb/plugins/workspaces/routers/workspaces.py:296-318` | 与「收藏视图」是两套对象，不共用存储 | 确认 |
| 4 | `DataView` 只有 `visibility`（table/shared/private）与 `order`，无「谁收藏了它」 | `src/cndb/plugins/tables/models.py:225-280` | 无法表达跨表个人收藏 | 新增 |
| 5 | 视图可见性唯一入口 `visible_view_filter` / `is_view_visible` | `src/cndb/plugins/tables/services/core/view_access.py:91-127` | 收藏读取必须复用，避免泄露他人私有视图 | 确认 |
| 6 | 视图列表按 `order, id` 返回；排序是表级公共属性 | `src/cndb/plugins/tables/routers/views.py:350-365` | 收藏面板顺序不能复用 `DataView.order`（会影响全表用户） | 新增 |
| 7 | `User.preferences` JSON 已承载 `active_views`，`_ensure_preferences` 负责补键 | `src/cndb/plugins/accounts/models.py:73-77`、`src/cndb/plugins/accounts/routers/preferences.py:62-69` | 可直接承载收藏与顺序，无需迁移 | 确认 |
| 8 | 视图栏桌面端右侧有新建 / 编辑 / 更多，移动端有「更多」菜单 | `frontend/src/pages/grid/gridViewBar.tsx:262-283`、`409-453` | 收藏入口可无侵入加入两处 | 确认 |
| 9 | 视图深链 `?view=` 已支持切换激活视图 | `frontend/src/pages/grid/GridPage.tsx:399-443` | 面板「打开视图」直接复用 | 排除（无需改动） |

**核心缺陷（需求要补的）**：现有模型只有「表内视图排序」与「工作区 pin」，没有「当前用户跨表收藏了哪些视图、以什么顺序展示」的载体。

设计目标（不变量）：

- **I1 可见性天花板**：收藏只对「视图可见 ∧ 表可读 ∧ 表未软删」成立；读取时失效 id 一律剪枝，不返回名称等元数据。
- **I2 用户隔离**：`workspace_order` / `favorite_views` 只存在当前用户 `preferences`，任意用户之间互不可见、互不覆盖。
- **I3 排序不越权**：自定义顺序只影响本人主页展示；不写 `DataView.order`、不影响其他成员，也不改变「已收藏工作区置顶」的分组优先级。
- **I4 收藏无副作用**：收藏 / 取消收藏不改视图配置、可见性、默认标记与表数据，可随时撤销。

## Decision

### 1. 数据模型

不加表、不加列，复用 `accounts_user.preferences`（JSON）：

```json
{
  "active_views": { "12": 34 },
  "workspace_order": [3, 1, 2],
  "favorite_views": [9, 4, 15]
}
```

- `favorite_views`：有序 view_id 列表，顺序即「我的视图」展示顺序；上限 **50**。
- `workspace_order`：有序 workspace_id 列表，顺序即「我的工作区」同组内展示顺序；只保存当前用户仍是成员的工作区。
- 两个键均为可选：旧数据缺失时由 `_ensure_preferences` 补空数组；`_default_preferences()` 同步补默认键。
- 独立收藏表被否决（见 D1）。

### 2. 判定算法（唯一入口）

新增 `src/cndb/plugins/accounts/services/preferences.py`，router 只做参数装配：

```python
MAX_FAVORITE_VIEWS = 50

def normalize_ids(raw: list[Any]) -> list[int]:
    """去重、保序、丢弃非正整数。"""

def set_favorite_views(db, user, view_ids: list[Any]) -> list[int]:
    """全量替换收藏；校验可见 + 表可读 + 表未软删，静默丢弃无效 id；超上限 400。"""

def load_favorite_view_summaries(db, user) -> list[dict]:
    """按收藏顺序返回摘要；读取时剪枝失效 id 并回写 preferences。"""

def set_workspace_order(db, user, workspace_ids: list[Any]) -> list[int]:
    """全量替换；仅保留当前用户为成员的工作区 id。"""
```

校验口径：

1. `visible_view_filter(user.id)` 判视图可见（table / 本人创建 / shared 名单，ADR 0003 唯一入口）。
2. `get_table_or_404(table_id, workspace_id, db, user, TableAction.READ)` 判表可读；`HTTPException` 视为无效并丢弃（不区分不存在 / 无权限，避免存在性提示）。
3. `DataTable.trashed_at IS NULL` 排除软删表。
4. 去重后 `> MAX_FAVORITE_VIEWS` → `400 最多收藏 50 个视图`；无效 id 静默丢弃而非报错（全量替换语义下保持幂等，且不泄露他人视图）。

### 3. API 变更清单

| 端点 | 变更 |
|---|---|
| `GET /api/v1/accounts/preferences` | 响应扩展 `workspace_order: int[]`、`favorite_view_ids: int[]`（未登录仍 401） |
| `GET /api/v1/accounts/preferences/favorite-views` | 新增：按收藏顺序返回摘要（`view_id` / `name` / `view_type` / `is_default` / `visibility` / `filter_count` / `sort_count` / `table_id` / `table_name` / `workspace_id` / `workspace_name` / `updated_at`），读取时剪枝失效 id |
| `PUT /api/v1/accounts/preferences/favorite-views` | 新增：请求 `{view_ids: int[]}` 全量替换；返回规范化后的 `{view_ids: int[]}` |
| `PUT /api/v1/accounts/preferences/workspace-order` | 新增：请求 `{workspace_ids: int[]}` 全量替换；返回规范化后的 `{workspace_ids: int[]}` |

工作区列表接口 `GET /api/v1/workspaces` 不改：返回仍按 `pinned → id`，前端用 `workspace_order` 覆盖同组内顺序（见 D3）。

### 4. 边界与例外

1. 取消收藏 / 视图删除后，id 可能短暂残留；下一次 `GET /preferences/favorite-views` 或 `GET /preferences` 读取时剪枝并 `flag_modified` 回写（与 `active_views` 清理口径一致）。
2. 多标签页并发为 last-write-wins（全量替换）；不做版本号 / 冲突合并。
3. 收藏上限 50：前端在收藏前检查数量并提示，后端仍兜底 400。
4. 工作区顺序里出现非成员 id（被移出工作区）→ 丢弃，不报错。
5. 拖拽跨分组：工作区拖拽只在「已收藏 / 其他工作区」组内生效；置顶分组优先级不变（D3）。
6. 收藏面板行点击只做展开 / 跳转，不触发视图自动保存（避免打开详情即写库）。

### 5. 迁移

无 DDL / Alembic 迁移：`preferences` 是 JSON 列，新增键由应用层补默认值；存量用户读取时自动补空数组。

### 6. 前端

| 层 | 文件 | 改动 |
|---|---|---|
| API 封装 | `frontend/src/api/preferences.ts`（新增） | `get` / `listFavoriteViews` / `setFavoriteViews` / `setWorkspaceOrder` |
| 类型 | `frontend/src/api/types/accounts.ts` | `FavoriteViewSummary`、`UserPreferences` |
| API 出口 | `frontend/src/api/index.ts` | 导出 `preferencesApi` |
| 收藏状态 Hook | `frontend/src/hooks/useFavoriteViews.ts`（新增） | 收藏 id 查询（`GET /preferences`）+ 收藏摘要查询 + 全量替换 mutation + 失效缓存 |
| 主页 | `frontend/src/pages/workspace/WorkspaceList.tsx` | 双列布局、视图面板（展开详情 / 空态 / 深链）、两个面板的 `@dnd-kit` 排序与乐观更新 |
| 视图栏 | `frontend/src/pages/grid/gridViewBar.tsx` | 桌面星标按钮 + 移动端「更多 → 收藏 / 取消收藏当前视图」 |
| 样式 | `frontend/src/index.css` | `cn-home-split` / `cn-myviews-*` 双列与面板样式；`<992px` 单列 |

排序展示算法（前端纯函数，便于单测）：

```ts
// 工作区：pinned 分组优先，组内按 workspace_order 排名，未登记 id 按原 id 兜底
sortWorkspaces(list, order) =>
  list.sort((a, b) =>
    Number(!!b.pinned) - Number(!!a.pinned) ||
    rank(order, a.id) - rank(order, b.id) ||
    Number(a.id) - Number(b.id))

// 保存：按当前展示顺序扁平化全部 id（已收藏在前，其他在后）
```

### 7. 测试清单

**判定层（单测）**：`normalize_ids` 去重保序 / 丢弃非法值；超上限拒绝；`set_workspace_order` 过滤非成员；剪枝算法保持收藏顺序。

**接口层**（扩展 `tests/test_user_preferences.py`）：

- 未登录访问 4 个端点 → 401。
- `PUT favorite-views` 后 `GET` 返回顺序与摘要字段；重复 id 去重。
- 收藏他人 private 视图 / 不存在视图 / 不可读表的视图 → 静默丢弃；读取后 preferences 回写。
- 视图删除、表软删、用户被移出工作区后 `GET favorite-views` 剪枝。
- 用户 A / B 收藏与顺序互不影响。
- `PUT workspace-order`：非成员 id 丢弃、重复去重、A/B 隔离。
- 权限副作用：收藏前后 `DataView` 的 `visibility / is_default / view_options` 不变。

**迁移 / 备份**：无迁移；工作区备份 / 恢复不携带 `User.preferences`（个人数据，天然不进入备份），补一条断言防止将来误导出。

**前端单测**：

- `WorkspaceList.test.tsx`：双列渲染（`my-views-panel`）；收藏视图行展开显示详情；空态指引；深链跳转 `/w/{wid}/tables/{tid}?view={vid}`；`sortWorkspaces` 纯函数（置顶分组 / 自定义顺序 / 未登记兜底）；拖拽排序后调用 `setWorkspaceOrder` / `setFavoriteViews`；窄屏堆叠（class 断言）。
- `gridViewBar.test.tsx`：桌面星标按钮 `aria-pressed` 随收藏态变化；移动端「更多」菜单项；点击调用收藏 API 并失效缓存。
- `useFavoriteViews.test.tsx`（可选）：查询 / mutation 缓存失效。

**e2e（前端）**：`frontend/tests/e2e/critical/favorite-views.spec.ts`——登录后在数据表视图栏收藏一个视图 → 打开 `/w` 看到「我的视图」该行 → 展开详情 → 点击「打开视图」落回同一视图；取消收藏后列表消失。

### 8. 分期

| 期 | 内容 | 风险 |
|---|---|---|
| **P0** | `preferences` 服务层 + 4 个端点 + 剪枝 / 上限 / 隔离的接口测试 | 低（无迁移） |
| **P1** | 视图栏收藏入口 + 主页双列「我的视图」面板 + 展开详情 / 深链 / 空态 + 前端单测 | 中（布局与现有行列表交互耦合） |
| **P2** | 两个面板拖拽排序 + 持久化 / 乐观更新 + 排序纯函数测试 + e2e | 中（拖拽与行点击 / 收藏按钮共存） |

## 决策记录（唯一决策台账）

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | 收藏与顺序的存储载体 | 复用 `User.preferences` JSON 的 `favorite_views` / `workspace_order` | 纯个人 UI 状态、无跨用户查询；JSON 列已承载 `active_views`，零迁移 | ① 新建 `favorite_views` 表：为个人展示状态引入迁移 / 备份 / 级联清理成本；② localStorage：换设备丢失、与「跨设备保持」冲突 | `accounts_user.preferences`、`services/preferences.py` |
| D2 | 「个人收藏的视图」数据来源 | 用户手动星标收藏任意可见视图（跨表 / 跨工作区） | 需求方确认；与「私有视图全集」「最近访问」相比语义明确、可控 | ① 自动收录 `visibility=private`：无法收藏表内 / 共享视图，且与「收藏」语义不符；② 最近访问：无手动控制，列表漂移 | `gridViewBar.tsx`、`preferences` 端点 |
| D3 | 排序方式 | 拖拽自定义顺序，per-user 持久化；工作区仍按 pin 分组优先，组内按自定义顺序 | 需求方确认；满足「调整排序」且不改变他人视图 / 工作区顺序 | ① 仅排序规则下拉：无法表达用户想要的固定顺序；② 复用 `DataView.order`：会改动全表成员的视图顺序（I3 越权） | `WorkspaceList.tsx`、`workspace_order` 键 |
| D4 | 面板布局 | 桌面端右侧固定宽 340px 分栏，`<992px` 上下堆叠 | 需求方确认；同屏对照工作区与收藏视图，窄屏不横向溢出 | ① 可折叠右栏：多一层折叠状态且收起后信息不可见；② Tab 切换：无法同屏对照 | `WorkspaceList.tsx`、`index.css` |
| D5 | 写入语义 | `PUT` 全量替换列表；无效 id 静默丢弃；超 50 返回 400；多端 last-write-wins | 与拖拽排序天然契合（一次提交完整顺序）；剪枝不泄露他人视图存在性 | ① 逐条 POST/DELETE：排序仍需另一端点，且多端并发更难合并；② 无效 id 返回 404：会形成存在性提示（ADR 0003 I6） | `services/preferences.py` |
| D6 | 收藏摘要的数据来源 | 服务端一次返回视图 + 表 + 工作区名称与筛选 / 排序条数 | 避免主页按收藏行逐个请求表 / 视图（N+1） | 前端逐行 `viewApi.get`：≤50 行时请求数不可控，首屏抖动 | `GET /preferences/favorite-views` |
| D7 | 收藏动作的权限 | 只校验「可见 ∧ 表可读」；不改视图、不触发保存 | I4；收藏是个人 UI 状态，不构成视图配置变更 | 复用 `VIEW_EDIT`：会把收藏误当编辑权限，个人视图与非管理用户无法收藏 | `services/preferences.py` |

门禁：`Proposed` → `Accepted` 前本表不得有「待定」。

## Consequences

- **正向**：主页一屏同时看到工作区与常用视图；收藏与顺序跨设备一致；零 DDL 迁移，回滚只需删前端入口（残留键无害）。
- **负向**：`preferences` JSON 增加两个有序数组（最多 50 个收藏）；主页新增一次偏好查询与一次摘要查询；工作区排序逻辑仍保留前后端两处口径（后端 `pinned → id` 兜底，前端叠加自定义顺序）。
- **风险与缓解**：拖拽与行点击 / 收藏按钮冲突 → 仅拖拽把手可拖（`PointerSensor` 距离阈值）；收藏视图列表失效引用 → 读取时剪枝 + React Query 失效缓存。

## 与既有 ADR 的关系（可选）

| 轴 | 载体 | 决定 | 由谁 |
|---|---|---|---|
| 视图可见性 | `visible_view_filter` | 收藏读取复用同一判定，不新增可见性档位 | ADR 0003 |
| 工作区收藏 | `WorkspaceMember.pinned` | 继续作为「已收藏工作区」分组依据，不被自定义顺序替代 | ADR 0021 D3 |

## 落地状态（随实现更新）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 | 已落地 | `src/cndb/plugins/accounts/services/preferences.py`（判定层：normalize_ids / visible_favorite_views / set_favorite_views / set_workspace_order）、`src/cndb/plugins/accounts/routers/preferences.py`（4 个端点）、`src/cndb/plugins/accounts/models.py`（默认偏好补两键） | `tests/test_user_preferences.py`（判定 / 剪枝 / 上限 / 端点权限） | 95da1938 |
| P1 | 已落地 | `frontend/src/api/preferences.ts`、`frontend/src/hooks/useFavoriteViews.ts`、`frontend/src/pages/workspace/MyViewsPanel.tsx`、`frontend/src/pages/workspace/WorkspaceList.tsx`（双列 + 面板挂载）、`frontend/src/pages/grid/gridViewBar.tsx`（桌面星标 / 移动菜单）、`frontend/src/index.css`（cn-home-split / cn-myviews-* 样式） | `frontend/src/pages/workspace/WorkspaceList.test.tsx`（面板渲染 / 展开详情 / 深链 / 取消收藏 / 空态）、`frontend/src/pages/grid/gridViewBar.test.tsx`（收藏入口 / 上限）、`frontend/src/test/msw.ts`（偏好 handler） | 95da1938 |
| P2 | 已落地 | `frontend/src/utils/homeOrder.ts`（buildRankMap / sortWorkspaces / flattenWorkspaceOrder）、`frontend/src/pages/workspace/WorkspaceList.tsx`（工作区拖拽 + 搜索时禁用）、`frontend/src/pages/workspace/MyViewsPanel.tsx`（收藏视图拖拽）、`frontend/src/hooks/useFavoriteViews.ts`（乐观更新 / 回滚 / 上限） | `frontend/src/utils/homeOrder.test.ts`（8 例）、`frontend/src/pages/workspace/WorkspaceList.test.tsx`（自定义顺序 / 搜索禁用拖拽）、`frontend/src/pages/grid/gridViewBar.test.tsx`、`frontend/tests/e2e/critical/favorite-views.spec.ts` | 95da1938 |

> 状态只取「未开始 / 进行中 / 已落地」。标「已落地」的期必须有代码落点与测试文件；全期落地后由人确认 `Status` 是否改 `Accepted` / `Implemented`。

## 交接（会话结束更新）

- 当前阶段：P0-P2 已落地（后端判定层 + 4 端点、主页双列面板、两列拖拽排序）
- 已完成：前端 `170` 个测试文件 / `2079` 例全绿（含 `tokens.test.ts` 断点口径扩到 `tablet - 0.02`）；后端偏好测试全绿；`pnpm typecheck` / `eslint` 无报错；e2e `favorite-views.spec.ts` 已修正断言（Segmented 选中项 `innerText` 会把视图名与「默认」标签拆成多行，只取第一行名称匹配面板行），本地实跑通过，待 CI shard 复跑确认
- 下一步：观察主页新增的偏好 + 摘要两次查询对首屏耗时的影响，必要时合并为单个聚合端点
- 已知坑：① 拖拽监听只挂把手，否则行点击 / 星标误触；② 搜索过滤期间禁用拖拽，避免保存过滤后的子集；③ 收藏读取必须复用 `visible_view_filter` + `get_table_or_404`，不能直接按 id 查 `DataView`；④ msw `onUnhandledRequest: 'error'`——任何渲染 `GridViewBar` / `WorkspaceList` 的测试都必须有偏好 handler 或 api mock；⑤ e2e 取当前视图名不能直接用 `.ant-segmented-item-selected` 的 `innerText` 整串——它是 inline-flex，名称与「默认 / 我的」标签会变成多行，而面板行里名称和标签分属不同元素
- 最近一次全绿：2026-10-22（前端全量 vitest + 后端 `make flow` + e2e `favorite-views` / `kline-view` 单跑）
