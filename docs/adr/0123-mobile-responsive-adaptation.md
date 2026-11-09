# ADR 0123: 全站移动端显示适配专项（响应式优先）

Status: Accepted（2026-11-08 人工评审通过）
Date: 2026-11-08
Related: `frontend/src/index.css`、`frontend/src/hooks/useResponsive.ts`、`frontend/src/layouts/MainLayout.tsx`、`frontend/src/pages/**`、ADR 0044（文档页移动端紧凑化范式）、ADR 0026（Chrome 81 兼容基线）
需求卡片: `docs/requirements/0123-mobile-responsive-adaptation.md`（需求原文与约束编号的唯一副本）

> 需求变更时**先改本 ADR 再改代码**：删去失效的口径行 / 现状条目 / 决策 D 行 / 测试与分期，不留「历史方案」「以后备用」段落；整节不适用写「无」。ADR 被新方案替代或需求作废时**直接删除本文件**，同步删除 `docs/adr/README.md` 索引行与代码 / 文档中的引用（git 历史可追溯），不在仓库保留 `Superseded` / `Deprecated` 文档；编号不复用。

## 口径（需求 → 设计落点）

需求原文：见需求卡片 §需求原句（逐字，ADR 不复制第二份）。

卡片约束沿用各自编号（C1..Cn），本表只补「设计怎么落地」，不重新拆句：

| 卡片约束 # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | 核心页面在 <768px 视口可用 | 以 375px 为基准视口逐页走查：无横向溢出（`overflow-x` 不出现滚动条）、关键信息可读、触控目标沿 0044 I4 口径（顶栏 32px / 行内图标 24px） |
| C2 | 工作区列表名称不可见 | 已随 S0 热修复落地（2026-11-08）：移动端收起态不渲染模块徽标（`WorkspaceList.tsx` `!isMobile` 分支）+ `index.css` 窄屏规则让 `.cn-ws-row-name` 占满剩余宽度（`flex: 1 1 auto; min-width: 0`） |
| C3 | 响应式优先 | 不新建移动端路由 / 页面组件；全部适配在既有组件内按断点分叉 |
| C4 | 网格页横向滚动 + 首列冻结 | 复用既有实现：`GridPage.tsx` 移动端 `pinFirstColumn: isMobile`（`buildColumns.tsx:376` 首个数据列 `fixed=left`）+ `gridTableSection.tsx` `mobileLayout`（关虚拟滚动、行选择列 fixed）；P2 只做走查补漏（视图栏 / 工具栏 / 行详情 Drawer 宽度），不重构 |
| C5 | 能力不减、桌面零回归 | 次级入口收「更多」菜单 / 收起面板（0044 范式）；桌面分支 DOM 与行为不变，既有桌面用例断言不改 |
| C6 | 断点沿用 768 / 1024 / 1280 | `useResponsive.ts` 不动；`index.css` 媒体查询断点统一 `767.98px`（与 antd 口径一致，现状既有写法） |
| C7 | CSS 承样式、JS 承结构 | 新增移动适配一律：纯样式差异（间距 / 字号 / 显隐 / flex 占比）进 `index.css` `@media` 层（按组件前缀就近分节）；`useResponsive` 分支仅用于「渲染不同组件 / 布局结构」（如两行工具栏 vs 单行、列表 vs 菜单收敛）。存量 JS 内联样式迁移随各页走查顺带做，不专项重写 |
| C8 | 复杂交互只读兜底 | 设计编辑器（3D CSG 预览 / DSL 编辑）移动端不承诺编辑：P3 走查若不可用则收敛为提示 + 引导桌面（不新建只读页） |
| C9 | 移动端测试门禁 | 触及页面补 375px 视口单测（`WorkspaceList.test.tsx` 的 `setViewportWidth` 范式）；e2e 新增 `critical/mobile-viewport.spec.ts`（登录 → 工作区列表名称可见 → 进入工作区），`projects` 配置加移动视口 |

决策结论只在「决策记录」写一次；本节与正文不再罗列「已确认决策」。

## Context

现状逐条核对（以代码为准，标注 `文件:行号`）。沿用需求卡片「现状影响面」的编号，逐条给结论：

| # | 现状 | 位置 | 影响 | 与卡片的关系 |
|---|---|---|---|---|
| 1 | 工作区列表行内 3-4 个文字徽标不可收缩（flex 项 min-width:auto），名称设 `overflow:hidden` 可收缩到 0，375px 下名称被挤压为完全不可见 | `frontend/src/pages/workspace/WorkspaceList.tsx:543-548`、`frontend/src/index.css:1334-1341` | 用户报告的直接痛点 | 确认（C2，已随 S0 修复） |
| 2 | CSS `@media` 全 `src/` 仅 6 处；33 个页面文件用 `useResponsive`，移动适配大量以内联样式 `isMobile ? … : …` 散在 JSX | `frontend/src/index.css`、各页面 | 口径分裂、难审计；样式型差异本可不进 JS | 确认（C7 主缺口） |
| 3 | 全局壳层已有移动端基础：汉堡抽屉导航、移动搜索 Drawer、页签移动端简化、顶栏品牌/用户区收窄 | `frontend/src/layouts/MainLayout.tsx:144`、`:410`、`:1047-1080` | 壳层不是缺口主体 | 排除（P1 仅走查收尾） |
| 4 | 文档列表页已按 ADR 0044 完成移动端紧凑化（两行工具栏 / 筛选收起 / 两列文件夹卡 / 行操作收「更多」） | `frontend/src/pages/documents/DocumentsPage.tsx` | 既有范式可直接复用 | 排除（不重做；编辑态走查归 P2） |
| 5 | 网格页移动端基础已存在：首列冻结、行选择列 fixed、移动关虚拟滚动 | `frontend/src/pages/grid/GridPage.tsx:1142`、`:1282`、`frontend/src/pages/grid/cells/buildColumns.tsx:376`、`frontend/src/pages/grid/gridTableSection.tsx:219-224` | C4 主体已落地 | 部分确认（P2 只补视图栏 / 工具栏 / Drawer 走查） |
| 6 | Modal 移动宽度部分已 `calc(100vw - 32px)`（新建 / 导入工作区），但全仓未规约 | `frontend/src/pages/workspace/WorkspaceList.tsx:356`、`:878` | 各弹窗宽窄不一 | 确认（P1 规约） |
| 7 | 设计编辑器为桌面双栏 + 3D 视口（three.js + Web Worker CSG），移动端未验证 | `frontend/src/pages/design/DesignEditorPage.tsx` | 移动端大概率不可用 | 确认（C8 兜底） |
| 8 | 模板结构化编辑器（ADR 0121）未实施，已随功能移除 | — | 不再实施 | 移除 |
| 9 | admin 管理台页面移动端未适配 | `frontend/src/pages/admin/` | 低频页，可后置 | 确认（P3） |
| 10 | e2e 无移动视口用例 | `frontend/tests/e2e/` | 移动回归无门禁 | 确认（C9） |
| 11 | Chrome 81 兼容基线（ADR 0026）要求生产构建在旧内核可用；本专项新增 CSS（媒体查询 / flex）均为 0026 白名单内基础特性 | `frontend/src/compat/`、`.browserslistrc` | 移动适配不引入新语法缺口 | 排除（复用既有基线） |

**核心缺陷（需求要补的）**：移动端适配没有统一实现口径（CSS 媒体查询 vs JS 分支 vs 内联样式各写各的），也没有统一验收门禁（无移动视口测试）；个别页面（工作区列表）已出现「关键信息被不可收缩元素挤压为 0」的可用性故障。

设计目标（不变量）：

- **I1 名称优先**：任何「名称 / 标题 + 徽标」行内布局，窄屏下名称占满剩余宽度（`flex: 1 1 auto; min-width: 0` + 省略号），徽标可收纳（隐藏 / 进详情），名称不被挤压为 0。
- **I2 能力不减**：移动端功能入口与桌面等价（形态可收敛：菜单 / 收起面板 / 抽屉）。
- **I3 桌面零回归**：`!isMobile` 分支与 ≥768px 样式不变，既有桌面用例断言不改。
- **I4 触控不缩水**：紧凑来自行数 / 留白 / 横向让位，不来自缩小可点区（顶栏 32px / 行内图标 24px，沿 0044 I4）。
- **I5 无横向溢出**：375px 视口下页面不出现横向滚动（网格表格区按 C4 例外，横向滚动是预期形态）。
- **I6 口径唯一**：新代码样式型适配只进 CSS 媒体查询层、结构性切换只用 `useResponsive`，评审按此拦截（C7）。

## Decision

### 1. 数据模型

无（纯前端布局与测试，不落库）。

### 2. 判定算法（唯一入口）

无后端判定。前端唯一断点口径在 `frontend/src/hooks/useResponsive.ts`（<768 mobile）；CSS 侧统一 `@media (max-width: 767.98px)`。

### 3. API 变更清单

无。

### 4. 边界与例外

1. **网格表格区横向滚动**：C4 预期形态，I5 的例外只针对表格容器本体；表格外的页面结构（视图栏 / 工具栏 / 分页）仍不得横向溢出。
2. **触屏拖拽排序**：工作区列表 `@dnd-kit` PointerSensor 在触屏可用（把手 `touch-action: none`），保持现状；若走查发现与页面滚动冲突，P1 收敛为移动端隐藏把手。
3. **平板 768-1024px**：沿用桌面分支（0044 C6 同口径），本专项不新增平板专属形态。
4. **超窄屏 <360px**：不单独适配，验收基准 375px；不因超窄屏引入额外分支。
5. **Chrome 81**：新增样式限于既有白名单特性（媒体查询 / flex / overflow），不引入新 CSS 语法。

### 5. 迁移

无。

### 6. 前端

| 层 | 文件 | 改动 |
|---|---|---|
| 样式底座 | `frontend/src/index.css` | P1：新增「移动端适配统一分节」（按组件前缀就近挂 `@media (max-width: 767.98px)`），把 Modal 宽度等公共规约收敛为类（如 `.cn-modal-mobile` 或 antd Modal `width` 统一口径） |
| 页面 | `frontend/src/pages/**`（P2/P3 逐页走查清单） | 网格页视图栏 / 工具栏 / RowDetailDrawer；文档编辑页编辑态；admin 页；设计页兜底提示 |
| 测试基建 | `frontend/src/pages/workspace/WorkspaceList.test.tsx`（范式）、`frontend/tests/e2e/critical/mobile-viewport.spec.ts`（新增） | 375px 视口单测范式推广；移动视口 e2e 冒烟 |
| e2e 配置 | `frontend/tests/e2e/`（playwright projects） | 增加移动视口 project（375×812，仅 critical 冒烟用例挂载） |

### 7. 测试清单

**判定层（单测）**：无（无判定算法变更）。

**接口层**：无（无 API 变更）。

**迁移 / 备份**：无。

**前端单测**：

- 工作区列表：已落地（`WorkspaceList.test.tsx` 移动端徽标 / 名称可见性 + 桌面回归，随 S0）；
- P1：Modal 宽度规约用例（统一宽度类 / 口径断言）；
- P2：网格页移动端（首列冻结既有用例保持 + 视图栏 / 工具栏走查用例）、文档编辑页移动端用例；
- P3：设计页移动端兜底提示用例、admin 页走查用例。

**e2e（前端）**：`critical/mobile-viewport.spec.ts` —— 移动视口下登录 → 工作区列表名称可见 → 进入工作区落地页（C9）。

### 8. 分期

| 期 | 内容 | 风险 |
|---|---|---|
| **P0 首屏痛点** | 工作区列表行内名称修复（已随 S0 热修复落地，2026-11-08）+ 同类「徽标挤占名称」模式扫描（MyViewsPanel / TablesList 等，只修同构问题） | 低 |
| **P1 适配底座** | `index.css` 移动端统一分节 + Modal/Drawer 移动宽度规约 + MainLayout 壳层走查收尾 | 中（存量内联样式迁移以「顺带」为界，防摊大饼） |
| **P2 高频页走查** | 网格页（视图栏 / 工具栏 / 行详情，复用既有 pinFirstColumn 基础）、文档编辑页编辑态 | 中 |
| **P3 低频页与门禁** | admin 走查、设计页移动端只读兜底、移动视口 e2e 冒烟进 critical | 低 |

## 决策记录（唯一决策台账）

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | 整体方案：响应式 vs 独立移动端 | **响应式优先**：一套代码 + 断点分叉 | 与现状（useResponsive / 0044）连续，成本最低；用户 2026-11-08 确认 | 独立移动端路由 / 页面（工作量翻倍，与 33 处既有接入冲突） | 各页面组件内分支 |
| D2 | 适配实现口径 | **CSS 承样式、JS 承结构**（C7/I6）：纯样式差异进 `index.css` `@media`，`useResponsive` 只做结构性切换 | 内联样式散置是现状口径分裂根源；CSS 层可整体审计、与 antd 断点一致 | 全部继续走 JS 分支（不可审计）；一次性把存量内联全量迁 CSS（改动面失控，改为走查顺带迁移） | `index.css`、各页面 |
| D3 | 网格页移动端形态 | **横向滚动 + 首列冻结**，复用既有 `pinFirstColumn` / `mobileLayout` 实现 | 保真（列语义 / 排序 / 列宽不丢）；主体已落地，增量最小；用户确认 | 卡片式行布局（实现量大，列语义需重设计）；P2 再议（本期不做） | `GridPage.tsx:1142`、`gridTableSection.tsx` |
| D4 | 设计 3D 编辑器移动端 | **只读兜底**：不可用则提示 + 引导桌面，不做移动编辑 | three.js + Worker CSG 在移动端成本高、需求未证实 | 移动端 3D 编辑（成本 / 收益不成比例） | `DesignEditorPage.tsx`（P3） |
| D5 | 移动端测试门禁 | 页面单测（375px 范式）+ **移动视口 e2e 冒烟进 critical**（登录 → 列表 → 进入工作区） | 布局回归单测可断言 DOM；关键链路靠 e2e 兜底；两条都不贵 | 全量 e2e 双视口跑（时长翻倍，收益递减） | `mobile-viewport.spec.ts` |
| D6 | 「徽标挤占名称」通例 | 名称占满剩余宽度（`flex: 1 1 auto; min-width: 0`）+ 徽标收纳（隐藏 / 进详情 / 收菜单），不靠徽标缩小字号 | I1；工作区列表根因的通用化 | 缩小徽标字号（低于 10px 不可读）；名称折行（行高不稳） | `index.css` 窄屏层 + 各页 |
| D7 | Modal / Drawer 移动宽度 | 统一 `calc(100vw - 32px)` 口径（与现状已有写法一致），P1 收敛为公共类 / 统一口径 | 现状各页自发写法已验证可用 | Drawer 全屏化（部分场景遮挡上下文） | `index.css`、各 Modal 调用点 |
| D8 | 桌面回归保障 | 桌面分支与用例断言**零改动**（I3），移动端新增用例与桌面用例分 describe 并存 | C5；既有 34 个 WorkspaceList 用例等资产不重写 | 桌面 / 移动共用断言（互相污染视口状态） | 各 `*.test.tsx` |

门禁：`Proposed` → `Accepted` 前本表不得有「待定」；结论只在本书出现，别处只引用编号。

## Consequences

- **正向**：移动端可用性有统一口径与门禁（I1/I5/C9）；「名称被挤没」类故障有通例可依；桌面零风险。
- **负向**：P2 前各页移动体验仍参差（分期消化）；C7 口径对存量代码是「新代码从严、存量顺带迁移」，短期两种写法并存。
- **风险与缓解**：存量内联样式迁移易摊大饼 → D2 明确以「走查顺带」为界；移动 e2e 增加流水线时长 → 仅一条冒烟链路挂移动 project。

被否决的替代方案见「决策记录」对应行，此处不重复。

## 行业对照（可选）

无。

## 与既有 ADR 的关系（可选）

| 轴 | 载体 | 决定 | 由谁 |
|---|---|---|---|
| 移动端紧凑化范式（两行工具栏 / 收菜单 / 触控不缩水） | 文档页 | 本 ADR 复用其 I2/I4 口径并推广为全站不变量 | ADR 0044 |
| CSS 兼容白名单 | `frontend/src/compat/`、ThemeProvider 运行时样式审计 | 移动端新增样式限于既有白名单基础特性，不新增兼容缺口 | ADR 0026 |
| 断点与设备判定 | `useResponsive.ts` 768/1024/1280 | 原样沿用，不新增断点 | 既有口径 |

## 落地状态（随实现更新）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 首屏痛点 | 已落地 | `frontend/src/pages/workspace/WorkspaceList.tsx`、`frontend/src/index.css`（工作区列表行内名称修复，S0 热修复先行；同类扫描结论见 P1） | `frontend/src/pages/workspace/WorkspaceList.test.tsx` | 876820d2 |
| P1 适配底座 | 已落地 | `frontend/src/index.css`、`frontend/src/pages/workspace/WorkspaceList.tsx`、`frontend/src/pages/documents/ChartDesignerModal.tsx`、`frontend/src/layouts/MainLayout.tsx`（明细见「交接」） | `frontend/src/mobileCaliber.test.ts`、`frontend/src/pages/workspace/WorkspaceList.test.tsx`、`frontend/src/layouts/MainLayout.test.tsx`、`frontend/src/pages/documents/ChartDesignerModal.test.tsx` | 876820d2 |
| P2 高频页走查 | 未开始 | — | — | — |
| P3 低频页与门禁 | 未开始 | — | — | — |

> 状态只取「未开始 / 进行中 / 已落地」。标「已落地」的期必须有代码落点与测试文件；全期落地后由人确认 `Status` 是否改 `Accepted` / `Implemented`。`make adr-check` 会校验本表与代码、测试、CHANGELOG 的对应关系。

## 交接（会话结束更新）

- 当前阶段：P0-P1 已落地并提交（876820d2，2026-11-08），待进入 P2（高频页走查）
- 已完成：S0 热修复（P0）与 P1 全部四项——①「移动端全局适配」分节统一 D7 口径（Modal / 左右抽屉 `calc(100vw - 32px)` 上限，顶部抽屉豁免，修正原 `92vw` 全局上限误伤顶部抽屉）；② `WorkspaceList` 两处 Modal + `ChartDesignerModal` 内联宽度迁入统一口径；③ MainLayout 顶栏 `padding`/`gap` 内联 `isMobile` 分叉迁入 CSS（C7），壳层走查无功能缺口（汉堡抽屉 / 移动搜索 / 页签简化 / 菜单收纳均完备）；④ 同类「徽标挤占名称」扫描：MyViewsPanel / TablesList 窄屏卡片 / 全局搜索项 / 用户卡片均合规，唯一缺口 `.cn-ws-detail-table-name` 已补 `min-width: 0`
- 下一步：P2 高频页走查（网格页视图栏 / 工具栏 / RowDetailDrawer + 文档编辑页编辑态），复用 `mobileCaliber.test.ts` 口径契约范式补页面级 375px 用例
- 已知坑：jsdom 不加载样式表，弹窗移动宽度无法在组件测试里断言计算样式，靠 `mobileCaliber.test.ts` 直读 index.css 文本守卫（同 `headerBorders.test.ts` 范式）；P0+P1 已提交（876820d2）
- 最近一次全绿：`make check-fast` + 前端全量 vitest（264 文件 / 3202 例）@ 876820d2（2026-11-08）
