# ADR 0042: 文档插入图片 / 插入表格引用入口收进编辑模式工具栏

Status: Implemented
Date: 2026-10-26
Related: `frontend/src/components/Document/MarkdownToolbar.tsx`、`frontend/src/pages/documents/DocumentEditorPage.tsx`、`frontend/src/pages/documents/InsertTableModal.tsx`、`frontend/src/pages/documents/DocumentEditorPage.test.tsx`、`frontend/src/components/Document/MarkdownToolbar.test.tsx`、`docs/adr/0025-document-asset-formats.md`
需求卡片: `docs/requirements/0042-edit-toolbar-insert-entries.md`（需求原文与约束编号的唯一副本）

> 需求变更时**先改本 ADR 再改代码**：删去失效的口径行 / 现状条目 / 决策 D 行 / 测试与分期，不留「历史方案」「以后备用」段落；整节不适用写「无」。ADR 被新方案替代或需求作废时**直接删除本文件**，同步删除 `docs/adr/README.md` 索引行与代码 / 文档中的引用（git 历史可追溯），不在仓库保留 `Superseded` / `Deprecated` 文档；编号不复用。

## 口径（需求 → 设计落点）

需求原文：见需求卡片 §需求原句（逐字，ADR 不复制第二份）。

卡片约束沿用各自编号（C1..Cn），本表只补「设计怎么落地」，不重新拆句：

| 卡片约束 # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | 插入图片入口整合到编辑模式工具栏或附近，仅编辑模式渲染 | 顶栏「图片」按钮删除；`MarkdownToolbar` 新增可选按钮 `md-toolbar-image`（`PictureOutlined`），由 `DocumentEditorPage` 仅在编辑分支且非窄屏时传入 `onInsertImage`（沿用 `onAiAction` 可选 props 模式，不传不渲染） |
| C2 | 插入表格引用入口同上，且与「插入 Markdown 表格」区分 | 顶栏「插入表格引用」按钮删除；`MarkdownToolbar` 新增可选按钮 `md-toolbar-table-ref`（`DatabaseOutlined`，title「插入表格引用（数据表）」），与既有 `md-toolbar-table`（`TableOutlined`，Markdown 表格骨架下拉）形状区分、并存 |
| C3 | 查看模式下不可见即不可操作 | 插入入口只出现在 `viewMode === 'edit'` 的编辑分支：桌面工具栏按钮随组件只在编辑分支渲染；窄屏「更多」菜单的 `insert-image` / `insert-table` 项仅编辑模式注入。查看模式（含原件文档 / 文件夹）全站无插入入口 |
| C4 | 窄屏「更多」菜单一致性 | 窄屏编辑模式：两项保留在「更多」菜单（`docMoreItems` 以 `viewMode === 'edit'` 为注入条件）；窄屏编辑分支不向 `MarkdownToolbar` 传两个新 props，避免 390px 工具栏拥挤 |
| C5 | 迁移不改既有功能 | 上传链路（隐藏 file input → `fileApi.upload` → 串行队列 → `insertSnippetAtCursor`）、粘贴图片、`InsertTableModal` 插入 `{{table:...}}` 占位符全部原样；隐藏 file input 仍页面级唯一实例，工具栏按钮与窄屏菜单共用 |

决策结论只在「决策记录」写一次；本节与正文不再罗列「已确认决策」。

## Context

现状逐条核对（以代码为准，标注 `文件:行号`）。沿用需求卡片「现状影响面」的编号，逐条给结论：

| # | 现状 | 位置 | 影响 | 与卡片的关系 |
|---|---|---|---|---|
| 1 | 顶栏「图片」按钮仅 `!isAssetDoc` 门禁，view / edit 两模式都渲染、都可点 | `frontend/src/pages/documents/DocumentEditorPage.tsx:1017-1026` | 查看模式点击会走上传链路并改写正文（见 #5），静默产生「未保存」改动 | 确认（C1/C3 主缺口） |
| 2 | 顶栏「插入表格引用」按钮同样仅 `!isAssetDoc` 门禁 | `frontend/src/pages/documents/DocumentEditorPage.tsx:1037-1041` | 同上：查看模式可打开 `InsertTableModal` 并把占位符写进正文 | 确认（C2/C3） |
| 3 | 窄屏「更多」菜单 `docMoreItems` 含 `insert-image` / `insert-table`，两模式共用菜单 | `frontend/src/pages/documents/DocumentEditorPage.tsx:886-887` | 窄屏查看模式同样可触发插入 | 确认（C4） |
| 4 | `MarkdownToolbar` 已有可选 props 模式（`onAiAction` 不传完全不渲染）；`table` 键已被「插入 Markdown 表格」骨架下拉占用 | `frontend/src/components/Document/MarkdownToolbar.tsx:47-51`、`:99`、`:143-164`、`:178-206` | 新入口可零破坏接入；同图标并存会混淆，需形状区分（D2） | 复用（C1/C2 落点） |
| 5 | `insertSnippetAtCursor` 在 `editorRef` 为空（查看模式无编辑器实例）时回退「插到正文末尾」 | `frontend/src/pages/documents/DocumentEditorPage.tsx:656-669` | 查看模式的插入不是报错而是静默改稿——入口泄漏的真实危害佐证 | 确认（C3 依据） |
| 6 | 隐藏图片 file input 为页面级唯一实例，顶栏按钮 / 窄屏菜单共用 | `frontend/src/pages/documents/DocumentEditorPage.tsx:1221-1229` | 迁移后保持唯一，仅改触发方 | 复用（C5） |
| 7 | `InsertTableModal` 与触发位置解耦，弹窗内选择表 / limit / 插入逻辑自包含 | `frontend/src/pages/documents/InsertTableModal.tsx:1` | 弹窗本体不动，只换打开入口 | 排除（无需改动） |
| 8 | 既有测试按顶栏按钮 / 更多菜单定位插入入口（测试文档 2 为 draft，默认进入编辑模式） | `frontend/src/pages/documents/DocumentEditorPage.test.tsx:78`、`:106`、`:453`、`:701-751` | 编辑模式下的定位改由工具栏按钮承载；需补查看模式「不可见」断言 | 确认（C5） |
| 9 | e2e 无用例引用插入图片 / 插入表格引用入口（仅 `ai-entrypoints.spec.ts:43` 断言 `md-toolbar` 可见） | `frontend/tests/e2e/critical/ai-entrypoints.spec.ts:43` | 工具栏新增按钮不影响该断言；入口位置迁移无新端到端流程 | 排除（不新增 e2e，D6） |

**核心缺陷（需求要补的）**：插入入口的可见性绑定在「文档页顶栏」而不是「编辑模式」——查看模式下既能点、点了还会静默改稿（光标回退到末尾插入），违背查看模式的只读预期。

设计目标（不变量）：

- **I1 模式即门禁**：插入图片 / 插入表格引用入口只在 `viewMode === 'edit'` 且非原件文档的编辑分支出现；查看模式下任何位置不渲染（不可见即不可操作）。
- **I2 可选 props 零破坏**：`MarkdownToolbar` 新入口沿用「不传不渲染」模式，既有调用方与既有测试零感知。
- **I3 行为不变**：只迁移入口位置，不改上传 / 插入链路（file input、串行上传队列、粘贴图片、`InsertTableModal`、`insertSnippetAtCursor`）。
- **I4 单一 file input**：隐藏文件选择器仍为页面级唯一实例，桌面工具栏按钮与窄屏菜单共用，不新增 input。
- **I5 形状可辨**：工具栏内「插入 Markdown 表格」与「插入表格引用（数据表）」图标形状不同，不依赖悬浮文字区分。

## Decision

以下小节按需增减；不适用的小节保留标题写「无」。

### 1. 数据模型

无（纯前端入口位置迁移，不落库）。

### 2. 判定入口

无后端判定。前端唯一可见性口径在 `DocumentEditorPage`：编辑分支（`viewMode === 'edit'` 且非 `isAssetDoc`）内传 `onInsertImage` / `onInsertTableRef`（桌面）或注入菜单项（窄屏）；查看分支不渲染任何插入入口。

### 3. API 变更清单

无。

### 4. 边界与例外

1. **原件文档 / 文件夹**：编辑分支本身不可达（`DocumentEditorPage.tsx:1150` 先判 `isAssetDoc`，模式切换对其隐藏），插入入口随之消失——与现状口径一致，不另加门禁。
2. **图片上传中**：工具栏图片按钮透传 `imageInsertLoading`（= `imageMut.isPending`）保留 loading / 禁用呈现；上传中切换到查看模式时进行中的上传仍按现状走完（`onSuccess` 仍插入，改动落在「未保存」），不中断。
3. **上传中切模式**：不新增取消逻辑（现状也如此，本 ADR 不扩范围）。
4. **编辑器无选区 / 未聚焦**：沿用 `insertSnippetAtCursor` 的末尾回退，不变（编辑分支内编辑器实例始终存在，不再出现查看态静默改稿）。
5. **查看模式的既有插入手段**：编辑器内粘贴图片仍只在编辑模式可用（`MarkdownLiveEditor` 仅编辑分支挂载），与本 ADR 无交互。

### 5. 迁移

无。

### 6. 前端

| 层 | 文件 | 改动 |
|---|---|---|
| 工具栏组件 | `frontend/src/components/Document/MarkdownToolbar.tsx` | 新增可选 props：`onInsertImage?: () => void`、`imageInsertLoading?: boolean`、`onInsertTableRef?: () => void`。两个按钮渲染在 `link` 之后、AI 分隔符之前，各带 `data-testid`（`md-toolbar-image` / `md-toolbar-table-ref`）与 title（「插入图片」/「插入表格引用（数据表）」）；图片按钮 `loading={imageInsertLoading}`；不传对应回调则该按钮不渲染（沿用 `onAiAction` 模式，I2） |
| 文档编辑页 | `frontend/src/pages/documents/DocumentEditorPage.tsx` | ① 删除顶栏「图片」「插入表格引用」两按钮（`:1017-1026`、`:1037-1041`）；② `docMoreItems` 的 `insert-image` / `insert-table` 两项改为 `viewMode === 'edit'` 时才注入（窄屏入口，C4）；③ 编辑分支 `MarkdownToolbar` 调用处仅 `!isMobile` 时传 `onInsertImage={() => imageInputRef.current?.click()}`、`imageInsertLoading={imageMut.isPending}`、`onInsertTableRef={() => setInsertOpen(true)}`；隐藏 file input 与 `InsertTableModal` 挂载位置不动（I3/I4） |
| 组件单测 | `frontend/src/components/Document/MarkdownToolbar.test.tsx` | 不传新 props → 两个按钮不渲染；传入 → 渲染且点击透传回调；`imageInsertLoading` → 图片按钮禁用 / loading |
| 页面单测 | `frontend/src/pages/documents/DocumentEditorPage.test.tsx` | 既有插入用例定位调整（编辑模式下从 `md-toolbar-*` / 窄屏菜单进入，链路断言不变）；新增：查看模式断言 `md-toolbar-image`、`md-toolbar-table-ref`、顶栏按钮均不存在，窄屏查看模式「更多」菜单无这两项（C3/C4） |

### 7. 测试清单

**判定层（单测）**：无（无判定算法变更）。

**接口层**：无（无 API 变更）。

**迁移 / 备份**：无。

**前端单测**：

- `MarkdownToolbar.test.tsx`：不传新 props 零渲染（回归既有用例）；传 props 渲染两个按钮、点击触发回调、loading 透传；
- `DocumentEditorPage.test.tsx`：
  - 查看模式：`doc-view-mode` 下查询不到 `md-toolbar-image` / `md-toolbar-table-ref` / 顶栏图片与表格引用按钮；窄屏查看模式「更多」菜单不含「插入图片」「插入表格引用」；
  - 编辑模式（桌面）：工具栏两按钮可见，点击分别打开 file input 链路（沿用 `doc-image-input` 注入断言）与 `InsertTableModal`（既有用例定位改到此入口，`{{table:100}}` 插入断言不变）；
  - 编辑模式（窄屏）：「更多」菜单含两项且可打开弹窗；
  - 回归：插入图片上传成功 / 失败、粘贴图片、上传中 loading 等既有用例全绿。

**e2e**：无（D6：入口位置迁移无新端到端流程，可见性断言由前端单测承载；`ai-entrypoints.spec.ts` 的 `md-toolbar` 断言不受影响）。

### 8. 分期

| 期 | 内容 | 风险 |
|---|---|---|
| **P0 工具栏可选按钮** | `MarkdownToolbar` 三个可选 props + 两个按钮 + 组件单测 | 低 |
| **P1 页面接入与门禁** | 顶栏两按钮删除、工具栏传参（桌面）、窄屏菜单模式门禁、页面单测调整与新增 | 中（既有用例定位迁移，需保证编辑模式语义不变） |

## 决策记录（唯一决策台账）

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | 整体方案选型：插入入口放哪 | **方案 A**：进 `MarkdownToolbar`（可选 props），顶栏按钮删除；查看模式全站不渲染 | 需求方 2026-10-26 拍板；编辑分支是入口的语义归属，工具栏已承载全部 Markdown 写操作 | ① 方案 B：摆在工具栏旁不进组件（工具栏行布局两处维护，窄屏门禁仍要另做，非单点）；② 保留顶栏按钮、查看模式仅置灰（仍可见，违背「避免在查看模式可操作」，顶栏也更挤） | `MarkdownToolbar.tsx`、`DocumentEditorPage.tsx` |
| D2 | 工具栏内与「插入 Markdown 表格」的区分 | 数据表引用按钮用 `DatabaseOutlined` + title「插入表格引用（数据表）」，`data-testid=md-toolbar-table-ref` | 既有 `table` 键是 Markdown 表格骨架（`TableOutlined`），同图标相邻不可辨（I5） | 沿用 `TableOutlined`（工具栏出现两个同图标表格按钮，误点率高） | `MarkdownToolbar.tsx` |
| D3 | 图片上传 loading 态 | 工具栏图片按钮保留 `imageInsert.isPending` 的 loading（透传 `imageInsertLoading`），防止重复点击叠加队列 | 需求方 2026-10-26 确认；串行上传队列下重复触发会排队放大延迟 | 去掉 loading（迁按钮丢能力，体验回退） | `MarkdownToolbar.tsx`、`DocumentEditorPage.tsx` |
| D4 | 窄屏入口形态 | 编辑模式收进「更多」菜单（`viewMode === 'edit'` 才注入）；窄屏编辑分支不向工具栏传两个新 props | 需求方 2026-10-26 确认；工具栏已 10+ 按钮，390px 直接展示会挤掉正文（现状 `:874-876` 同口径收菜单） | 窄屏也展示在工具栏（挤；菜单是既有次级入口惯例） | `DocumentEditorPage.tsx` |
| D5 | 角色门禁是否调整 | 维持现状：仅模式门禁，不改角色门禁（`editable` 恒 true，viewer 保存走修改申请） | 需求方 2026-10-26 确认；入口泄漏的本质是模式错位而非角色错位 | 顺带加 `editable` 角色门禁（改写既有 0025 之后的编辑入口口径，扩范围） | 不动 |
| D6 | e2e 是否新增 | 不新增：无新端到端流程，可见性由前端单测断言 | e2e 全量检索无用例引用插入入口；`ai-entrypoints.spec.ts` 仅断言 `md-toolbar` 存在，新增按钮不破坏 | 为入口可见性补 e2e（单测已覆盖同 DOM 断言，e2e 增维护成本无增量收益） | `frontend/src/pages/documents/DocumentEditorPage.test.tsx` |

门禁：`Proposed` → `Accepted` 前本表不得有「待定」；结论只在本书出现，别处只引用编号。

## Consequences

- **正向**：查看模式恢复只读预期（插入入口不可见即不可操作，消除 #5 的静默改稿路径）；插入能力与写操作语义归位到编辑工具栏；可选 props 模式零破坏，既有调用方与测试无感知。
- **负向**：桌面用户从「顶栏常驻」变为「先切编辑模式」，插入图片多一步；窄屏与桌面入口形态不一致（菜单 vs 工具栏），帮助文档如提及顶栏按钮需同步。
- **风险与缓解**：既有用例按顶栏定位插入入口（卡片 #8）→ 同期迁移定位并补查看模式反断言，`make flow` 全绿收口。

被否决的替代方案见「决策记录」对应行，此处不重复。

## 行业对照（可选）

无。

## 与既有 ADR 的关系（可选）

| 轴 | 载体 | 决定 | 由谁 |
|---|---|---|---|
| 原件文档无编辑入口（含插入） | `DocumentAssetView` 分支 + `isAssetDoc` 判断 | 本 ADR 沿用其只读口径，不另加门禁 | ADR 0025 |

## 落地状态（随实现更新）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 工具栏可选按钮 | 已落地 | `frontend/src/components/Document/MarkdownToolbar.tsx` | `frontend/src/components/Document/MarkdownToolbar.test.tsx` | 14d182f1 |
| P1 页面接入与门禁 | 已落地 | `frontend/src/pages/documents/DocumentEditorPage.tsx` | `frontend/src/pages/documents/DocumentEditorPage.test.tsx` | 1c48163b |

> 状态只取「未开始 / 进行中 / 已落地」。标「已落地」的期必须有代码落点与测试文件；全期落地后由人确认 `Status` 是否改 `Accepted` / `Implemented`。`make adr-check` 会校验本表与代码、测试、CHANGELOG 的对应关系。

## 交接（会话结束更新）

- 当前阶段：P0 / P1 均已落地并提交，功能完结（`Status` 已于 2026-10-26 由人确认改 `Implemented`）
- 已完成：P0 `MarkdownToolbar` 三个可选 props + 两个按钮（`md-toolbar-image` / `md-toolbar-table-ref`，图片按钮 loading 态显式 `disabled`——antd loading 只加类不落 disabled 属性）；P1 顶栏两按钮删除、桌面编辑模式工具栏接入、窄屏「更多」菜单 `viewMode === 'edit'` 才注入插入项、隐藏 file input / `InsertTableModal` 未动
- 测试：`MarkdownToolbar.test.tsx` 13 例（不传不渲染 / 点击透传 / loading 只禁图片按钮）；`DocumentEditorPage.test.tsx` 57 例（新增：桌面查看模式无插入入口、窄屏编辑模式菜单含并可打开选表弹窗、窄屏查看模式菜单不含；既有插入表格引用 / 插入图片链路用例经新入口回归通过）
- 下一步：无（功能已完结；ADR 已登记 CHANGELOG「未发布 · 变更」）
- 已知坑：测试文档 2（`需求说明`）为 draft，默认进入编辑模式——查看模式用例需先点 `doc-mode-switch` 的「查看」；antd Button `loading` 不落 `disabled` 属性，断言禁用要显式传 `disabled`
- 最近一次全绿：`make check-fast` + `make test` @ 1c48163b（2026-10-26）
