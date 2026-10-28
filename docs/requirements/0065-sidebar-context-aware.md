# 需求卡片：侧边栏随工作区功能切换显示文档结构

- 编号：0065（与 ADR `docs/adr/0065-*.md` 同号，卡片存 `docs/requirements/0065-<topic>.md`）
- 来源 / 提出人：用户
- 日期：2026-10-28
- 关联 ADR：无（S1，方案写入本卡片「口径」节）

> 本卡片是**需求原文与约束编号的唯一副本**：ADR 只引用 C1..Cn，不复制原文；需求澄清后先改这里，再同步 ADR「口径」表。

## 需求原句（逐字）

> 请优化导航布局和工作区功能切换设计，数据表切换到文档，侧边栏不应还显示数据表列表，而是文档结构。

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 数据表切换到文档 | 前端路由处于 `/w/:wid/documents(/:docId)` 时，桌面端 Sider 内容切换为当前打开文档的标题结构（大纲）；不再渲染数据表列表 | frontend/layouts/MainLayout | 前端单测 + e2e |
| C2 | 侧边栏不应还显示数据表列表 | 路由在文档功能段下，`sider-tables`（数据表列表及其操作菜单）不渲染；数据表能力入口仍由顶部「数据表」页签承担 | frontend/layouts/MainLayout | e2e 断言 testid 不存在 |
| C3 | 而是文档结构 | Sider 中渲染文档大纲（标题层级树），复用 `OutlineList`（`frontend/src/pages/documents/OutlineList.tsx`）；点击条目锚点滚动到对应标题；未打开具体文档时显示文档列表或空态提示 | frontend/layouts、frontend/pages/documents | 前端单测 |
| C4 | 优化导航布局和工作区功能切换设计 | 切换行为按当前路由段（tables / documents / 其他）判别，而非仅按 `workspaceTypeFeatures`；`data_doc` 工作区在两功能间切换时 Sider 内容跟随切换；纯 `data` 或 `doc` 类型工作区行为不变（doc 类型维持大纲侧栏，data 类型维持表列表） | frontend/layouts、frontend/utils/workspaceType.ts | 前端单测 |
| C5 | （其他功能段） | 路由处于 `analytics` / `datasource` / `settings` 段时隐藏 Sider，布局主体占满宽度 | frontend/layouts | 前端单测 + e2e |
| C6 | （可发现性） | Sider 顶部保留区域标题（如「文档结构」/「数据表」），移动端抽屉行为与现状一致不回退 | frontend/layouts | e2e |

## 现状影响面（候选，待精查）

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | Sider 仅按 `wsFeatures.tables` 渲染数据表列表 | `frontend/src/layouts/MainLayout.tsx:349-395` | 核心改动点 |
| 2 | Sider 挂载条件为 `wsFeatures.tables` | `frontend/src/layouts/MainLayout.tsx:501-509` | 需改为「tables 能力且路由在 tables 段」或「documents 能力且路由在 documents 段」 |
| 3 | 工作区类型能力映射与落地路由 | `frontend/src/utils/workspaceType.ts:43-57` | 判别字段来源 |
| 4 | 文档大纲数据与树渲染已存在 | `frontend/src/pages/documents/OutlineList.tsx:27-43`、`frontend/src/components/Document/outline` | 复用基础，需要评估大纲数据的提升/共享方式 |
| 5 | 路由表 | `frontend/src/App.tsx:80-131` | 判别 `/w/:wid/documents` 段 |

## 口径（方案）

1. **判别逻辑**：在 `MainLayout` 中按 `location` 判定当前功能区段（`inDocumentsContext = /w/:wid/documents` 前缀，与现有 `inTableContext` 同形）。Sider 渲染改为四分支：
   - 路由在文档段且 `wsFeatures.documents` → 渲染文档侧栏；
   - 路由在表段且 `wsFeatures.tables` → 维持现状数据表列表；
   - 路由在 `analytics` / `datasource` / `settings` 段 → 隐藏 Sider，主体占满宽度（C5）；
   - 无对应能力 → 不渲染 Sider（现状不变）。
2. **文档侧栏**（2026-10-29 按用户反馈修订：文档/文件夹树取代大纲与平铺列表）：
   - 文档段（含未选中与已选中文档）侧栏统一显示**文档/文件夹树**（`documentsApi.tree` + `buildDocTree` + antd Tree，与文档管理页共享 react-query 缓存）：点文档进编辑器，点文件夹进对应层级管理页（`?parent=`）；编辑器视图下高亮当前文档；侧栏**不再显示标题大纲**（大纲仍由编辑器右侧大纲栏承担）。
   - 自动展开：当前文档祖先链 + 一级文件夹；用户手动展开/收起后以手动状态为准。
   - 不承载「新建文档」等操作按钮，操作入口保留在文档列表页（Q2 已确认）。
   - 已废弃的中间方案（大纲 store + 侧栏锚点跳转）连同 `store/docOutline.ts` 一并移除，不留兼容代码。
2a. **移除页面内重复左树**（2026-10-29 第二次修订：侧栏树与 DocumentsLayout 页面内左树重复）：
   - DocumentsLayout 不再渲染页面内左侧文档树（桌面 aside 与移动端 FAB 抽屉），仅保留 `<Outlet />` 内容出口；文档树统一由布局侧边栏承担。
   - DocumentsPage 内容区的系列卡片网格与文件夹/文档列表**保留**；`DocumentTree` 组件暂保留（其拖拽/右键管理能力未迁移到侧栏，后续演进再定去留）。
   - 状态筛选从组件局部状态改为 URL 参数 `?status=`，与 `?parent=` / `?order=` / `?tag=` 同机制。
2b. **排序 / 刷新 / 过滤入侧栏**：文档段侧栏树上方提供——排序下拉（写 `?order=`）、刷新按钮（invalidate `['documents', wid]` 全部文档查询）、标签筛选（写 `?tag=`，选项来自 `documentsApi.tags`）、状态筛选（写 `?status=`）；均为 URL 驱动，文档列表页与编辑器视图下均可用，DocumentsPage 工具栏不再重复渲染这些控件。
3. **不做的事**：不改后端接口；不改移动端抽屉交互语义（仅内容跟随同一判别逻辑）；不引入新路由。

## 未决问题

- [x] Q1：未打开具体文档时 Sider 显示什么？——已确认：文档列表，点击进入后切换为大纲。
- [x] Q2：Sider 是否承载「新建文档」等操作按钮？——已确认：不需要，入口保留在文档列表页。
- [x] Q3：`analytics` / `datasource` / `settings` 段 Sider 显示什么？——已确认：隐藏 Sider。

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [ ] 未决问题全部有结论，需求方确认
