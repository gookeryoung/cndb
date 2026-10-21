# ADR 0012: 工作区顶栏统一搜索（文档 + 数据表，默认按激活视图收敛）

Status: Implemented（2026-10-21）
Date: 2026-10-21
Related: `src/cndb/plugins/workspaces/routers/search.py`、`src/cndb/plugins/workspaces/services/search.py`、`frontend/src/components/GlobalSearch.tsx`、`frontend/src/api/search.ts`、`frontend/src/layouts/MainLayout.tsx`、`frontend/src/pages/documents/DocumentsPage.tsx`、`frontend/src/pages/documents/DocumentEditorPage.tsx`、`tests/test_workspace_search.py`、`frontend/src/components/GlobalSearch.test.tsx`

## 口径（需求 → 设计落点）

| 需求片段 | 本设计的落地 |
|---|---|
| 文档「查找」按钮移除 | 文档总览页的「全文搜索」按钮与 `SearchDrawer` 删除；文档编辑器工具栏的「查找」按钮删除，查找替换仅保留 `Ctrl+F` / 右键菜单入口（`FindReplaceBar` 与快捷键逻辑不变） |
| 参考 GitHub，顶部增加搜索区域 | 顶栏 `MainLayout` 新增 `GlobalSearch`：左侧范围选择器 + 输入框 + `Ctrl K` 提示，聚焦后向下展开分组结果面板，交互对齐 GitHub header 搜索框 |
| 默认搜索工作区范围的内容 | 默认 `scope=all`：一次请求同时返回文档（FTS5）与数据表（表名 / 表内行）两路结果，与当前所在页面无关 |
| 区分数据表搜索与文档搜索的 UI | 范围选择器三档 `工作区 / 数据表 / 文档`（GitHub 的 scope 限定词等价物），结果面板按「数据表 / 表内数据 / 文档」分组并带命中数徽标 |
| 数据表默认只搜索当前激活视图的内容 | 表上下文（`/w/:wid/tables/:tid` 且 URL 带 `?view=`）时前端下发 `table_id` + `view_id`，后端把该视图的 `filters` 按原 AND/OR 语义作为前置条件，再与关键词条件 AND 组合；面板底部回显「表名 · 视图「名称」」 |

## Context

现状逐条核对（以改动前的代码为准）：

| # | 现状 | 位置 | 影响 |
|---|---|---|---|
| 1 | 文档全文检索仅存在于文档插件，且只覆盖文档 | `src/cndb/plugins/documents/routers/documents.py` | 数据表侧无任何关键词检索能力 |
| 2 | 文档总览页有独立「全文搜索」按钮 + 抽屉 | `frontend/src/pages/documents/DocumentsPage.tsx` | 入口绑定在「文档」页，跨模块搜不到；与顶栏搜索区重复 |
| 3 | 编辑器工具栏有「查找」按钮 | `frontend/src/pages/documents/DocumentEditorPage.tsx` | 与 `Ctrl+F` 同一动作，重复控件占用工具栏宽度 |
| 4 | 行检索能力已具备：`list_rows` 支持 `$query` 全局关键词（对全部文本列 OR contains）、嵌套 `__or__` / `__and__` 分组、行级权限与字段隐藏 | `src/cndb/plugins/tables/services/core/records.py`、`query.py` | 无需新建检索索引，直接复用即可保证与网格同口径 |
| 5 | 表可见性判定有批量预取入口 `preload_table_access` | `src/cndb/plugins/tables/services/core/access.py` | 跨表检索可用少量查询封顶完成权限裁剪 |
| 6 | 视图 `filters` / `filter_type` 落库于 `tables_dataview`，可见性判定为 `is_view_visible` + `grants_for_user` | `src/cndb/plugins/tables/models.py`、`core/view_access.py` | 「按激活视图收敛」可直接读视图条件，无需新增字段 |

设计不变量：

- **I1 权限单一**：文档侧沿用 `search_documents` 的可见性口径（非管理员搜不到他人未发布内容）；数据表侧沿用 `preload_table_access` + `list_rows(row_scope)`，不新增旁路。
- **I2 视图语义保留**：视图 `filter_type=OR` 时组内按 OR，外层与关键词恒 AND；视图不可见 / 不属于该表 / 参数失效时**退化为整表检索**，检索不因坏参数 500。
- **I3 存量零迁移**：不新增表 / 列 / 索引，不改文档 FTS schema。
- **I4 成本可控**：无视图上下文时最多扫描 `MAX_TABLES_SCAN=8` 张表、每表 3 行、总行命中 ≤ 20；单表异常不影响整体结果。
- **I5 入口唯一**：模块内的「搜索 / 查找」入口收敛到顶栏一处 + 编辑器快捷键。

## Decision

### 1. 后端：工作区级检索端点

`GET /api/v1/workspaces/{wid}/search?q=&scope=all|documents|tables&table_id=&view_id=&limit=`

- 挂载：workspaces 插件新增 `routers/search.py`（插件 `route_prefix=""`，故路径与 `/tables`、`/documents` 同级）。
- 成员门槛：`check_workspace_permission(..., VIEWER)`，非成员 403。
- 响应：`{query, documents[], tables[], rows[], view}`；`view` 回显生效的检索范围（`null` 表示不在表上下文）。

### 2. 后端：数据表侧「按激活视图收敛」

`services/search.py` 内：

1. `_readable_tables` 取工作区可读表；带 `table_id` 时目标收敛到该表，否则限量扫描。
2. `_view_scope_filters` 读视图 `filters` / `filter_type`，视图不可见或不属于该表 → 空条件（整表）。
3. `_combine_filters` 生成 `[{__or__|__and__: 视图条件}, {field_name: "$query", value: 关键词}]`，外层 `filter_logic="AND"`。
4. `list_rows(... limit=3, db, user)` —— 行级权限、字段隐藏、软删除排除与网格完全同口径。
5. 行标题取字段顺序上首个非空文本值；命中片段优先取含关键词的字段值。

### 3. 前端：顶栏搜索区

- `components/GlobalSearch.tsx`：`Dropdown` 范围选择器 + `Input`（borderless，外层自绘盒子）+ 自绘分组面板（表名命中 / 表内数据 / 文档），`↑↓` 选择、`Enter` 打开、`Esc` 收起、`Ctrl/⌘+K` 与 `/` 聚焦。
- 范围偏好存 `localStorage('cndb:search-scope')`，默认 `all`。
- `MainLayout` 在桌面端把搜索框放在工作区切换器右侧；移动端收为图标 + 顶部抽屉，避免挤压 44px 顶栏。
- 点击命中：文档 → 编辑器；表 / 行 → 该表网格页。

### 4. 移除旧入口

- `DocumentsPage`：删除「全文搜索」按钮、`searchOpen` 状态与 `SearchDrawer`（文件删除）；「本页标题过滤」保留（那是列表内过滤，不是检索）。
- `DocumentEditorPage`：删除工具栏「查找」按钮，`openFind` 仍由 `Ctrl+F` 与右键菜单「查找替换」触发。

## 落地状态（随实现更新）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 | 已落地 | `src/cndb/plugins/workspaces/routers/search.py`、`src/cndb/plugins/workspaces/services/search.py`、`src/cndb/plugins/workspaces/plugin.py` | `tests/test_workspace_search.py` | 7e1224d1 |
| P1 | 已落地 | `frontend/src/components/GlobalSearch.tsx`、`frontend/src/api/search.ts`、`frontend/src/layouts/MainLayout.tsx`、`frontend/src/index.css` | `frontend/src/components/GlobalSearch.test.tsx`、`frontend/src/test/msw.ts` | 7e1224d1 |
| P2 | 已落地 | `frontend/src/pages/documents/DocumentsPage.tsx`、`frontend/src/pages/documents/DocumentEditorPage.tsx` | `frontend/src/pages/documents/DocumentEditorPage.test.tsx` | 7e1224d1 |

> 状态只取「未开始 / 进行中 / 已落地」。标「已落地」的期必须有代码落点与测试文件。

## 交接（会话结束更新）

- 当前阶段：P0-P2 全部落地（含 CHANGELOG 回填）
- 已完成：统一检索端点（文档 FTS + 数据表表名/行，视图范围收敛）、顶栏 GitHub 风格搜索区（范围三档 + 分组面板 + 快捷键）、移动端抽屉、移除文档页与编辑器两处旧入口
- 下一步：无（本 ADR 范围内交付完毕）；若要做「跨工作区全局搜索」或「检索结果独立页」，另立 ADR（当前面板只取前 10~20 条，不做分页）
- 已知坑：
  - 数据表行检索是**逐表 LIKE**（无全文索引），表多且行多时是线性成本；已用 `MAX_TABLES_SCAN=8` / `ROWS_PER_TABLE=3` 封顶，超大工作区若要全量覆盖需引入 FTS 索引
  - 视图收敛只在**表上下文且 URL 带 `?view=`** 时生效；不带 view 参数视为整表检索（面板底部显示「表名 · 整表」）
  - 行命中只跳到表网格页，**不定位到具体行**（网格暂无 `?row=` 深链参数）
  - `documentsApi.search` 仍保留（后端端点未删除），当前无前端调用方
- 最近一次全绿：`make check-fast` + 定向测试（后端 `tests/test_workspace_search.py` 11 例、前端 GlobalSearch 6 例与文档页 201 例）2026-10-21
