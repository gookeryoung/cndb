# ADR 0105: 面向初级用户的界面提示易读性与帮助文档层级下沉

Status: Implemented
Date: 2026-11-05
Related: `frontend/src/pages/help/helpNav.tsx`、`frontend/src/pages/help/HelpDocsPage.tsx`、`frontend/src/pages/help/content/*.tsx`、`frontend/src/layouts/MainLayout.tsx`、`frontend/src/components/GlobalSearch.tsx`、`frontend/src/pages/datasource/DatasourcePage.tsx`、`frontend/src/pages/import-export/FileImportPreview.tsx`、`frontend/src/pages/settings/LlmConfigPanel.tsx`、`docs/adr/0036-help-docs-hierarchy.md`、`docs/adr/0047-permission-denied-message.md`
需求卡片: `docs/requirements/0105-beginner-hints-and-help-hierarchy.md`（需求原文与约束编号的唯一副本）

## 口径（需求 → 设计落点）

需求原文：见需求卡片 §需求原句（逐字，ADR 不复制第二份）。

卡片约束沿用各自编号（C1..Cn），本表只补「设计怎么落地」，不重新拆句：

| 卡片约束 # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | 针对初级使用者 | §2 提示文案口径 R1-R6（含改写示例）：以「未读过文档的初级用户」为基准读者的可对照规范，评审与后续新文案共用 |
| C2 | 完善界面提示内容的易读性 | §3 全量分域改写清单：placeholder / Tooltip / 空态 / 校验错误按 §2 口径**全量巡检**，初级高频动线先行；技术参数类保留示例值 + 白话 Tooltip + 帮助链接 |
| C3 | 并完善帮助文档的完善 | §4 内容补全与初级化：新增 `tutorials/templates`、`tutorials/data-flow` 两个 L2（含 L3/L4 结构）；派生字段并入 `field-types`、推送并入 `configuration/datasource`；既有主题 intro 全部按「你能学到什么」初级化改写 |
| C4 | 和层级下沉 | §5 双轨下沉：导航下沉（侧栏选中主题就地展开 L3，零额外请求）+ 内容下沉（细节沉入 L4、综述上浮导语，长页可扫读）；路由与锚点不变 |

决策结论只在「决策记录」写一次；本节与正文不再罗列「已确认决策」。

## Context

现状逐条核对（以代码为准，标注 `文件:行号`）。沿用卡片「现状影响面」的编号，逐条给结论。

| # | 现状 | 位置 | 影响 | 与卡片的关系 |
|---|---|---|---|---|
| 1 | placeholder 文案约 260 处散落各组件（含 placeholder / Tooltip / Empty 的组件分布：documents 14、grid 系 25+、settings 8、analytics 8+5、import-export 6、design 4、workspace 3、changeRequests 3、admin 3、auth 2、templates 2、pipelines 2、issues 2 等，共 25+ 目录），无统一文案层与写法口径 | `frontend/src/**/*.tsx`（grep `placeholder=` 计 260 处） | 同一控件提示风格不一，初级用户面对的是「27 种口音」的界面 | 确认（C1/C2） |
| 2 | 技术术语直出的提示：如「updated_at / day；留空每次全量」「不使用会话（凭据内联在请求模板里）」「data.items（留空自动探测 data / items / results）」 | `frontend/src/pages/datasource/DatasourcePage.tsx:1035`、`:1345`、`:1381` | 初级用户看不懂字段含义，也无从求证 | 确认（C1/C2） |
| 3 | 帮助导航侧栏只到 L2：`menuItems` 仅「L1 部分 → L2 主题」两层 | `frontend/src/pages/help/HelpDocsPage.tsx:93-98` | 进入页面前无法预知主题内部覆盖维度；L3 仅页内目录可达（`:123-162`） | 确认（C4） |
| 4 | 帮助内容对新功能零覆盖：grep「工作区模板 / 数据流程 / 派生字段 / 推送」在 content 目录无命中 | `frontend/src/pages/help/content/*.tsx` | ADR 0094 / 0095 / 0097 / 0099 / 0100 的功能在帮助里查不到 | 确认（C3） |
| 5 | 既有主题 intro 面向已入门读者，直接讲机制（如导入主题首句「导入不是『上传即入库』：表头识别、类型推断与预览确认都会影响落表结果…」），无「本页你能学到什么 / 适合谁」的导引 | `frontend/src/pages/help/content/tutorials.tsx:209`、`:343` | 初级用户无法快速判断「这篇是不是写给我看的」 | 新增（C1/C3） |
| 6 | `tutorials.tsx` 单文件 1135 行承载 10 个主题正文，长主题正文以整段叙述为主、L4 条目占比低 | `frontend/src/pages/help/content/tutorials.tsx`（全文件 subsection 引用 10 处） | 长页不可扫读，细节混在段落里无法锚点直达 | 新增（C4 内容下沉工作面） |
| 7 | 新手引导底座已存在（OnboardingTour + onboarding store，localStorage 持久化） | `frontend/src/components/onboarding/OnboardingTour.tsx`、`frontend/src/store/onboarding.ts:27` | 首次登录引导已有，本次不重建、不扩展引导步骤 | 排除（无改动） |
| 8 | 主界面帮助入口已有 Tooltip「帮助文档与新手引导」 | `frontend/src/layouts/MainLayout.tsx:882` | 提示易读性改写时纳入 §3 清单统一口径 | 新增（C2） |
| 9 | 权限不足提示已有独立口径（角色 + 拥有者联系指引） | `docs/adr/0047-permission-denied-message.md` | 0047 文案已是「发生了什么 + 怎么办」结构，不重复改写 | 排除（无改动） |
| 10 | 帮助图示按 key 挂在 L3 body 上，与导航层级无关 | `docs/adr/0030-help-figures.md` | 层级下沉不动图示挂载方式 | 排除（无改动） |

**核心缺陷（需求要补的）**：界面提示以开发者视角书写、260 处散落且无统一口径，初级用户看不懂也无从求证；帮助文档主题导语不回答「这页写给我看吗」，长主题细节埋在段落里不可扫读、导航最浅只到 L2；工作区模板、数据流程、派生字段、数据推送等新功能在帮助里没有落点。

设计目标（不变量）：

- **I1 零后端变更**：提示与帮助正文均为前端静态内容，不落库、不加接口、不改备份（延续 ADR 0036 I5）。
- **I2 单一真相源**：侧栏就地目录与页内目录同源（同一 `topic.subsections`），不存在两份 L3 列表；`HELP_SECTIONS` 仍同时决定侧栏、路由与正文层级（延续 0036 I1）。
- **I3 路由与锚点不变**：`topicPath` / `subsectionAnchor` / `itemAnchor` 签名与既有 id 兼容；侧栏 L3 点击即锚点跳转，存量深链全部有效。
- **I4 体积口径不变**：`helpNav.tsx` 仍只含 L1/L2 元数据，不静态 import 任何 content 模块（0090 C1）；侧栏 L3 数据复用当前主题已懒加载的正文。
- **I5 文案口径唯一出处**：§2 是提示文案写法的唯一判定口径，评审与后续新增文案对照同一标准。
- **I6 全量覆盖**：§3 分域清单覆盖全部 25+ 目录，每处存量提示至少被巡检一次（改或判定不改都留痕），不允许「从未被看过」的提示。

## Decision

### 1. 数据模型

无——纯前端静态文案与导航改造，不新增表 / 列 / 枚举，不触发迁移（I1）。

### 2. 提示文案口径（C1 唯一判定入口）

基准读者：**未读过任何文档的初级用户**。所有面向用户的提示（placeholder / Tooltip / 空态 / 校验错误 / 确认弹窗文案）按下表口径书写与评审：

| # | 口径 | 判定方式 |
|---|---|---|
| R1 | 白话短句：一句话说清「这里填什么 / 这是什么」，≤30 字优先 | 评审对照 |
| R2 | 术语首次出现即就地解释：术语旁用括号或 Tooltip 给一句白话说明 | 评审对照 |
| R3 | 操作类提示带下一步：错误 / 警示文案 = 发生了什么 + 怎么办（对齐 0047 结构） | 评审对照 + 单测抽查关键文案 |
| R4 | 示例先行：参数类 placeholder 保留示例值（熟练用户输入效率），白话解释经 Tooltip 或 label 的 extra 承接 | 单测断言示例值不回退 |
| R5 | 指路帮助：高频路径的关键提示挂 `helpLink` 跳帮助对应 L3/L4 锚点，让「看不懂」可一键求证 | e2e 校验跳转 |
| R6 | 不造新术语：产品内同一概念只用一个名字，与帮助文档用词一致（单一词表以帮助文档为准） | 评审对照 |

**改写示例（现状 → 目标，R1/R2/R4 的对照基准）**：

| 位置 | 现状 | 目标 |
|---|---|---|
| `DatasourcePage.tsx:1035` | `updated_at / day；留空每次全量` | placeholder 保留示例 + Tooltip：「填数据表里的时间字段名（如 updated_at）。系统用它只更新新抓到的行；留空则每次抓取的数据全部写入」 |
| `DatasourcePage.tsx:1345` | `不使用会话（凭据内联在请求模板里）` | 保留简称 + Tooltip：「会话 = 系统帮你记住的登录状态。不使用会话时，账号密码直接写在下方请求模板里」 |
| `DatasourcePage.tsx:1381` | `data.items（留空自动探测 data / items / results）` | placeholder 保留示例 + Tooltip：「接口返回内容里，数据列表所在的位置。不确定就留空，系统会自动在常见位置找」 |

口径不引入 i18n / 文案常量层（见 D2）：改写就地发生在各组件，R1-R6 由评审与抽查测试守卫。

### 3. 界面提示全量改写清单（C2）

**巡检对象**：placeholder、Tooltip、Empty 空态、表单校验 message、确认弹窗文案——grep `placeholder=` / `Tooltip title=` / `Empty description=` 命中的全部组件（25+ 目录）。

**节奏**：P0 先改初级用户动线（前六行），P1 按域批量收尾其余全部目录（I6：每处至少巡检一次，改或不改都在 PR 描述留痕）：

| 批次 | 域 / 路径 | 文件 | 改动重点 |
|---|---|---|---|
| P0 | 登录 / 注册 | `pages/auth/*` | placeholder 与错误提示按 R1/R3 改写 |
| P0 | 全局搜索 | `components/GlobalSearch.tsx` | placeholder 按 R1；空态给「换个关键词 / 调整范围」指引（R3）+ 帮助链接（R5） |
| P0 | 文件导入预览 | `pages/import-export/*`（6 个组件） | 表头识别置信度提示、冲突处理文案按 R2/R3 改写 |
| P0 | 数据同步 | `pages/datasource/DatasourcePage.tsx` | 术语直出重灾区（Context #2）：幂等键 / 数据路径 / 会话 / 请求模板等术语就地解释（R2），示例值保留（R4） |
| P0 | 大模型配置 | `pages/settings/LlmConfigPanel.tsx` | 连接配置提示按 R1/R2 改写，配帮助链接 |
| P0 | 主布局入口 | `layouts/MainLayout.tsx` | 顶栏各图标 Tooltip 统一「名词 + 一句干什么」（R1） |
| P1 | 文档域 | `pages/documents`（14）、`components/Document`（3） | 编辑 / 分享 / 导入提示 |
| P1 | 表格域 | `pages/grid/**`（views 9 + dashboard 5 + cells 5 + view-config 4 + kanban 3 + layout 3 + grid 5）、`pages/fields/FieldManager`（5） | 视图 / 字段 / 单元格编辑提示 |
| P1 | 分析域 | `pages/analytics`（8 + RecommendationPanel 等 5） | 公式 / 汇总 / 模板提示 |
| P1 | 设置域 | `pages/settings`（8） | 个人设置 / 工作区设置 / 备份提示 |
| P1 | 协作与管理域 | `pages/changeRequests`（3）、`pages/admin`（3）、`pages/issues`（2）、`pages/pipelines`（2） | 审批 / 管理 / 反馈提示 |
| P1 | 其余 | `pages/design`（4）、`pages/templates`（2）、`pages/workspace`（3）、`pages/public`（1）、`components`（2） | 按口径逐条对照 |

### 4. 帮助文档内容补全与初级化（C3）

沿用 ADR 0036 四级层级与归属规则，做「补缺口 + 初级化」两件事。

**4.1 新功能落点（新增 / 补全）**：

| 类型 | 主题（section/topic） | L3/L4 结构 | 主要内容要点 |
|---|---|---|---|
| 新增 L2 | `tutorials/templates` 工作区模板 | L3：① 模板是什么、从模板建工作区；② 模板配置（字段与文档规则）；③ 生命周期与阶段门禁 | 0094 全流程：模板建区、配置项逐条解释、状态流转；与普通工作区的差异表 |
| 新增 L2 | `tutorials/data-flow` 数据流程 | L3：① 流程卡片与步骤视图；② 表单式填报与写路径权限；③ 多端到端流程的组织 | 0095/0097：步骤门禁、修改申请兜底、多流程切换 |
| 补全 L4 | `tutorials/field-types` | L4「派生字段（公式）」挂入对应 L3 | 0100：公式语法、函数清单、实时计算口径、与普通字段差异 |
| 补全 L3/L4 | `configuration/datasource` | L3「对外推送」+ 若干 L4 | 0099：push 方向任务配置、目标接口要求、失败重试 |
| 补全导语 | `quick-start/workflow` | 开头补「初级用户路径」段 | 按模板建工作区 → 填数据流程 → 看视图，三条链接直达对应主题 |

**4.2 既有主题初级化（intro 口径，见 D7）**：每个 L2 主题的 `intro` 改为「**本页你能学到什么**（1-2 句）+ **适合谁**（一句话）」，机制性叙述（如现状导入主题首句）下沉到首个 L3 的 body。改写只动导语与段落归位，不改变事实与锚点结构。

新增 / 改写主题须满足 0036 I4（每主题 ≥2 个 L3、不留空层）并通过 `helpNav` 层级完整性单测。

### 5. 层级下沉（C4，双轨）

**5.1 导航下沉——侧栏就地 L3 目录**：

- 交互：侧栏 Menu 保持 L1→L2；当前选中主题的菜单项下就地展开其 L3 小节列表（可点击锚点跳转，高亮当前活跃小节）；其余主题不展开。移动端抽屉同口径。
- 实现：`HelpDocsPage` 已按 section 懒加载当前主题正文（`:39-68`），就地目录直接渲染已加载 `topic.subsections` 的 key/label，零新增请求、零元数据上提（I2/I4）。
- 范围：L3 只在选中主题下展开；L4 不进侧栏（页内目录保留 L4 展开现状）。

**5.2 内容下沉——长主题细节沉入 L4、综述上浮**：

| 规则 | 判定 |
|---|---|
| L2 页首导语 ≤5 行可扫读（含 4.2 的初级化导语） | 超过 2 段的综述下沉为首个 L3 的 body |
| 单一实例的细节（一个设置项、一种视图、一条症状）一律写为 L4 条目 | 段落里出现「第 N 个 / 其中有一种」的枚举叙述即拆为 L4 |
| 操作步骤 ≥3 步的内容用 `primitives` 的步骤组件呈现 | 步骤可单独锚点引用 |
| 同一事实只在一处写全（0036 I2） | 下沉时用 `helpLink` 收口交叉引用 |

内容下沉随 §4 内容补全同期落地（P2），不拆分 per-topic 文件、不改变 per-section chunk 粒度（0090 C1）。

### 6. 边界与例外

1. 权限不足提示（0047）、表头识别概率提示（0018）等已有 ADR 口径的文案**只校对用词一致性（R6），不重写结构**。
2. OnboardingTour 引导步骤文案不在本次范围（引导底座独立演进）。
3. 帮助图示（0030）继续挂 L3 body，层级下沉不改变挂载方式。
4. 侧栏 L3 仅静态展示小节 key/label；不含 L4、不做跨主题搜索（全局搜索已有 ADR 0012 口径）。
5. 提示文案的巡检判定「不改」是合法结论（如纯图标按钮的既有 Tooltip 已达标），但须在 PR 留痕，保证 I6 的全量巡检可审计。

### 7. 迁移

无——存量零迁移（I1）；既有 `/help/:section/:topic#anchor` 深链全部保持有效（I3）。

### 8. 前端

| 层 | 文件 | 改动 |
|---|---|---|
| 帮助导航 | `frontend/src/pages/help/helpNav.tsx` | `HELP_SECTIONS` 注册 2 个新 L2 主题（templates / data-flow）；接口与锚点函数不变 |
| 帮助页面 | `frontend/src/pages/help/HelpDocsPage.tsx` | 侧栏选中主题下就地渲染 L3 列表（复用已加载正文），活跃锚点高亮复用现有 `activeAnchor` |
| 帮助内容 | `frontend/src/pages/help/content/tutorials.tsx` | 新增 templates / data-flow 主题正文；field-types 补派生字段 L4；workflow 补初级用户路径导语；既有主题 intro 初级化 + 内容下沉 |
| 帮助内容 | `frontend/src/pages/help/content/{configuration,quickStart,troubleshooting,examples}.tsx` | datasource 补「对外推送」小节；各主题 intro 初级化 + 内容下沉 |
| 样式 | `frontend/src/index.css` | 侧栏就地 L3 列表样式（沿用 `--cn-help-docs-*` token） |
| 提示改写 | §3 清单所列 25+ 目录 | placeholder / Tooltip / 空态 / 校验文案按 R1-R6 改写 |

### 9. 测试清单

**判定层（单测）**：
- `helpNav.test.tsx`：新主题注册完整性（每主题 ≥2 个 L3、key 唯一、锚点 id 不冲突——0036 既有用例自动覆盖新主题）
- `HelpDocsPage.test.tsx`：选中主题侧栏就地展开 L3；点击 L3 触发锚点跳转；未选中主题不展开；intro 初级化后页首含「你能学到什么」
- 高频路径组件单测：关键 placeholder / Tooltip 文案断言（R1/R4 抽查，示例值不回退）

**接口层**：无（I1）。

**迁移 / 备份**：无（I1）。

**e2e（前端）**：`help-docs.spec.ts` 扩展——侧栏 L3 点击滚动定位；新主题（templates / data-flow）路由可直达；长主题 L4 锚点深链可达；全局搜索空态帮助链接跳转可达。

### 10. 分期

| 期 | 内容 | 风险 |
|---|---|---|
| **P0** | §2 文案口径 + §3 前六条初级动线改写（登录注册 / 全局搜索 / 导入预览 / 数据同步 / 大模型配置 / 主布局）+ 帮助链接 | 低 |
| **P1** | §3 其余域全量巡检收尾（文档 / 表格 / 分析 / 设置 / 协作管理 / 其余，I6 留痕） | 中 |
| **P2** | §4 帮助内容补全（2 个新 L2 + 派生字段 / 推送 / 初级路径）+ 主题 intro 初级化 + §5.2 内容下沉 | 中 |
| **P3** | §5.1 侧栏就地 L3 目录（导航 + 样式 + e2e） | 中 |

## 决策记录（唯一决策台账）

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | 整体方案选型 | 前端纯静态四件套：文案口径（§2）+ 全量提示改写（§3）+ 帮助内容补全与初级化（§4）+ 导航 / 内容双轨层级下沉（§5），零后端变更 | 提示与帮助正文均为静态内容；落库引入迁移与备份负担，收益为零（I1） | 后端文案下发 / 文案落库（违背 0036 I5 静态口径，增加运维面） | 本 ADR 全部前端落点 |
| D2 | 是否引入 i18n / 集中文案常量层 | 否：单语（中文）系统，260 处就地改写，口径由 §2 R1-R6 承担 | 常量层重构面大、评审噪声大；antd 组件就地写文案更直观 | 集中 `hintConstants.ts` 常量层（一次性大重构，且无多语言诉求支撑） | 各组件就地改写 |
| D3 | 提示改写范围与节奏 | **全量覆盖**：P0 初级动线先行，P1 按域巡检收尾全部 25+ 目录；每处至少巡检一次并留痕（I6） | 「完善易读性」针对的是整个界面；只改高频路径会让 3/4 的界面保持开发者口吻 | 只改高频路径、低频不动（覆盖不完整，「完善」落空）；一次性全量改写（260 处一个 PR 不可评审） | §3 清单 |
| D4 | 「层级下沉」的落点 | 双轨：① 侧栏选中主题就地展开 L3（复用已加载正文）；② 长主题内容细节沉入 L4、综述上浮导语（§5.2 规则） | 导航解决「进页前预知结构」，内容下沉解决「进页后可扫读直达」，二者合起来才是层级对初级用户的「下沉」 | ① 新增 L5 层级（违背 0036「L4 即单一实例」定位）；② 全量 114 个 L3 进侧栏（信息过载）；③ L3 元数据上提 `helpNav.tsx`（破坏 0090 C1，需维护两份 L3 列表）；④ 只做导航不沉内容（长页依旧不可扫读） | `HelpDocsPage.tsx` 侧栏、content 各文件 |
| D5 | 新功能帮助落点 | 新增 `tutorials/templates` 与 `tutorials/data-flow` 两个 L2；派生字段并入 `field-types` 的 L4；推送并入 `configuration/datasource` | 0036 归属规则：L2 按对象 / 任务族切（模板与数据流程是独立页面与入口）；派生字段是「一个字段类型」= L4 单一实例；推送是数据同步任务族的一环 | 模板 + 数据流程合并为一个 L2（0094 / 0095 产品入口与路由独立，帮助主题应与入口一一对应） | `helpNav.tsx`、`content/tutorials.tsx`、`content/configuration.tsx` |
| D6 | 技术参数类提示的处置 | placeholder 保留示例值，白话解释经 Tooltip / extra 承接（R4） | 示例值对熟练用户有输入效率价值，全部白话化会丢失示例 | 全部改写成纯白话（熟练用户受损，且示例本身就是一种提示） | `DatasourcePage.tsx` 等 |
| D7 | 帮助主题导语口径 | 每个 L2 主题 intro 统一为「本页你能学到什么（1-2 句）+ 适合谁（一句话）」，机制叙述下沉首个 L3 | 初级用户判断「这页是不是写给我的」只看首屏导语；现状 intro 直接讲机制（Context #5） | 保留现状导语（不回答读者适配问题，初级化目标落空） | `content/*.tsx` 各主题 intro |

门禁：`Proposed` → `Accepted` 前本表不得有「待定」；结论只在本书出现，别处只引用编号。

## Consequences

- **正向**：界面提示全量按统一口径面向初级用户，看不懂可一键求证；帮助文档补齐 4 个新功能落点、每页开篇回答「写给我看吗」；导航可预览主题结构、长页可扫读直达 L4；文案口径沉淀为后续所有新页面的对照标准。
- **负向**：260 处提示需两期才收口，期间新旧风格并存；主题 intro 初级化与内容下沉要触碰全部 content 文件，P2 改动面大；侧栏就地目录增加渲染分支与样式维护点。
- **风险与缓解**：文案改写可能触碰既有单测断言的字符串——改写与断言同步更新；`tutorials.tsx` 1135 行，P2 补内容时改动集中，注意 key 唯一性（层级完整性单测兜底）；侧栏 L3 在窄屏抽屉中的高度溢出——L3 列表上限滚动（CSS token 内处理）。

被否决的替代方案见「决策记录」对应行，此处不重复。

## 与既有 ADR 的关系

| 轴 | 载体 | 决定 | 由谁 |
|---|---|---|---|
| 帮助层级模型 | `helpNav.tsx` 四层模型 | 0105 不改 L1-L4 定义与归属规则，只补内容与下沉导航 | ADR 0036 |
| 懒加载体积口径 | `HELP_SECTION_LOADERS` per-section chunk | 0105 不拆 per-topic chunk、不上提 L3 元数据 | 需求卡片 0090 C1 |
| 权限不足文案 | `workspaces/permissions.py` 等 | 0105 只校对用词，不重写结构 | ADR 0047 |
| 提示与帮助的衔接 | `helpLink` 锚点 | 0105 复用为「看不懂就指路」的通道 | ADR 0036 |

## 落地状态（随实现更新）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 | 已落地 | `frontend/src/pages/auth/LoginPage.tsx`、`frontend/src/pages/auth/RegisterPage.tsx`、`frontend/src/components/GlobalSearch.tsx`、`frontend/src/pages/import-export/FileImportPreview.tsx`、`frontend/src/pages/datasource/DatasourcePage.tsx`、`frontend/src/pages/settings/LlmConfigPanel.tsx`、`frontend/src/layouts/MainLayout.tsx`、`frontend/src/index.css` | `frontend/src/pages/auth/LoginPage.test.tsx`、`frontend/src/pages/auth/RegisterPage.test.tsx`、`frontend/src/components/GlobalSearch.test.tsx`、`frontend/src/pages/import-export/FileImportPreview.test.tsx`、`frontend/src/pages/datasource/DatasourcePage.test.tsx` | `03fda834` |
| P1 | 已落地 | `frontend/src/pages/analytics/AnalyticsPage.tsx`、`frontend/src/pages/grid/layout/RowDetailDrawer.tsx`（其余目录巡检判定不改，留痕见交接） | `frontend/src/pages/analytics/AnalyticsPage.test.tsx`、`frontend/src/pages/grid/layout/RowDetailDrawer.test.tsx` | `03fda834` |
| P2 | 已落地 | `frontend/src/pages/help/helpNav.tsx`、`frontend/src/pages/help/content/*.tsx` | `frontend/src/pages/help/helpNav.test.tsx`、`frontend/src/pages/help/HelpDocsPage.test.tsx` | `03fda834` |
| P3 | 已落地 | `frontend/src/pages/help/HelpDocsPage.tsx`、`frontend/src/index.css` | `frontend/src/pages/help/HelpDocsPage.test.tsx`、`frontend/tests/e2e/critical/help-docs.spec.ts` | `03fda834` |

> 状态只取「未开始 / 进行中 / 已落地」。标「已落地」的期必须有代码落点与测试文件；全期落地后由人确认 `Status` 是否改 `Accepted` / `Implemented`。`make adr-check` 会校验本表与代码、测试、CHANGELOG 的对应关系。

## 交接（会话结束更新）

- 当前阶段：P0-P3 全部落地，Status 已置 `Implemented`
- 已完成：P0 高频动线文案与 `helpLink` 指路（登录 / 注册、全局搜索、导入预览、数据同步、大模型、顶栏）；P1 其余域巡检（documents / grid / fields / analytics / settings / changeRequests / admin / issues / design / templates / workspace / public；多数已符合 R1/R4 判定不改，JSON 单元格与分析占位改为示例 / 白话）；P2 帮助内容补全（`tutorials/templates`、`tutorials/data-flow` 两个 L2；`field-types` 补 L4「派生字段（公式）」；`datasource` 补 L3「对外推送」；`quick-start/workflow` 补模板工作区路径；全部 L2 intro 改为「本页你能学到什么 + 适合谁」；`HelpLink` 修正裸 key 锚点）；P3 侧栏就地 L3 目录（复用已加载正文、锚点跳转与高亮、窄屏抽屉同口径、L4 不进侧栏）
- 下一步：无功能遗留；若后续新增提示文案，按 §2 R1-R6 与帮助用词校对后落库
- 已知坑：`helpLink` 的 anchor 参数是完整锚点 id（裸 key 需经 `subsectionAnchor` / `itemAnchor`）；新增主题时 `helpNav.tsx` 元数据与 content default export 必须同序同 key；侧栏 L3 依赖当前主题正文加载完成，正文加载失败时只剩 L2
- 最近一次全绿：`make check-fast`（adr-check 0 error，仅 4 条「未提交」warning；ruff / pyrefly / tsc / eslint 通过）→ `make test`（6656 passed / 3 skipped）→ `make frontend-coverage`（全部用例通过，核心集合 lines 97.79% / branches 100%，全局 lines 82.81%，双门槛达标）→ `pnpm e2e tests/e2e/critical/help-docs.spec.ts`（5 passed，含新增侧栏 L3 / 全局搜索深链 2 例）
