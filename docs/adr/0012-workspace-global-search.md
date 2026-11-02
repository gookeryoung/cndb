# ADR 0012: 工作区顶栏统一搜索（文档 + 数据表，默认按激活视图收敛）

Status: Implemented（2026-10-21）
Date: 2026-10-21
Related: `src/cndb/plugins/workspaces/routers/search.py`、`src/cndb/plugins/workspaces/services/search.py`、`frontend/src/components/GlobalSearch.tsx`、`frontend/src/api/search.ts`、`frontend/src/layouts/MainLayout.tsx`、`frontend/src/pages/documents/DocumentsPage.tsx`、`frontend/src/pages/documents/DocumentEditorPage.tsx`、`tests/test_workspace_search.py`、`frontend/src/components/GlobalSearch.test.tsx`
> 本 ADR 已合并原 ADR 0015（工作区搜索缓存与全表覆盖增强），口径 / 决策 / 落地状态见文末「续作」小节（编号 0015 不复用）。

## 口径（需求 → 设计落点）

| 需求片段 | 本设计的落地 |
|---|---|
| 文档「查找」按钮移除 | 文档总览页的「全文搜索」按钮与 `SearchDrawer` 删除；文档编辑器工具栏的「查找」按钮删除，查找替换仅保留 `Ctrl+F` / 右键菜单入口（`FindReplaceBar` 与快捷键逻辑不变） |
| 参考 GitHub，顶部增加搜索区域 | 顶栏 `MainLayout` 新增 `GlobalSearch`：左侧范围选择器 + 输入框 + `Ctrl K` 提示，聚焦后向下展开分组结果面板，交互对齐 GitHub header 搜索框 |
| 默认搜索工作区范围的内容 | 默认 `scope=all`：一次请求同时返回文档（FTS5）与数据表（表名 / 表内行）两路结果，与当前所在页面无关 |
| 区分数据表搜索与文档搜索的 UI | 范围选择器三档 `工作区 / 数据表 / 文档`（GitHub 的 scope 限定词等价物），结果面板按「数据表 / 表内数据 / 文档」分组并带命中数徽标 |
| 数据表范围只搜索当前激活视图的内容 | 「数据表」范围（`scope=tables`）下表上下文（`/w/:wid/tables/:tid` 且 URL 带 `?view=`）时前端下发 `table_id` + `view_id`，后端把该视图的 `filters` 按原 AND/OR 语义作为前置条件，再与关键词条件 AND 组合；面板底部回显「表名 · 视图「名称」」。「工作区」范围（`scope=all`）不收敛，覆盖全部可读表（ADR 0015） |

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
- **I4 成本可控**：每表 3 行、总行命中 ≤ 20 的展示预算不变；工作区范围覆盖全部可读表，结果缓存与失效策略见 ADR 0015。
- **I5 入口唯一**：模块内的「搜索 / 查找」入口收敛到顶栏一处 + 编辑器快捷键。

## Decision

### 1. 后端：工作区级检索端点

`GET /api/v1/workspaces/{wid}/search?q=&scope=all|documents|tables&table_id=&view_id=&limit=`

- 挂载：workspaces 插件新增 `routers/search.py`（插件 `route_prefix=""`，故路径与 `/tables`、`/documents` 同级）。
- 成员门槛：`check_workspace_permission(..., VIEWER)`，非成员 403。
- 响应：`{query, documents[], tables[], rows[], view}`；`view` 回显生效的检索范围（`null` 表示不在表上下文）。

### 2. 后端：数据表侧「按激活视图收敛」

`services/search.py` 内：

1. `_readable_tables` 取工作区可读表；`scope=tables` 带 `table_id` 时收敛到该表，工作区范围覆盖全部可读表（ADR 0015）。
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
- 已完成：统一检索端点（文档 FTS + 数据表表名/行；数据表范围按视图收敛、工作区范围全表覆盖与结果缓存，见 ADR 0015）、顶栏 GitHub 风格搜索区（范围三档 + 分组面板 + 快捷键）、移动端抽屉、移除文档页与编辑器两处旧入口
- 下一步：无（本 ADR 范围内交付完毕）；若要做「跨工作区全局搜索」或「检索结果独立页」，另立 ADR（当前面板只取前 10~20 条，不做分页）
- 已知坑：
  - 数据表行检索是**逐表 LIKE**（无全文索引），表多且行多时是线性成本；已用 `ROWS_PER_TABLE=3` / 总行命中 20 封顶，并以 15s 结果缓存降低重复查询成本
  - 视图收敛只在「数据表」范围 + 表上下文且 URL 带 `?view=` 时生效；工作区范围不收敛，数据表范围不带 view 参数视为整表检索（面板底部显示「表名 · 整表」）
  - 行命中只跳到表网格页，**不定位到具体行**（网格暂无 `?row=` 深链参数）
  - `documentsApi.search` 仍保留（后端端点未删除），当前无前端调用方
- 最近一次全绿：`make check-fast` + 定向测试（后端 `tests/test_workspace_search.py` 17 例、前端 GlobalSearch 7 例与文档页 201 例）2026-10-21

## 续作：工作区搜索缓存与全表覆盖增强（原 ADR 0015，已并入本 ADR）

> 原独立文件已删除，编号 0015 不复用（追溯：`git log -- docs/adr/0015-search-cache-and-full-coverage.md`）。下列各节保留原 ADR 的约束 / 决策编号，代码与提交里的 `ADR 0015 Cx / Dx` 指的就是本节。

### 口径（原 ADR 0015）

| 需求片段 | 本设计的落地 |
|---|---|
| 未打开特定视图时，无法搜索到对应关键词内容 | 两个根因：① 不在表上下文（工作区页 / 文档页）时只扫**前 8 张表**，第 9 张及以后的数据表内容永远不进入结果；② 在表上下文但 URL 无 `?view=` 时，后端仍把数据表侧**收敛到当前表**，其他表内容搜不到。修复：工作区范围（`scope=all`）覆盖全部可读表且**不按视图收敛**；只有「数据表」范围（`scope=tables`）才收敛到当前表与激活视图（保留 ADR 0012 的视图口径） |
| 构建缓存机制，便于实施快速搜索 | 新增进程内搜索结果缓存（TTL 15s + LRU 256），键含工作区 / 用户 / 范围 / 关键词 / 表 / 视图 / 上限；重复查询与范围切换直接命中，不再逐表 LIKE；写路径（单行 CRUD、批量导入、数据同步）主动失效，批量写用短 TTL 兜底 |
| 覆盖全部内容 | 删除 `MAX_TABLES_SCAN` 截断，工作区范围内逐表扫描全部可读表；保留「总行命中 20 条即停」的展示预算，避免把面板撑爆 |

### Decision（原 ADR 0015）

### 1. 范围语义（修复「未打开视图搜不到」）

| 范围 | 数据表侧行为 | 视图收敛 | 当前表 |
|---|---|---|---|
| `all`（工作区） | 扫描全部可读表；当前表排在最前（仅排序） | **不收敛** | 仅排序优先 |
| `tables`（数据表） | 有表上下文 → 只扫当前表；无表上下文 → 全部可读表 | URL 带 `?view=` 时按该视图 filters 收敛；否则整表 | 收敛目标 |
| `documents`（文档） | 不跑数据表侧 | — | — |

前端 `GlobalSearch` 只在 `scope === 'tables'` 时下发 `view_id`；`table_id` 始终下发，但在工作区范围只用于排序。后端在 `scope=all` 时忽略 `view_id`，即使旧客户端传了也不会收窄。

### 2. 全表覆盖

`_search_tables` 删除 `tables[:MAX_TABLES_SCAN]`，`targets` 为全部可读表（当前表前置）。保留 `MAX_ROWS_TOTAL=20` 短路：行命中达到 20 条即停止扫描，面板展示上限不变。

### 3. 搜索结果缓存

- **实例**：`core/cache.py` 新增 `search_cache = TTLCache(max_entries=256, name="search")`，并接入 `invalidate_all`。
- **键**：`search | workspace_id | user_id | scope | table_id | view_id | limit | keyword`；`scope=all` 时 `view_id` 归一为 0，避免无意义的缓存分片。
- **TTL**：15s。交互搜索的重复率远高于 15s，命中后零 SQL；权限变化（如工作区角色调整）最迟 15s 生效。
- **入口**：`search_workspace` 包一层 `get → 计算 → set`，空结果同样缓存（关键词不存在是全扫的最坏情况，最需要缓存）。

### 4. 失效矩阵

| 写入 | 失效方式 | 覆盖 |
|---|---|---|
| 单行 create / update / delete / trash / restore | `log_action → record_event → invalidate_for_event` 清 `search\|{wid}` | 即时 |
| 批量导入 / 数据同步（`bulk_create` / `bulk_update` / `bulk_update_rows`） | 写函数末尾显式清 `search\|{wid}`（best-effort） | 即时 |
| 表 / 字段 / 视图 / 行级权限变更 | `table.*` / `row_rule.*` 事件清 `search\|{wid}`；无事件路径由 TTL 兜底 | ≤15s |
| 文档创建 / 更新 / 删除 | `document.*` 事件清 `search\|{wid}`；文档写路径无事件时由 TTL 兜底 | ≤15s |
| 备份恢复 / 成员角色变更 | `invalidate_all()` 或 TTL | ≤15s |

### 边界与例外（原 ADR 0015）

1. **展示预算仍在**：总行命中 20 条即停，命中极多时后面的表可能只剩表名结果；需要「看全部命中」应另立 ADR 做独立结果页 / 分页。
2. **`$query` 仅文本列**：数字、日期、选项字段的关键词不命中（当前边界）。
3. **缓存不跨进程**：与项目单进程部署一致；多实例部署前必须换成共享后端（`CacheBackend` 协议已预留）。
4. **权限变更延迟**：成员角色 / 表权限调整没有统一事件时，最迟 15s 后生效。

### 落地状态（原 ADR 0015）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 | 已落地 | `src/cndb/plugins/workspaces/services/search.py`、`src/cndb/plugins/workspaces/routers/search.py`、`src/cndb/core/cache.py`、`src/cndb/core/events.py`、`src/cndb/plugins/tables/services/core/records.py`、`frontend/src/components/GlobalSearch.tsx`、`frontend/src/api/search.ts` | `tests/test_workspace_search.py`、`frontend/src/components/GlobalSearch.test.tsx` | 8d0df1f2 |

> 状态只取「未开始 / 进行中 / 已落地」。标「已落地」的期必须有代码落点与测试文件。

### 交接（原 ADR 0015）

- 当前阶段：P0 已落地（功能完成，无后续分期）
- 已完成：`scope=all` 改为全工作区覆盖且不按视图收敛；删除 8 张表截断；`search_cache`（15s / 256 条）与事件 / 批量写失效；前端只在数据表范围下发 `view_id`
- 下一步：无
- 已知坑：`$query` 只搜文本列（数字 / 日期 / 选项不命中）；总行命中 20 条为面板展示预算；缓存失效 best-effort，权限变化最迟 15s 生效
- 最近一次全绿：`make check-fast` + `make test`（5136 passed / 8 skipped）+ 前端定向单测 34 例（`GlobalSearch` / `MainLayout`）2026-10-21 @ `8d0df1f2`
