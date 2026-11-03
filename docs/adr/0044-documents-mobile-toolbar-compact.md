# ADR 0044: 文档列表页移动端布局紧凑化

Status: Implemented（2026-10-27 人工评审通过，2026-11-03 追加 P2）
Date: 2026-10-26（2026-11-03 追加整页紧凑化）
Related: `frontend/src/pages/documents/DocumentsPage.tsx`、`frontend/src/pages/documents/DocumentsPage.test.tsx`、`frontend/src/index.css`、`frontend/src/hooks/useResponsive.ts`
需求卡片: `docs/requirements/0044-documents-mobile-toolbar-compact.md`（需求原文与约束编号的唯一副本）

> 需求变更时**先改本 ADR 再改代码**：删去失效的口径行 / 现状条目 / 决策 D 行 / 测试与分期，不留「历史方案」「以后备用」段落；整节不适用写「无」。ADR 被新方案替代或需求作废时**直接删除本文件**，同步删除 `docs/adr/README.md` 索引行与代码 / 文档中的引用（git 历史可追溯），不在仓库保留 `Superseded` / `Deprecated` 文档；编号不复用。

## 口径（需求 → 设计落点）

需求原文：见需求卡片 §需求原句（逐字，ADR 不复制第二份）。

卡片约束沿用各自编号（C1..Cn），本表只补「设计怎么落地」，不重新拆句：

| 卡片约束 # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | 移动端工具栏默认两行 | 第一行：返回（仅子层，纯图标）+ 面包屑（`flex: 1, minWidth: 0` 省略）+「更多」；第二行：排序 + 标题过滤（`flex: 1, minWidth: 0`）+「筛选」+「新建」。行 `gap` 8 → 6，`marginBottom` 12 → 8，页面内边距 12 → 10 |
| C2 | 标签 / 状态按需展开，排序常驻 | 新增 `filterOpen` 状态；筛选行仅在 `filterOpen` 时渲染（`data-testid="doc-toolbar-filters"`，标签 / 状态两个 Select 各 `flex: 1, minWidth: 0`）；排序按钮与侧栏共享偏好（需求 0065），保持在操作行常驻；「筛选」按钮 `data-testid="doc-toolbar-filter"`、`aria-expanded` 反映展开态 |
| C3 | 收起态可见已应用标签 / 状态 | `activeFilterCount = (tagFilter !== undefined ? 1 : 0) + (statusFilter ? 1 : 0)`；`Badge count` + `aria-label`「筛选」/「筛选（已应用 N 项）」；`count === 0` 时 Badge 自然不显示 |
| C4 | 可点区域不缩水 | 顶栏搜索框、排序 / 筛选 / 更多 / 新建按钮保持 antd 默认尺寸（32px）；行尾「更多」与批量操作图标按钮为 `size="small"`（24px 点击区），与桌面行内操作一致 |
| C5 | 既有能力与入口不丢失 | 「更多」菜单内容原样（新建文件夹 / 导入 / 导出 / 回收站）；返回、面包屑、标题过滤、新建文档、排序、标签 / 状态筛选、行内重命名 / 移动 / 置顶 / 删除全部保留；移动端删除走 `Modal` 二次确认 |
| C6 | 桌面端不变 | 仍走 `!isMobile` 分支：工具栏三段 `Space`、250px+ 文件夹大卡、行尾四枚常驻图标均原样 |
| C7 | 区段留白同步收窄 | 页面内边距 10；`SectionTitle` 移动端 `marginBottom` 4；文件夹 / 子文件夹 / 文档块留白 16 → 8~10；系列详情卡 `marginBottom` 10；列表行与头像 / 操作区间距收紧一档（`index.css` 窄屏规则） |
| C8 | 文件夹区紧凑 | 顶层卡片网格移动端 `repeat(auto-fill, minmax(150px, 1fr))`、`gap` 8；卡片内边距 12 → 10，标题 15 → 14、文件夹图标 20 → 18、统计与更新时间 12 → 11、状态标签 10px/16px 行高；勾选与点击进入能力不变 |
| C9 | 文档列表行紧凑 | 移动端行尾四个操作收进单枚「更多」`Dropdown`（`data-testid="doc-row-more-{id}"`），菜单承载重命名 / 移动 / 置顶 / 删除；菜单 Portal 的点击用 `domEvent.stopPropagation()` 阻断 React 树冒泡，避免触发行跳转；删除用 `modal.confirm` 二次确认；桌面分支四枚图标原样 |
| C10 | 次级控件紧凑 | 移动端系列详情操作按钮图标化（保留 `aria-label="重命名系列" / "移动系列" / "删除系列"`）；批量操作栏的移动 / 删除在窄屏只留图标（保留 `aria-label`）；列表格式图标 22 → 18、描述行字号 12 → 11、状态 / 锁标签 10px/16px、大小与版本合并为「2.1 KB · v3」 |

决策结论只在「决策记录」写一次；本节与正文不再罗列「已确认决策」。

## Context

现状逐条核对（以代码为准，标注 `文件:行号`）。沿用需求卡片「现状影响面」的编号，逐条给结论：

| # | 现状 | 位置 | 影响 | 与卡片的关系 |
|---|---|---|---|---|
| 1 | P2 前移动端操作行把排序 / 搜索 / 标签 / 状态 / 新建五组控件塞进一行，390px 下实际换行成三行 | `DocumentsPage.tsx` 移动端工具栏（P2 前实现，`git show e6cd68f2` 可查） | 顶部常驻约 120px，首屏列表被顶下移 | 确认（C1/C2 主缺口） |
| 2 | P2 前顶层文件夹卡片最小宽度 240px，390px 屏只能单列，每张卡约 130px 高 | `DocumentsPage.tsx` 系列卡片（P2 前实现，同上） | 6 个文件夹占约 780px 纵向空间 | 确认（C8 主缺口） |
| 3 | P2 前移动端行尾四枚图标常驻，标题可用宽度约 130px | `DocumentsPage.tsx` 行内操作（P2 前实现，同上） | 长标题大量省略、描述行频繁折行 | 确认（C9 主缺口） |
| 4 | P2 前移动端系列详情三枚文字按钮在 390px 下换行，卡片高度多一行 | `DocumentsPage.tsx` 系列详情（P2 前实现，同上） | 系列头部占高，列表继续下移 | 确认（C10） |
| 5 | P2 前批量操作栏文字按钮在窄屏折行 | `DocumentsPage.tsx` 批量栏（P2 前实现，同上） | 多选时内容区再被顶下一行 | 确认（C10） |
| 6 | 「更多」菜单已承载次级入口，内容为新建文件夹 / 导入 / 导出 / 回收站 | `frontend/src/pages/documents/DocumentsPage.tsx:552-558` | 既有收敛成果，保持不动 | 排除（C5） |
| 7 | 返回上级为纯图标按钮，桌面为文字按钮 | `frontend/src/pages/documents/DocumentsPage.tsx:835-847` | 移动端已让出横向空间 | 排除（C1 已落地部分） |
| 8 | 桌面端文件夹卡片 / 列表行 / 工具栏走 `!isMobile` 分支 | `frontend/src/pages/documents/DocumentsPage.tsx:876-914`、`:1051-1066` | 桌面零变更 | 排除（C6 依据） |
| 9 | e2e 无文档列表工具栏 / 卡片定位用例 | `frontend/tests/e2e/critical/` | 纯布局收敛无端到端流程影响 | 排除（不新增 e2e） |
| 10 | 断点为 768px，文档页已按 `isMobile` 分叉移动 / 桌面两套布局 | `frontend/src/hooks/useResponsive.ts:5-6` | 只需改移动分叉，不影响平板 / 桌面 | 复用 |

**核心缺陷（P2 要补的）**：移动端把「高频操作」「低频筛选」「四枚行操作」都按桌面的横向富余来排，窄屏只能靠换行与压缩标题消化；紧凑化应从**减少常驻行数**与**让出横向空间**入手，而不是缩小点击区。

设计目标（不变量）：

- **I1 默认两行**：移动端工具栏在筛选收起时为两个直接子块（导航行 + 操作行），不再出现第三行常驻控件。
- **I2 能力不减**：C5 列出的全部入口、筛选与行内操作在移动端仍可达，行为与桌面一致。
- **I3 收起可感知**：筛选收起时，已应用的标签 / 状态通过计数徽标与 `aria-label` 可感知。
- **I4 触达不缩水**：顶栏控件保持 32px；行内 / 批量图标按钮保持 24px 点击区；紧凑来自行数、留白与横向让位。
- **I5 桌面零变更**：`!isMobile` 分支 DOM 与行为不变，既有桌面用例不改断言。
- **I6 标题优先**：移动端行尾操作收进单枚「更多」，把横向空间让给单行省略标题。
- **I7 两列文件夹**：390px 及以上手机宽度可排两列 150px 卡片；更窄屏自动回退单列，不横向溢出。

## Decision

以下小节按需增减；不适用的小节保留标题写「无」。

### 1. 数据模型

无（纯前端布局调整，不落库）。

### 2. 判定算法（唯一入口）

无后端判定。前端唯一口径在 `DocumentsPage` 的 `isMobile` 分支：`activeFilterCount` 由 `tagFilter` / `statusFilter` 两个既有状态派生，筛选行是否渲染只看 `filterOpen`；排序常驻，不计入收起筛选数。

### 3. API 变更清单

无。

### 4. 边界与例外

1. **深链筛选**：`?tag=` / `?status=` 仍按 URL 生效；筛选行默认收起，计数徽标提示已应用项，不自动展开（避免深链重新占第三行）。
2. **无已应用筛选**：`activeFilterCount === 0` 时 Badge 不显示数字（antd 默认行为），「筛选」按钮保持中性样式。
3. **320px 窄屏**：文件夹网格 `minmax(150px, 1fr)` 在两列放不下时回退单列；操作行仍按 32px 控件排布，搜索框 `minWidth: 0` 吸收剩余宽度，不产生横向滚动。
4. **菜单 Portal 事件**：移动端「更多」菜单渲染在 body，但 React 事件沿组件树冒泡到整行；菜单项 `onClick` 必须 `domEvent.stopPropagation()`，否则重命名 / 移动 / 删除会触发文档跳转。
5. **删除确认主题**：移动端确认框使用 `Modal.useModal()` 的 `modal.confirm` + `modalContextHolder`，静态 `Modal.confirm` 读不到 `ConfigProvider` 的动态主题。
6. **长标题**：移动端标题仍走 `.cn-doc-title-ellipsis` 单行省略，完整名保留在 `title` 属性。
7. **平板 / 桌面**：`isMobile` 仅在 `< 768px` 为真，平板沿用桌面分支（C6）。

### 5. 迁移

无。

### 6. 前端

| 层 | 文件 | 改动 |
|---|---|---|
| 页面 | `frontend/src/pages/documents/DocumentsPage.tsx` | ① 新增 `filterOpen`、`activeFilterCount`、`Modal.useModal()`；② 移动端工具栏重排为两行（导航行；排序 + 搜索 + 筛选 + 新建），`gap` 6、`marginBottom` 8、页面内边距 10；③ 筛选行条件渲染（两个 Select 等宽）；④ `renderRowActions`：移动端单枚「更多」下拉 + 二次确认删除，桌面四枚图标原样；⑤ 文件夹卡片网格 `minmax(150px, 1fr)`、内边距 / 字号收紧；⑥ 系列详情操作、批量栏图标化；⑦ 页内分块留白与列表元信息字号收紧 |
| 样式 | `frontend/src/index.css` | 窄屏 `.cn-doc-list` 行内边距 / 头像间距 / 操作区间距再收紧一档（保持 24px 点击区） |
| 页面单测 | `frontend/src/pages/documents/DocumentsPage.test.tsx` | 移动端用例改为：默认两行 + 筛选行不存在；展开后标签 / 状态可见；`?tag=7` 徽标 / `aria-label`；行尾「更多」包含四操作并验证删除确认；文件夹网格 `minmax(150px, 1fr)`；系列操作 `aria-label` |

### 7. 测试清单

**判定层（单测）**：无（无判定算法变更）。

**接口层**：无（无 API 变更）。

**迁移 / 备份**：无。

**前端单测**（`DocumentsPage.test.tsx`）：

- 移动端默认态：工具栏两个直接子块；`doc-toolbar-filters` 不存在；排序 / 搜索 / 筛选 / 新建可见；筛选按钮 `aria-expanded=false`；
- 展开 / 收起：点 `doc-toolbar-filter` 后 `doc-toolbar-filters` 与标签 / 状态控件可见，`aria-expanded=true`；再点后从 DOM 移除；
- 已应用筛选：`?tag=7` 下筛选按钮 `aria-label` 含「已应用 1 项」，展开后标签回显；
- 行尾操作：移动端点 `doc-row-more-2` 后重命名 / 移动 / 置顶 / 删除菜单项存在；删除经确认后发出 `DELETE`；
- 文件夹与系列：移动端 `doc-series-grid` 样式含 `minmax(150px, 1fr)`；系列三枚操作按钮带 `aria-label`；
- 回归：桌面端既有排序切换、标签回显、行内重命名 / 移动 / 置顶、回收站、批量操作用例不改断言通过。

**e2e（前端）**：无（结构收敛不新增端到端流程，可见性由前端单测覆盖）。

### 8. 分期

| 期 | 内容 | 风险 |
|---|---|---|
| **P0 工具栏重排** | 两行结构 + 筛选收起 / 展开 + 计数徽标 + 移动端返回图标化 | 中（既有移动端用例定位需同期改写） |
| **P1 区段留白收窄** | 系列详情卡 `marginBottom`、`.cn-doc-recent` 窄屏规则 | 低 |
| **P2 整页紧凑化** | 操作行收敛（排序常驻、标签 / 状态收起）、文件夹两列卡、行尾「更多」下拉、系列 / 批量图标化、列表元信息收紧 | 中（新增菜单 Portal 事件与移动端删除确认路径） |

## 决策记录（唯一决策台账）

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | 整体方案：三行如何收敛 | **保留两行常驻（导航 + 操作），标签 / 状态改为可展开的第三行；排序保留在操作行** | 导航、搜索、排序是高频操作；标签 / 状态是低频筛选，收起后不损失能力（I1/I2） | ① 继续三行只缩间距（纵向收益有限）；② 把筛选收进「更多」菜单（混杂销毁性操作，筛选是列表高频动作，语义不合）；③ 排序也收进筛选行（需求 0065 要求排序与侧栏偏好常驻可见） | `DocumentsPage.tsx:855-886` |
| D2 | 已应用筛选在收起态的提示 | 计数徽标 + `aria-label`（「筛选（已应用 N 项）」） | 收起后用户仍需知道列表被筛选过；徽标不占纵向空间、`aria-label` 可测可读屏（I3） | 收起态常显当前筛选文本（又占一行）；只靠徽标无文本（读屏不可达） | `DocumentsPage.tsx:870-879` |
| D3 | 移动端返回按钮形态 | 纯图标 + `aria-label="上一级"`，桌面保持文字 | 返回是高频但语义单一动作，图标可省约 40px 给面包屑（C1） | 继续用「上一级」文字（挤压面包屑，且与图标语义重复） | `DocumentsPage.tsx:835-847` |
| D4 | 是否靠缩小控件换紧凑 | **顶栏不缩小**（32px）；行内 / 批量图标按钮维持 24px 点击区 | 触控目标下限；紧凑应来自行数与留白而非压缩可点区（C4/I4） | 顶栏改 `size="small"`（24px，误触率上升）；行内再缩到 20px（低于可点区下限） | `DocumentsPage.tsx` |
| D5 | 桌面端是否同步调整 | **不同步**：`!isMobile` 分支原样 | 桌面横向空间充足，紧凑问题只存在于窄屏；既有桌面用例零改动（C6/I5） | 桌面也收筛选 / 收行操作（无收益且改动面扩大） | `DocumentsPage.tsx` |
| D6 | 是否新增 e2e | 不新增：无端到端流程变化，可见性由前端单测断言 | e2e 无文档列表布局定位用例，单测已覆盖同 DOM 断言 | 为布局断言补 e2e（维护成本高、无增量收益） | `DocumentsPage.test.tsx` |
| D7 | 移动端文件夹区形态 | **两列自适应卡片**（最小 150px），不改成列表行 | 保留系列状态分布的可扫视性；390px 屏两列即把纵向高度减半（C8） | 改成一列列表行（丢失状态分布总览）；固定两列（320px 屏溢出） | `DocumentsPage.tsx:1017-1064` |
| D8 | 移动端行尾操作放哪 | **收进单枚「更多」下拉**，四项能力保留，删除二次确认 | 四枚常驻图标与标题争宽是长文件名省略的根因；一枚图标换约 80px 标题宽度（C9/I6） | 保留四枚只缩间距（横向让位有限）；两枚拆分（仍与标题争宽） | `DocumentsPage.tsx:584-710` |
| D9 | 系列详情 / 批量栏控件形态 | 移动端**图标化 + `aria-label`**，桌面保留文字 | 窄屏把文字按钮折行的高度省回给列表；可访问名不丢失（C10） | 全端图标化（桌面可读性下降）；仅缩字号（仍占宽） | `DocumentsPage.tsx:1114-1175`、`:962-999` |
| D10 | 移动端删除确认实现 | `Modal.useModal()` + `modalContextHolder` | 静态 `Modal.confirm` 不消费 `ConfigProvider` 动态主题（测试亦告警）（C9） | 继续用静态 `Modal.confirm`（主题不一致） | `DocumentsPage.tsx:161-162`、`:681-693` |

门禁：`Proposed` → `Accepted` 前本表不得有「待定」；结论只在本书出现，别处只引用编号。

## Consequences

- **正向**：移动端顶部由三行常驻降为两行；文件夹卡片两列后同屏可见数量翻倍；行尾操作收敛让长标题恢复可读；系列 / 批量栏不再折行；桌面零变更。
- **负向**：使用标签 / 状态筛选多一次点击（先展开面板）；移动端行操作多一次点击（先开菜单）；移动端与桌面工具栏 / 行操作入口形态不一致。
- **风险与缓解**：菜单 Portal 的 React 事件会冒泡到整行 → 菜单项统一 `domEvent.stopPropagation()` 并用单测覆盖删除路径；移动端用例按常显控件定位（卡片 #7）→ 同期改为「先展开再断言」，`make flow` 全绿收口。

被否决的替代方案见「决策记录」对应行，此处不重复。

## 行业对照（可选）

无。

## 与既有 ADR 的关系（可选）

| 轴 | 载体 | 决定 | 由谁 |
|---|---|---|---|
| 窄屏顶部控件收敛 | 文档页「更多」菜单 / 筛选行 | 本 ADR 沿用「次级入口收菜单 / 主操作常驻」口径，进一步把低频筛选收起 | 本轮 CHANGELOG「手机端顶栏与页面首屏控件过多」修复 |
| 排序偏好与侧栏一致 | 需求 0065（卡片 `0065-sidebar-context-aware.md`） | 排序保留在内容区工具栏常驻，与侧栏共享排序偏好 | 需求 0065 第二次修订 |
| 移动端断点与布局分叉 | `useResponsive` 768px | 继续按 `isMobile` 单一分叉，不新增断点 | 既有 `useResponsive` 口径 |

## 落地状态（随实现更新）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 工具栏重排 | 已落地 | `frontend/src/pages/documents/DocumentsPage.tsx` | `frontend/src/pages/documents/DocumentsPage.test.tsx` | e6cd68f2 |
| P1 区段留白收窄 | 已落地 | `frontend/src/pages/documents/DocumentsPage.tsx`、`frontend/src/index.css` | `frontend/src/pages/documents/DocumentsPage.test.tsx` | e6cd68f2 |
| P2 整页紧凑化 | 进行中 | `frontend/src/pages/documents/DocumentsPage.tsx`、`frontend/src/index.css` | `frontend/src/pages/documents/DocumentsPage.test.tsx` | 待回填 |

> 状态只取「未开始 / 进行中 / 已落地」。标「已落地」的期必须有代码落点与测试文件；全期落地后由人确认 `Status` 是否改 `Accepted` / `Implemented`。`make adr-check` 会校验本表与代码、测试、CHANGELOG 的对应关系。

## 交接（会话结束更新）

- 当前阶段：P2 整页紧凑化已实现，前端单测通过，待 `make flow` 全绿与提交
- 已完成：P0 / P1（`e6cd68f2`）；P2 工具栏操作行收敛、文件夹两列卡、行尾「更多」下拉、系列 / 批量图标化、列表元信息收紧
- 下一步：跑 `make flow` → 提交 P2 → 回填本表提交 sha
- 已知坑：菜单是 Portal，React 事件仍沿组件树冒泡到整行，菜单项必须 `domEvent.stopPropagation()`；移动端确认框用 `Modal.useModal()` 而非静态 `Modal.confirm`；`Badge` 在 `count === 0` 时不渲染数字，断言用按钮 `aria-label`
- 最近一次全绿：`make flow` @ P0/P1 实现提交 `e6cd68f2`（2026-10-26）
