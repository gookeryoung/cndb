# ADR 0109: 【设计】「设计结构」根页左右分栏（左产品列表 / 右结构树）

Status: Implemented
Date: 2026-11-06
Related: `frontend/src/pages/design/DesignsPage.tsx`、`frontend/src/pages/design/DesignStructureNav.tsx`、`frontend/src/pages/design/designOutline.ts`、`frontend/src/layouts/MainLayout.tsx`、`frontend/src/index.css`、`frontend/src/pages/help/content/*`、`docs/adr/0083-design-structure-subnav-and-assembly-tree.md`、`docs/adr/0084-design-sidebar-assembly-and-system-level.md`、`docs/adr/0103-design-editor-layout-optimization.md`
需求卡片: `docs/requirements/0109-design-structure-left-right-layout.md`（需求原文与约束编号的唯一副本）

## 口径（需求 → 设计落点）

需求原文：见需求卡片 §需求原句（逐字，ADR 不复制第二份）。

卡片约束沿用各自编号（C1..Cn），本表只补「设计怎么落地」，不重新拆句：

| 卡片约束 # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | 「参考数据表质量检查、修改申请的设计风格」 | `DesignsPage` 根容器改为 `cn-page cn-qc-page` + `cn-page-head` 紧凑页头（`ApartmentOutlined` 图标、标题「设计结构」、副标题「左侧产品列表、右侧选中产品的结构树」）；类型筛选 `Segmented` 与「新建设计」主按钮上移页头；弃用 `maxWidth: 960` 居中单栏与 `.cn-design-structure` / `.cn-design-folder*` 旧类，复用质量检查页原语（D1） |
| C2 | 「采取左右布局设计」 | 主区改为 `cn-qc-split` 双栏（窄屏既有断点收为纵向堆叠）：左 `SectionBox`「产品列表」（extra「共 N 个」），右 `SectionBox`「结构树」（标题带选中产品名，未选中为「结构树」）（D1） |
| C3 | 「左侧为产品列表」 | 左栏 = 设计清单可选列表（`role=listbox/option`、`cn-qc-row--selectable/--active`）：行内名称 + 零件 / 装配 Tag + 目录 Tag + 「依赖陈旧」Tag + `v{version_count}` + 更新时间；扁平列表（0103 D12 目录分组退役为行内 Tag）；点击选中 / 再点取消；行尾 hover 动作保留 打开 / 编辑 / 删除（D2） |
| C4 | 「右侧为具体结构树」 | 右栏展示选中产品的装配树：复用 `designOutline.ts` 映射与 `GET /designs/{id}/outline`（懒加载 + IR 快照缓存优先，与侧栏同口径）；树层级 系统 → 组件 → 分组 → 零件；默认选中最近更新的设计（0107 口径），选中项被删除 / 被筛掉时自动回落到列表首个；未选中空态「选择左侧产品查看结构树」，清单为空空态「还没有结构设计」（D3 / D6） |
| C5 | （布局重构不减能力） | 节点点击与侧栏口径一致：设计根 / 大纲节点 → `designEditorPath`（大纲节点带 `?line=` 定位源行）；新建 / 改名 / 描述 / 删除 Modal 与模板内容原样保留；viewer 只读门控保留（D5） |
| C6 | （配套回归） | 根页不再渲染模块侧栏（`siderMode='design'` 收窄为 `/design/:id` 编辑器页，0103 C1 双向定位闭环不动）；样式新增类全部走 `--cn-*` token；ADR 0084 D4 / D5、ADR 0103 D12 失效行随实现改写引用本 ADR；单测 / e2e / 帮助文案 / CHANGELOG 同步（D4） |

决策结论只在「决策记录」写一次；本节与正文不再罗列「已确认决策」。

## Context

现状逐条核对（以代码为准，标注 `文件:行号`）。沿用卡片「现状影响面」的编号，逐条给结论；ADR 新发现的条目追加编号。

| # | 现状 | 位置 | 影响 | 与卡片的关系 |
|---|---|---|---|---|
| 1 | 设计管理页为居中单栏（`maxWidth: 960`）+ 目录分组（`cn-design-folder`）+ 类型 `Segmented` 在内容区头部 | `frontend/src/pages/design/DesignsPage.tsx:258-315` | 与质量检查 / 修改申请的双栏语言不一致；结构浏览必须进编辑器或依赖窄侧栏 | 确认：C1 / C2 / C3 改造对象 |
| 2 | 质量检查 / 修改申请双栏范式已成型：`cn-page` 紧凑页头 + `cn-qc-split` + `SectionBox` flush 列表 + `cn-qc-row` 行态 + 窄屏断点堆叠 | `frontend/src/pages/pipelines/PipelinesPage.tsx:319-534`、`frontend/src/pages/changeRequests/ChangeRequestsPage.tsx:676-765`、`frontend/src/index.css` | 原语齐备，直接复用，无需新布局组件 | 确认：C1 / C2 复用面 |
| 3 | 修改申请工作区级已有「左清单可选列表 + 右选中项详情」先例（含默认选中与失效回落） | `frontend/src/pages/changeRequests/ChangeRequestsPage.tsx:259-386` | 左栏选中态 / 默认选中 / 回落口径可直接对齐 | 确认：C3 / C4 复用先例（需求 0107） |
| 4 | 大纲端点、懒加载协议与 `?line=` 定位交互已就绪（快照优先 / v1-v2 派生只读不落库） | `src/cndb/plugins/design/routers.py`、`frontend/src/pages/design/designOutline.ts`、ADR 0083 D4 / D7 | 右栏树零新增端点、零新交互协议 | 确认：C4 / C5 复用 |
| 5 | 模块侧栏在整个设计上下文（含 `/design` 根页）渲染装配树 | `frontend/src/layouts/MainLayout.tsx:448-456`（`siderMode`）、`:759-769`（`renderDesignNav`） | 根页右栏树与侧栏树将构成双树冗余 | 新增：C6 改造点（侧栏收窄） |
| 6 | 编辑器的树 ↔ 代码双向定位闭环依赖侧栏（`?line=` 反选 + `scrollTo` + 选中态） | `frontend/src/pages/design/DesignStructureNav.tsx:90-94`、`:150-166`；ADR 0103 C1 | 侧栏不能全移除，否则破坏已落地的编辑器能力 | 约束：D4 取舍依据 |
| 7 | 侧栏懒加载含 IR 快照缓存优先（键与编辑器 `useQuery` 一致，避免重复请求 outline） | `frontend/src/pages/design/DesignStructureNav.tsx:110-129` | 右栏采用同口径，主区与编辑器共享缓存 | 确认：C4 数据流 |
| 8 | viewer 门控：`isViewer` 隐藏新建 / 编辑 / 删除入口 | `frontend/src/pages/design/DesignsPage.tsx:107-112`、`:207-229` | 重构后必须原样保留 | 确认：C5 |
| 9 | 既有 e2e 断言侧栏树与主区管理页形态 | `frontend/tests/e2e/critical/design-structure-tree.spec.ts`、`design-sidebar-assembly.spec.ts` | 布局切换后断言需同步改写 | 确认：C6 回归面 |
| 10 | ADR 0084 D4 / D5 定「侧栏 = 装配树、主区 = 管理列表」；ADR 0103 D12 定「管理页 folder 分组 + kind 筛选」 | `docs/adr/0084-*.md`、`docs/adr/0103-*.md` | 本需求改变主区形态，两处失效行需随实现清理 | 确认：C6 清理对象 |

**核心缺陷（需求要补的）**：主区居中单栏把「产品清单」与「装配结构」割裂——不进编辑器就无法以页面形态浏览某个产品的装配层级，且模块页与质量检查 / 修改申请已定型的左右分栏语言不一致。

设计目标（不变量）：

- **I1 零契约变更**：零新端点、零 IR / DSL 变更、零迁移、零后端改动。
- **I2 能力不减少**：新建 / 改名 / 描述 / 删除、viewer 门控、懒加载、`?line=` 定位、编辑器双向定位闭环全部保留。
- **I3 原语复用**：布局只使用 `cn-page` / `cn-page-head` / `cn-qc-split` / `SectionBox` / `cn-qc-row` 既有原语与 `--cn-*` token；断点只用既有 `1023.98px` / `767.98px`。

## Decision

### 1. 数据模型

无。

### 2. 判定算法（唯一入口）

无（纯前端布局重构）。右栏树数据流唯一入口仍为 `GET /designs/{id}/outline` + `designOutline.ts` 映射（ADR 0083 D4），本 ADR 不新增解析或派生路径。

### 3. API 变更清单

| 端点 | 变更 |
|---|---|
| `GET /api/v1/workspaces/{wid}/designs/{id}/outline` | 无变更（右栏直接复用；懒加载与 IR 快照缓存优先口径与侧栏一致） |
| 其余设计端点 | 无变更 |

### 4. 边界与例外

1. 清单为空（工作区无设计）：左栏空态「还没有结构设计」，右栏同空态；「新建设计」仍可用（非 viewer）。
2. 类型筛选后左栏为空：右栏回落为未选中空态「选择左侧产品查看结构树」。
3. 选中项被删除 / 被筛选隐藏：自动回落到当前可见列表首个；列表为空则清空选中。
4. viewer：无新建 / 编辑 / 删除入口，浏览与定位能力完整（沿用 ADR 0083 D8 只读口径）。
5. 大纲加载失败（网络 / 400 编译诊断）：右栏该产品树给「结构加载失败」提示行，可重试；不阻塞左栏。
6. 历史 v1 / v2 快照：沿用 ADR 0083 D5 派生口径（`source: "content"`，只读不落库），右栏标注「历史快照派生」Tag（与侧栏同文案）。
7. 窄屏（`<1023.98px`）：`cn-qc-split` 既有断点收为纵向堆叠（左栏在上、右栏在下），无需新断点。
8. 页面状态不跨会话持久化：默认选中最近更新的设计每次进入重算（清单数据驱动，无 localStorage）。

### 5. 迁移

无。

### 6. 前端

| 层 | 文件 | 改动 |
|---|---|---|
| 页面重构 | `frontend/src/pages/design/DesignsPage.tsx` | 根容器 `cn-page cn-qc-page` + `cn-page-head`（图标 / 标题 / 副标题 / `Segmented` 筛选 / 新建按钮）；主体 `cn-qc-split` 双栏：左 `SectionBox`「产品列表」（可选行 + hover 动作），右 `SectionBox`「结构树」（选中产品名标题）；新建 / 改名 Modal、模板常量、mutation 原样保留 |
| 右栏结构树 | `frontend/src/pages/design/DesignsPage.tsx`（新组件函数） | 选中产品的装配树：outline 懒加载 + 本页缓存（IR 快照缓存优先）、`designOutline.ts` 复用映射、设计根 / 大纲节点点击 `designEditorPath`（带 `?line=`）；空态 / 回落 / 失败态见边界 #1-#5 |
| 侧栏收窄 | `frontend/src/layouts/MainLayout.tsx` | `siderMode='design'` 渲染条件收窄为编辑器页（`/design/:id`）；根页不渲染侧栏；`renderDesignNav` 本身不动（0103 C1 双向定位闭环保持） |
| 样式 | `frontend/src/index.css` | 删除 `.cn-design-structure` / `.cn-design-folder*` 旧类；新增 `.cn-ds-*` 排版类全部走 `--cn-*` token；复用 `cn-qc-split` / `cn-qc-row` / `cn-qc-empty` |
| 帮助 | `frontend/src/pages/help/content/*` | 设计模块页形态描述同步为左右分栏口径 |
| 文档 | `docs/adr/0084-*.md`、`docs/adr/0103-*.md` | D4 / D5、D12 失效行改写并引用本 ADR；CHANGELOG 记录 |

### 7. 测试清单

**判定层 / 接口层 / 迁移备份**：不适用（零后端、零契约变更）。

**前端单测**：`DesignsPage.test.tsx`——页头标题与副标题、双栏 testId（`design-products-box` / `design-outline-box`）、左栏选中 / 再点取消、`Segmented` 过滤、默认选中最近更新、选中项删除 / 筛掉后回落、右栏懒加载触发与空态、节点点击跳转 URL 含 `?line=`、新建 / 改名 / 删除主流程回归、viewer 门控、大纲加载失败提示。`MainLayout.test.tsx`——根页不渲染侧栏、编辑器页侧栏保留。`designOutline.test.ts` 不动（映射零改）。

**e2e（前端）**：`design-structure-tree.spec.ts` 改写为根页双栏断言（左栏选中 → 右栏出现系统 / 组件 / 零件层级与行号 → 点击零件节点进编辑器定位）；`design-sidebar-assembly.spec.ts` 收窄为编辑器页侧栏断言；`navigation.spec.ts` 页签断言回归。

### 8. 分期

| 期 | 内容 | 风险 |
|---|---|---|
| **P0** | 页头 + 双栏骨架 + 左栏可选列表（含筛选 / 动作 / viewer 门控），右栏占位空态 | 低（纯模板改写，逻辑不变） |
| **P1** | 右栏结构树（懒加载 / 默认选中 / 回落 / 失败态 / `?line=` 定位）+ 前端单测 | 中（懒加载状态管理与既有断言迁移） |
| **P2** | 侧栏渲染条件收窄 + ADR 0084 / 0103 失效行清理 + 帮助文案 + CHANGELOG + e2e 收口 | 低（边界收窄，e2e 回归为主） |

## 决策记录（唯一决策台账）

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | 整体方案选型 | 纯前端双栏改造：`/w/:wid/design` 原路由原页面改造为 `cn-qc-split` 双栏，复用质量检查页原语（I1 / I3） | 用户明确「参考质量检查、修改申请风格」；0107 / 0108 已验证同一套原语可承载「左清单 + 右详情」形态；零契约零依赖 | 新增独立路由保留旧管理页（两个「根页」语义重复，0083 D6 已否决过同型方案）；目录树左栏（管理页体量小，树形过重，0103 D12 已否决） | `DesignsPage.tsx`、`index.css` |
| D2 | 左栏形态 | 扁平可选列表 + 行内 Tag（目录 / 类型 / 依赖陈旧 / 版本），`role=listbox/option` 选中态；0103 D12 的 folder 分组小节退役为行内目录 Tag | 对齐质量检查 / 修改申请左栏形态（`cn-cr-side-item` 同型）；kind 筛选上移页头与 0103 口径一致 | 保留分组小节（双栏内小节标题压缩可用宽，与参考风格不符）；完全丢弃目录信息（损失 0103 C8 已落地的组织维度） | `DesignsPage.tsx` |
| D3 | 右栏默认态 | 默认选中最近更新的设计并立即懒加载其大纲（对齐需求 0107「默认选中申请数最多项」口径）；选中失效自动回落 | 「右侧为具体结构树」要求进入即见结构；空态等待点击浪费一次交互 | 默认空态提示（右栏首屏无内容，与「右侧为具体结构树」意图不符）；默认选中首个（更新时间比列表顺序更能表达「最近工作」） | `DesignsPage.tsx` |
| D4 | 模块侧栏去留 | 根页隐藏侧栏，编辑器页保留：`siderMode='design'` 渲染条件收窄为 `/design/:id` | 0103 C1 的树 ↔ 代码双向定位闭环以侧栏为载体，属已验收能力不可回退；根页右栏树已承担结构浏览，双树冗余 | 根页保留侧栏（同屏两棵树、双份懒加载状态，0084 D5 否决主区大树的同型理由）；全移除侧栏（破坏编辑器定位闭环，改动面外溢） | `MainLayout.tsx` |
| D5 | 右栏节点点击交互 | 与侧栏口径一致：设计根 / 大纲节点 → 编辑器（大纲节点带 `?line=` 定位源行）；不在本页内嵌编辑器或预览 | 0083 D7 已定型「树 = 可导航结构目录」交互；右栏复用零新协议（I2） | 右栏内嵌 DSL 片段 / 3D 预览（重复编辑器能力，渲染与权限面扩大，0083 D7 已否决同型）；点击仅选中不跳转（信息价值折半） | `DesignsPage.tsx` |
| D6 | 右栏数据获取 | 复用 `GET /designs/{id}/outline` 懒加载 + IR 快照缓存优先（键与编辑器 / 侧栏一致），本页缓存按设计 id | 0083 D4 已定型按需获取；缓存键一致则主区 / 侧栏 / 编辑器三处共享数据，不重复请求 | 列表响应内联全部大纲（`compiled` 可达数百 KB，响应膨胀，0083 D4 否决项不复活）；右栏独立再拉 `/ir`（重复载荷，outline 端点已裁剪） | `DesignsPage.tsx` |

门禁：`Proposed` → `Accepted` 前本表不得有「待定」；结论只在本书出现，别处只引用编号。

## Consequences

- **正向**：「设计结构」根页与质量检查 / 修改申请形成统一的左右分栏语言；不进编辑器即可按产品浏览装配层级；左栏选中态让「当前看的是哪个产品」始终可见。
- **负向**：0103 D12 的目录分组形态落地不足两期即退役（属需求演进）；根页与编辑器页侧栏形态分叉（根页无侧栏、编辑器页有），`MainLayout` 渲染条件多一个分支。
- **风险与缓解**：双栏挤压左栏宽度致行内 Tag 换行 → 行态允许 `wrap`、次要信息收敛为次级文本；e2e 树交互受 antd 展开动画窗口影响 → 沿用 0084 已知坑口径（展开前等待约 600ms）；选中态与 URL 无关联，刷新后回落最近更新 → 属可接受行为（页面为浏览入口，非深链载体）。

被否决的替代方案见「决策记录」对应行，此处不重复。

## 行业对照（可选）

| 维度 | SolidWorks | Onshape | 本设计 |
|---|---|---|---|
| 结构浏览入口 | FeatureManager 左树 | Browser 左树 | 主区双栏：左产品 / 右结构树（D1），侧栏保留编辑器内导航（D4） |
| 列表 ↔ 结构联动 | 选中特征高亮 | 选中零件高亮 | 左栏选中驱动右栏树（D3）；树 ↔ 视口高亮沿用 0103 D8 |

来源：ADR 0103「行业对照」（同源调研，口径一致）。

## 与既有 ADR 的关系（可选）

| 轴 | 载体 | 决定 | 由谁 |
|---|---|---|---|
| 大纲获取与定位交互 | `GET /designs/{id}/outline` + `?line=` | 端点与交互协议零变更，右栏复用 | ADR 0083 D4 / D7 / 本 ADR D5 / D6 |
| 历史快照兼容 | `source: "content"` 派生 | 口径不变，右栏同文案标注 | ADR 0083 D5 |
| 侧栏形态 | `DesignStructureNav` / `MainLayout` | 收窄为编辑器页渲染；组件本身不动 | ADR 0084 D4 → 本 ADR D4 修订 |
| 主区「设计结构」页形态 | `DesignsPage` | 管理列表 → 左右双栏（左产品 / 右结构树） | ADR 0084 D5 → 本 ADR D1 / D2 修订 |
| 管理页组织 | folder 分组 + kind 筛选 | 分组退役为行内 Tag，筛选上移页头 | ADR 0103 D12 → 本 ADR D2 修订 |
| 树 ↔ 代码双向定位闭环 | `?line=` 反选 + `scrollTo` | 不动（依赖侧栏，编辑器页保留） | ADR 0103 C1 |
| 权限口径 | 设计读写边界 | viewer 只读浏览完整，零写路径 | ADR 0083 D8 / 本 ADR 边界 #4 |

## 落地状态（随实现更新）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 | 已落地 | `frontend/src/pages/design/DesignsPage.tsx`、`frontend/src/index.css` | `frontend/src/pages/design/DesignsPage.test.tsx` | `6da43578` |
| P1 | 已落地 | `frontend/src/pages/design/DesignsPage.tsx`、`frontend/src/pages/design/designTree.tsx`、`frontend/src/pages/design/designOutline.ts` | `frontend/src/pages/design/DesignsPage.test.tsx` | `6da43578` |
| P2 | 已落地 | `frontend/src/layouts/MainLayout.tsx`、`frontend/src/pages/design/DesignStructureNav.tsx`、`frontend/src/pages/help/content/quickStart.tsx`、`frontend/src/pages/help/content/tutorials.tsx` | `frontend/src/layouts/MainLayout.test.tsx`、`frontend/tests/e2e/critical/design-structure-tree.spec.ts`、`frontend/tests/e2e/critical/design-sidebar-assembly.spec.ts` | `6da43578` |

> 状态只取「未开始 / 进行中 / 已落地」。标「已落地」的期必须有代码落点与测试文件；全期落地后由人确认 `Status` 是否改 `Accepted` / `Implemented`。`make adr-check` 会校验本表与代码、测试、CHANGELOG 的对应关系。

## 交接（会话结束更新）

- 当前阶段：P0 / P1 / P2 全部落地（`Status: Implemented`）
- 已完成：根页改为 `cn-page cn-qc-page` + `cn-page-head` + `cn-qc-split` 双栏；左栏扁平可选列表（行内 Tag / 选中与取消 / hover 动作 / viewer 门控）；右栏装配树（`designTree.tsx` 与侧栏共用映射，outline 懒加载 + IR 快照缓存优先、默认选最近更新、失效回落、失败重试、`?line=` 定位）；侧栏收窄为编辑器页（`siderMode='design'` 只在 `/design/:id`）；ADR 0084 D4 / D5 与 0103 D12 失效行已改写；帮助文案、CHANGELOG、单测与两个 e2e 同步
- 下一步：无（后续「设计结构」页演进沿用同一套 `cn-qc-*` 原语与 `designTree.tsx` 映射；如需列表搜索 / 目录折叠再单开需求）
- 已知坑：① antd Tree 展开动画窗口（约 600ms）会吞点击 —— 侧栏单测 / e2e 展开前先等待（ADR 0084 口径），根页右栏用 `defaultExpandAll` 免去展开；② 右栏大纲缓存键须与编辑器 `useQuery` 一致（`['designs', wid, String(id), 'ir']`）才能命中 IR 快照，改动键名要三处同改；③ 根页 `siderMode='hidden'` 时移动端汉堡入口不再渲染（无侧栏可开），勿把它当「总能打开导航」使用
- 最近一次全绿：`make check`（lint / typecheck / frontend-static / frontend-coverage / cov）+ `make frontend-build` + bundle budget + 设计相关 e2e（`design-structure-tree` / `design-sidebar-assembly` / `design-tree-viewport-linkage` / `design-editor-layout` / `design-3d-preview` / `navigation`）@ 2026-11-06
