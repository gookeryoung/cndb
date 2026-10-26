# 需求卡片：插入图片 / 插入表格引用入口收进编辑模式工具栏

- 编号：0042（与 ADR `docs/adr/0042-*.md` 同号，卡片存 `docs/requirements/0042-edit-toolbar-insert-entries.md`）
- 来源 / 提出人：用户（口头需求）
- 日期：2026-10-26
- 关联 ADR：<立项后回填>

> 本卡片是**需求原文与约束编号的唯一副本**：ADR 只引用 C1..Cn，不复制原文；需求澄清后先改这里，再同步 ADR「口径」表。

## 需求原句（逐字）

> 文档，插入图片和插入表格引用，应当整合到编辑模式的工具栏中或者附近，这样也能避免在查看模式可操作。

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 「插入图片…应当整合到编辑模式的工具栏中或者附近」 | 插入图片入口从文档页**顶栏**（现 `图片` 按钮，`doc-image-insert`）移到编辑模式的 Markdown 工具栏或其紧邻区域，仅在 `viewMode === 'edit'` 时渲染 | frontend `DocumentEditorPage` / `MarkdownToolbar` | 前端单测：查看模式查询不到插入图片入口；编辑模式可点并触发隐藏 file input |
| C2 | 「插入表格引用…应当整合到编辑模式的工具栏中或者附近」 | 插入表格引用入口（现顶栏「插入表格引用」按钮 → `InsertTableModal`）同样移到编辑模式工具栏或附近，仅在 `viewMode === 'edit'` 时渲染；与工具栏既有「插入 Markdown 表格」骨架下拉（`md-toolbar-table`）为两个并存入口，不得混淆 | frontend `DocumentEditorPage` / `MarkdownToolbar` / `InsertTableModal` | 前端单测：查看模式查询不到该入口；编辑模式点击打开弹窗并插入 `{{table:...}}` 占位符 |
| C3 | 「这样也能避免在查看模式可操作」 | 查看模式（`viewMode === 'view'`）下，文档页任何位置（桌面顶栏、窄屏「更多」菜单）都不出现插入图片 / 插入表格引用入口——不可见即不可操作 | frontend `DocumentEditorPage` | 前端单测：`doc-view-mode` 下 `doc-image-insert` 与表格引用入口均不存在 |
| C4 | 「插入图片和插入表格引用」（窄屏一致性） | 窄屏「更多」菜单中的 `insert-image` / `insert-table` 项随 C1–C3 一并处理：查看模式不出现；窄屏**编辑模式**下两入口仍可达（工具栏或菜单其一） | frontend `DocumentEditorPage` | 前端单测：窄屏查看模式「更多」菜单无这两项；窄屏编辑模式入口可达 |
| C5 | 隐含（入口迁移不改变功能） | 迁移后行为不变：图片仍走隐藏 file input → `fileApi.upload` → 光标处插入 `![alt](file:<key>)`（含串行上传队列 / 粘贴图片路径）；表格引用仍走 `InsertTableModal` 插入 `{{table:<id>…}}` 占位符 | frontend `DocumentEditorPage` | 既有 `DocumentEditorPage.test.tsx` 插入图片 / 插入表格引用用例随定位调整后全绿 |

约束编号在 ADR 中原样引用；不重编号、不合并。

## 现状影响面（候选，待 ADR 核实）

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | 顶栏「图片」按钮：仅 `!isAssetDoc` 门禁，view / edit 两模式都渲染、都可点 | `frontend/src/pages/documents/DocumentEditorPage.tsx:1017` | C1 移除对象；带 `imageMut.isPending` loading 态 |
| 2 | 顶栏「插入表格引用」按钮：同样仅 `!isAssetDoc` 门禁，查看模式可点 | `frontend/src/pages/documents/DocumentEditorPage.tsx:1037` | C2 移除对象 |
| 3 | 窄屏「更多」菜单 `docMoreItems` 的 `insert-image` / `insert-table` 项 | `frontend/src/pages/documents/DocumentEditorPage.tsx:886` | C4 对象；该菜单 view / edit 两模式共用 |
| 4 | 编辑模式 Markdown 工具栏（候选落点；已有可选 props 模式 `onAiAction`、已有 `table` 表格骨架下拉） | `frontend/src/components/Document/MarkdownToolbar.tsx:90`、`DocumentEditorPage.tsx:1189` | 「插入 Markdown 表格」与「插入表格引用（数据表）」需视觉区分 |
| 5 | 光标处插入片段逻辑（图片 / 表格引用共用） | `frontend/src/pages/documents/DocumentEditorPage.tsx:652` | 查看模式下无编辑器实例，现顶栏入口在查看态点击行为存疑 |
| 6 | 隐藏图片文件选择器（顶栏按钮 / 更多菜单共用） | `frontend/src/pages/documents/DocumentEditorPage.tsx:1221` | 迁移后仍需保持共用 |
| 7 | 插入数据表引用弹窗 | `frontend/src/pages/documents/InsertTableModal.tsx:1` | 弹窗本体预计不动，只改触发位置 |
| 8 | 既有测试按顶栏 / 更多菜单定位插入入口 | `frontend/src/pages/documents/DocumentEditorPage.test.tsx:78`、`:106`、`:453`、`:701` | C5：随入口迁移调整查询定位 |

> 编号与 ADR「Context」表对齐：ADR 逐条给「确认 / 排除 / 新增」并补齐 `file:line`。本阶段只粗查，精查归 ADR。

## 未决问题（已全部有结论，需求方 2026-10-26 确认）

- [x] 落点：**方案 A** —— 作为 `MarkdownToolbar` 新增可选按钮，沿用 `onAiAction` 的可选 props 模式（不传则不渲染，既有调用方 / 测试无感知）。
- [x] 图片上传 loading 态：**保留**，工具栏图片按钮保留 `imageMut.isPending` 的 loading / 禁用呈现。
- [x] 窄屏：两项**收进「更多」菜单**保留（仅编辑模式可见），不依赖工具栏在窄屏直接展示。
- [x] 门禁：**维持现状**——仅模式门禁（`viewMode`），不改角色门禁（`editable` 恒为 true，viewer 保存走修改申请）。

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [x] 未决问题全部有结论，需求方确认
