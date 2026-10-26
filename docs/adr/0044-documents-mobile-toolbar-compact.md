# ADR 0044: 文档列表页移动端顶部工具栏紧凑化

Status: Proposed（待评审）
Date: 2026-10-26
Related: `frontend/src/pages/documents/DocumentsPage.tsx`、`frontend/src/pages/documents/DocumentsPage.test.tsx`、`frontend/src/index.css`、`frontend/src/hooks/useResponsive.ts`
需求卡片: `docs/requirements/0044-documents-mobile-toolbar-compact.md`（需求原文与约束编号的唯一副本）

> 需求变更时**先改本 ADR 再改代码**：删去失效的口径行 / 现状条目 / 决策 D 行 / 测试与分期，不留「历史方案」「以后备用」段落；整节不适用写「无」。ADR 被新方案替代或需求作废时**直接删除本文件**，同步删除 `docs/adr/README.md` 索引行与代码 / 文档中的引用（git 历史可追溯），不在仓库保留 `Superseded` / `Deprecated` 文档；编号不复用。

## 口径（需求 → 设计落点）

需求原文：见需求卡片 §需求原句（逐字，ADR 不复制第二份）。

卡片约束沿用各自编号（C1..Cn），本表只补「设计怎么落地」，不重新拆句：

| 卡片约束 # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | 移动端工具栏由固定三行收敛为默认两行 | 第一行：返回（仅子层，纯图标）+ 面包屑（`flex: 1, minWidth: 0` 省略）+「更多」；第二行：标题过滤（`flex: 1`）+「筛选」+「新建」。行 `gap` 10 → 8，`marginBottom` 16 → 12 |
| C2 | 排序 / 标签 / 状态默认收起，由「筛选」按钮展开 | 新增 `filterOpen` 状态；筛选行仅在 `filterOpen` 时渲染（`data-testid="doc-toolbar-filters"`），保持 `repeat(3, minmax(0, 1fr))` 三等分；「筛选」按钮 `data-testid="doc-toolbar-filter"`、`aria-expanded` 反映展开态 |
| C3 | 收起态需可见已应用筛选 | `activeFilterCount = (orderBy !== 'sort') + (tagFilter !== undefined) + (statusFilter ? 1 : 0)`；`Badge count` + `aria-label`「筛选」/「筛选（已应用 N 项）」；`count === 0` 时 Badge 自然不显示 |
| C4 | 主要可点元素高度不下降 | 搜索框、筛选 / 更多 / 新建按钮均保持 antd 默认尺寸（32px），不传 `size="small"`；紧凑只来自行数与留白 |
| C5 | 既有能力与入口不丢失 | 「更多」菜单内容原样（新建文件夹 / 导入文件 / 导入 Obsidian 库 / 导出 / 回收站）；返回、面包屑、搜索、新建文档、排序 / 标签 / 状态筛选逻辑全部复用，仅改变容器结构 |
| C6 | 桌面端不变 | 仍走 `!isMobile` 分支的三段 `Space` 布局，代码原样 |
| C7 | 区段留白同步收窄 | 系列详情卡 `marginBottom` 移动端 16 → 12；`index.css` 为 `.cn-doc-recent` 补窄屏规则（`margin-bottom: var(--cn-space-md)`、`padding: var(--cn-space-xs) var(--cn-space-sm)`） |

决策结论只在「决策记录」写一次；本节与正文不再罗列「已确认决策」。

## Context

现状逐条核对（以代码为准，标注 `文件:行号`）。沿用需求卡片「现状影响面」的编号，逐条给结论：

| # | 现状 | 位置 | 影响 | 与卡片的关系 |
|---|---|---|---|---|
| 1 | 移动端工具栏为固定三行：面包屑行 /（搜索 + 更多 + 新建）/（排序 + 标签 + 状态三等分），`gap: 10`、`marginBottom: 16` | `frontend/src/pages/documents/DocumentsPage.tsx:475-496` | 392px 宽度下顶部固定占三行，约 120px，第一屏列表被顶下移 | 确认（C1 主缺口） |
| 2 | 排序 / 标签 / 状态三等分常驻 | `frontend/src/pages/documents/DocumentsPage.tsx:491-495` | 未使用筛选时仍持续占一整行 | 确认（C2） |
| 3 | 「更多」菜单已承载次级入口，内容为新建文件夹 / 导入文件 / 导入 Obsidian 库 / 导出 / 回收站 | `frontend/src/pages/documents/DocumentsPage.tsx:463-470`、`:485-487` | 既有收敛成果，保持不动 | 排除（C5） |
| 4 | 返回上级为文字按钮「上一级」，移动端与桌面共用同一节点 | `frontend/src/pages/documents/DocumentsPage.tsx:407-409`、`:479` | 移动端占约 80px 横向空间，挤压面包屑 | 新增（C1 横向紧凑） |
| 5 | 「最近打开」条 `margin-bottom: 12px`、`padding: 4px 8px` | `frontend/src/index.css:4861-4867` | 工具栏收窄后该条留白相对突出 | 新增（C7） |
| 6 | 系列详情卡 `marginBottom` 固定 16 | `frontend/src/pages/documents/DocumentsPage.tsx:669` | 子层顶部多一层 16px 留白 | 新增（C7） |
| 7 | 既有移动端用例断言 `doc-order-select` / `doc-tag-filter` 在工具栏内可见 | `frontend/src/pages/documents/DocumentsPage.test.tsx:585-609` | 筛选默认收起后该断言失效 | 确认（C2 需同期改写） |
| 8 | 桌面端用例直接取 `doc-order-select` / `doc-tag-filter`（默认 `responsiveState` 为 desktop） | `frontend/src/pages/documents/DocumentsPage.test.tsx:282`、`:334`、`:501`、`:528` | 桌面分支不动，断言不变 | 排除（C6 依据） |
| 9 | e2e 无文档列表工具栏定位用例 | `frontend/tests/e2e/critical/` | 结构变化无端到端流程影响 | 排除（不新增 e2e） |
| 10 | 断点为 768px，与 antd 一致；文档页已按 `isMobile` 分叉移动 / 桌面两套工具栏 | `frontend/src/hooks/useResponsive.ts:5-6`、`DocumentsPage.tsx:475` | 只需改移动分叉，不影响平板 / 桌面 | 复用 |

**核心缺陷（需求要补的）**：移动端工具栏把「导航」「操作」「筛选」三种不同频次的控件都做成常驻整行——导航与搜索确需常驻，排序 / 标签 / 状态是低频筛选却固定占一行，导致顶部纵向空间与列表首屏争抢。

设计目标（不变量）：

- **I1 默认两行**：移动端工具栏在筛选收起时为两个直接子块（导航行 + 操作行），不再出现第三行常驻控件。
- **I2 能力不减**：C5 列出的全部入口与筛选能力在移动端仍可达，行为与现状一致。
- **I3 收起可感知**：筛选收起时，已应用的排序 / 标签 / 状态通过计数徽标与 `aria-label` 可感知。
- **I4 触达不缩水**：移动端搜索框与按钮保持默认尺寸（32px），不以缩小控件换取紧凑。
- **I5 桌面零变更**：`!isMobile` 分支 DOM 与行为不变，既有桌面用例不改断言。

## Decision

以下小节按需增减；不适用的小节保留标题写「无」。

### 1. 数据模型

无（纯前端布局调整，不落库）。

### 2. 判定算法（唯一入口）

无后端判定。前端唯一口径在 `DocumentsPage` 的 `isMobile` 分支：`activeFilterCount` 由 `orderBy` / `tagFilter` / `statusFilter` 三个既有状态派生，筛选行是否渲染只看 `filterOpen`。

### 3. API 变更清单

无。

### 4. 边界与例外

1. **深链筛选**：`?tag=` / `?order=` / 状态筛选仍按 URL 与本地状态生效；面板默认收起，计数徽标提示已应用项，不自动展开（避免深链重新占第三行）。
2. **无已应用筛选**：`activeFilterCount === 0` 时 Badge 不显示数字（antd 默认行为），「筛选」按钮保持中性样式。
3. **面包屑过长**：导航行面包屑容器 `flex: 1, minWidth: 0, overflow: hidden`，沿用 antd Breadcrumb 自身的省略表现；「更多」按钮固定在行尾不被挤压。
4. **展开筛选后的高度**：筛选行作为第三行插入，仅在用户主动展开时出现；滚动位置与列表数据不受影响（三个控件仍写既有状态 / URL）。
5. **平板 / 桌面**：`isMobile` 仅在 `< 768px` 为真，平板沿用桌面分支（C6）。
6. **返回入口**：仅 `parentId !== null` 时渲染图标按钮，`aria-label="上一级"` 保留可访问名；桌面文字按钮不变。

### 5. 迁移

无。

### 6. 前端

| 层 | 文件 | 改动 |
|---|---|---|
| 页面 | `frontend/src/pages/documents/DocumentsPage.tsx` | ① 新增 `filterOpen` 状态与 `activeFilterCount` 派生；② 移动端工具栏重排为两行（导航行：图标返回 + 面包屑 + 更多；操作行：搜索 + 筛选 + 新建），`gap` 8、`marginBottom` 12；③ 筛选行条件渲染（`data-testid="doc-toolbar-filters"`），保持三等分；④ 筛选按钮 `Badge` + `aria-expanded` + `aria-label`；⑤ 系列详情卡 `marginBottom` 移动端 12 |
| 样式 | `frontend/src/index.css` | `.cn-doc-recent` 补 `<768px` 规则：`margin-bottom: var(--cn-space-md)`、`padding: var(--cn-space-xs) var(--cn-space-sm)` |
| 页面单测 | `frontend/src/pages/documents/DocumentsPage.test.tsx` | 移动端用例改为：默认两行 + 筛选行不存在；点「筛选」后三个控件可见；再点收起；`?tag=7` 深链断言徽标 / `aria-label`；「更多」菜单与新建按钮断言保留 |

### 7. 测试清单

**判定层（单测）**：无（无判定算法变更）。

**接口层**：无（无 API 变更）。

**迁移 / 备份**：无。

**前端单测**（`DocumentsPage.test.tsx`）：

- 移动端默认态：工具栏存在；`doc-toolbar-filters` 不存在；`doc-order-select` / `doc-tag-filter` 查询为 null；搜索、筛选、更多、新建可见；
- 展开 / 收起：点 `doc-toolbar-filter` 后 `doc-order-select` / `doc-tag-filter` 出现且可见，`aria-expanded` 为 `true`；再点后消失；
- 已应用筛选：`/w/10/documents?parent=1&tag=7` 下筛选按钮 `aria-label` 含「已应用 1 项」，筛选行默认收起；
- 回归：「更多」菜单仍含回收站 / 导入文件 / 新建文件夹；桌面端既有排序切换、标签回显、回收站用例不改断言通过。

**e2e（前端）**：无（结构收敛不新增端到端流程，可见性由前端单测覆盖）。

### 8. 分期

| 期 | 内容 | 风险 |
|---|---|---|
| **P0 工具栏重排** | 两行结构 + 筛选收起 / 展开 + 计数徽标 + 移动端返回图标化 | 中（既有移动端用例定位需同期改写） |
| **P1 区段留白收窄** | 系列详情卡 `marginBottom`、`.cn-doc-recent` 窄屏规则 | 低 |

## 决策记录（唯一决策台账）

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | 整体方案：三行如何收敛 | **保留两行常驻（导航 + 操作），筛选改为可展开的第三行** | 导航与搜索是高频操作需常驻；排序 / 标签 / 状态是低频筛选，收起后不损失能力（I1/I2） | ① 继续三行只缩间距（纵向收益有限，仍是三行常驻）；② 把筛选收进「更多」菜单（混杂销毁性操作，筛选是列表高频动作，语义不合） | `DocumentsPage.tsx` |
| D2 | 已应用筛选在收起态的提示 | 计数徽标 + `aria-label`（「筛选（已应用 N 项）」） | 收起后用户仍需知道列表被筛选过；徽标不占纵向空间、`aria-label` 可测可读屏（I3） | 收起态常显当前筛选文本（又占一行）；只靠徽标无文本（读屏不可达） | `DocumentsPage.tsx` |
| D3 | 移动端返回按钮形态 | 纯图标 + `aria-label="上一级"`，桌面保持文字 | 返回是高频但语义单一动作，图标可省约 40px 给面包屑（C1） | 继续用「上一级」文字（挤压面包屑，且与图标语义重复） | `DocumentsPage.tsx` |
| D4 | 是否靠缩小控件换紧凑 | **不缩小**：搜索 / 筛选 / 更多 / 新建保持默认尺寸 | 32px 是触控可用下限，紧凑应来自行数与留白而非压缩可点区（C4） | 全部改 `size="small"`（触控目标 24px，误触率上升） | `DocumentsPage.tsx` |
| D5 | 桌面端是否同步调整 | **不同步**：`!isMobile` 分支原样 | 桌面横向空间充足，三行问题只存在于窄屏；既有桌面用例零改动（C6/I5） | 桌面也收筛选（无收益且改动面扩大，违背最小改动） | `DocumentsPage.tsx` |
| D6 | 是否新增 e2e | 不新增：无端到端流程变化，可见性由前端单测断言 | e2e 无文档列表工具栏定位用例，单测已覆盖同 DOM 断言 | 为布局断言补 e2e（维护成本高、无增量收益） | `DocumentsPage.test.tsx` |

门禁：`Proposed` → `Accepted` 前本表不得有「待定」；结论只在本书出现，别处只引用编号。

## Consequences

- **正向**：移动端顶部由三行常驻降为两行，列表首屏上移约一整行；筛选收起后可感知已应用条件；返回图标化给面包屑让出横向空间；桌面零变更。
- **负向**：使用排序 / 标签 / 状态筛选时多一次点击（先展开面板）；移动端与桌面工具栏入口形态不一致（图标筛选 vs 常显下拉）。
- **风险与缓解**：既有移动端用例按常显下拉定位（卡片 #7）→ 同期改为「先点筛选再断言」，并补收起 / 展开与徽标断言，`make flow` 全绿收口。

被否决的替代方案见「决策记录」对应行，此处不重复。

## 行业对照（可选）

无。

## 与既有 ADR 的关系（可选）

| 轴 | 载体 | 决定 | 由谁 |
|---|---|---|---|
| 窄屏顶部控件收敛 | 文档页「更多」菜单 | 本 ADR 沿用「次级入口收菜单 / 主操作常驻」口径，进一步把低频筛选收起 | 本轮 CHANGELOG「手机端顶栏与页面首屏控件过多」修复 |
| 移动端断点与布局分叉 | `useResponsive` 768px | 继续按 `isMobile` 单一分叉，不新增断点 | 既有 `useResponsive` 口径 |

## 落地状态（随实现更新）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 工具栏重排 | 已落地 | `frontend/src/pages/documents/DocumentsPage.tsx` | `frontend/src/pages/documents/DocumentsPage.test.tsx` | 待提交 |
| P1 区段留白收窄 | 已落地 | `frontend/src/pages/documents/DocumentsPage.tsx`、`frontend/src/index.css` | `frontend/src/pages/documents/DocumentsPage.test.tsx` | 待提交 |

> 状态只取「未开始 / 进行中 / 已落地」。标「已落地」的期必须有代码落点与测试文件；全期落地后由人确认 `Status` 是否改 `Accepted` / `Implemented`。`make adr-check` 会校验本表与代码、测试、CHANGELOG 的对应关系。

## 交接（会话结束更新）

- 当前阶段：P0 / P1 代码与测试已就绪，待需求方评审 ADR 后回填 `Status`
- 已完成：移动端工具栏两行化、筛选收起 / 展开与计数徽标、返回图标化、系列详情卡与「最近打开」留白收窄
- 下一步：人工评审 D1–D6，确认后将 `Status` 改为 `Accepted` / `Implemented`
- 已知坑：`Badge` 在 `count === 0` 时不渲染数字，断言徽标须用按钮 `aria-label` 而非 DOM 数字；桌面端用例依赖默认 `responsiveState = desktop`
- 最近一次全绿：`make flow` @ 未提交（2026-10-26，5509 passed / 3 skipped）
