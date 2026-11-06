# ADR 0109: 【设计】设计模块单一工作台（侧栏产品列表 ↔ 结构树，Content = DSL / 视图）

Status: Implemented（2026-11-06 落地）
Date: 2026-11-06
Related: `frontend/src/pages/design/DesignsPage.tsx`、`frontend/src/pages/design/DesignStructureNav.tsx`、`frontend/src/pages/design/DesignEditorPage.tsx`、`frontend/src/pages/design/designTree.tsx`、`frontend/src/layouts/MainLayout.tsx`、`frontend/src/App.tsx`、`frontend/src/index.css`、`frontend/src/pages/help/content/*`、`docs/adr/0083-design-structure-subnav-and-assembly-tree.md`、`docs/adr/0084-design-sidebar-assembly-and-system-level.md`、`docs/adr/0103-design-editor-layout-optimization.md`
需求卡片: `docs/requirements/0109-design-structure-left-right-layout.md`（需求原文与约束编号的唯一副本）

## 口径（需求 → 设计落点）

需求原文：见需求卡片 §需求原句（逐字，ADR 不复制第二份）。

卡片约束沿用各自编号（C1..Cn），本表只补「设计怎么落地」，不重新拆句：

| 卡片约束 # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | 「产品列表和结构树共享侧边栏」 | 重建设计侧栏为**单组件两态**：`DesignsPage` 改为侧栏宿主，内部维护 `view: 'list' \| 'tree'`；同一时刻只渲染产品列表（`design-products-panel`）或结构树（`design-outline-panel`）之一。`MainLayout` 在设计上下文（根页 / 编辑器页）始终渲染该侧栏（D4 / D8） |
| C2 | 「选取产品后就地切入结构树」 | 列表点击产品 → `navigate(/w/:wid/design/:id)`，侧栏 `view` 切到 `tree` 并载入该产品大纲；树态头部「产品列表」返回键只把 `view` 切回 `list`，URL 与 Content 不变；大纲节点点击沿用 `designEditorPath(..., line)`（D4 / D5） |
| C3 | 「Content区域留给DSL编辑和视图」 | 根页不再渲染页头与 `cn-qc-split` 双栏；`/design/:id` 的 Content 即现有 `DesignEditorPage`（工具栏 + 诊断 + DSL + 3D + 参数面板），并删除工具栏内的返回管理页箭头（D1 / D7） |
| C4 | （入口收进侧栏） | 侧栏列表态顶部：`SearchInput` 过滤标题、`Segmented` 类型筛选、`Button` 新建设计；行内保留名称 / 零件·装配 Tag / 目录 Tag / 依赖陈旧 Tag / `v{version_count}` / 更新时间；行尾 打开 / 编辑 / 删除；新建 / 改名 / 删除 Modal 从根页迁入侧栏；viewer 门控原样保留（D2） |
| C5 | （默认选中与空态） | `/design` 等列表就绪后取最近更新的设计 `navigate(..., { replace: true })`；无设计时侧栏列表空态 + 新建，Content 空态「还没有结构设计」；`/design/:id` 404 或产品被删时回落最近更新，列表为空回 `/design`（D3 / 边界 #2-#4） |
| C6 | （配套回归） | `MainLayout` 移除 `onDesignRoot` 隐藏分支；移动端抽屉同一组件；退役 `.cn-ds-outline-tree` 与根页双栏相关样式，新增类只用 `--cn-*` token 与既有断点；ADR 0084 D4 / D5、ADR 0103 C8 / D12 / 交接失效行改写引用本 ADR；单测 / e2e / 帮助 / CHANGELOG 同步（D8） |

决策结论只在「决策记录」写一次；本节与正文不再罗列「已确认决策」。

## Context

现状逐条核对（以代码为准，标注 `文件:行号`）。沿用卡片「现状影响面」的编号，逐条给结论；ADR 新发现的条目追加编号。

| # | 现状 | 位置 | 影响 | 与卡片的关系 |
|---|---|---|---|---|
| 1 | 设计根页为 `cn-page cn-qc-page` + `cn-page-head` + `cn-qc-split` 双栏：左产品列表 / 右结构树，整页都在 Content 内 | `frontend/src/pages/design/DesignsPage.tsx:404-470` | 与「侧栏共享、Content 留给编辑器」直接冲突；同屏无法同时看到 DSL / 视图 | 确认：C1 / C2 / C3 改造对象 |
| 2 | 编辑器页 Content 已是完整工作台（工具栏 / 诊断 / 可拖分栏 / 3D / 参数面板） | `frontend/src/pages/design/DesignEditorPage.tsx:375-584`、`frontend/src/index.css:7283-7608` | 编辑器本身无需重写，只需由「独立页」变为设计模块唯一 Content | 确认：C3 复用面 |
| 3 | 设计上下文侧栏在根页被隐藏（`onDesignRoot`），只在 `/design/:id` 渲染装配树 | `frontend/src/layouts/MainLayout.tsx:441-476`、`:932-944` | 与「共享侧边栏」冲突；根页无侧栏、编辑器页有侧栏，形态分叉 | 确认：C1 / C6 改造点 |
| 4 | `DesignStructureNav` 为「设计清单嵌套大纲」的一棵树：设计节点下挂系统 / 组件 / 零件 | `frontend/src/pages/design/DesignStructureNav.tsx:135-152` | 产品与结构混在同一棵树，无法表达「选产品 → 就地进入该产品结构」的两态语义 | 确认：C1 / C2 重构对象 |
| 5 | 大纲懒加载、IR 快照缓存优先、虚拟滚动、`?line=` 反向定位均已就绪 | `DesignStructureNav.tsx:69-133`、`designOutline.ts`、ADR 0083 D4 / D7、ADR 0103 C1 | 结构树态可直接复用，零新协议 | 确认：C2 复用面 |
| 6 | 编辑器工具栏有「返回设计列表」箭头，指向 `/design` | `DesignEditorPage.tsx:380-382` | 新形态下 `/design` 会自动重定向，该箭头语义失效 | 新增：C3 清理点 |
| 7 | 根页路由 `/w/:wid/design` 渲染 `DesignsPage`；编辑器 `/design/:designId` 渲染 `DesignEditorPage` | `frontend/src/App.tsx:108-114` | 路由可保留，仅改各自职责（根页 = 选择 / 重定向，编辑器 = Content） | 确认：C5 |
| 8 | 新建 / 改名 / 删除 Modal、模板常量、mutation 均在根页 | `frontend/src/pages/design/DesignsPage.tsx:97-403`、`:472-558` | 迁入侧栏后逻辑可原样保留 | 确认：C4 迁移面 |
| 9 | 单测 / e2e 断言双栏同时可见、根页无侧栏 | `DesignsPage.test.tsx`、`MainLayout.test.tsx:1227-1260`、`frontend/tests/e2e/critical/design-structure-tree.spec.ts`、`design-sidebar-assembly.spec.ts` | 两态互斥后断言全部改写 | 确认：C6 回归面 |
| 10 | 既有 ADR 定「根页双栏 + 编辑器页才有侧栏」 | `docs/adr/0084-*.md` D4 / D5、`docs/adr/0103-*.md` C8 / D12 | 与本需求冲突，失效行随实现改写 | 确认：C6 清理对象 |

**核心缺陷（需求要补的）**：产品浏览与结构浏览被放在 Content 的正交两栏里，导致「选产品」与「看结构」必须离开编辑器；产品列表、结构树、DSL、视图四者无法形成「侧栏选产品 / 结构 → 主区编辑 / 预览」的单一工作流。

设计目标（不变量）：

- **I1 零契约变更**：零新端点、零 IR / DSL 变更、零迁移、零后端改动。
- **I2 能力不减少**：新建 / 改名 / 描述 / 删除、类型筛选、viewer 门控、大纲懒加载、`?line=` 定位、树 ↔ 视口高亮闭环全部保留。
- **I3 原语复用**：侧栏沿用 `cn-table-nav` / `cn-doc-sider-tree` / `SearchInput` / `Segmented`；编辑器布局与样式零重写；断点只用既有 `1023.98px / 767.98px`。

## Decision

### 1. 数据模型

无。

### 2. 判定算法（唯一入口）

无（纯前端布局重构）。结构树数据流唯一入口仍为 `GET /designs/{id}/outline` + `designOutline.ts` 映射（ADR 0083 D4）；默认选中的唯一入口为「最近更新时间」，仅在 `DesignsPage` 计算一次。

### 3. API 变更清单

| 端点 | 变更 |
|---|---|
| `GET /api/v1/workspaces/{wid}/designs` | 无变更（侧栏列表复用） |
| `GET /api/v1/workspaces/{wid}/designs/{id}/outline` | 无变更（结构树态复用，IR 快照缓存优先） |
| 其余设计端点 | 无变更 |

### 4. 边界与例外

1. 工作区无设计：侧栏显示「还没有结构设计」+ 新建按钮（非 viewer）；Content 空态同样引导新建；不触发重定向。
2. `/design` 有设计：清单到达后 `replace` 到最近更新的 `/design/:id`；首帧显示加载态，不闪空态。
3. `/design/:id` 产品不存在 / 被删除（详情 404）：回落到最近更新的其余产品（`replace`）；列表为空则回 `/design`。
4. 类型筛选后当前产品被隐藏：侧栏列表仅过滤展示，不强制切换 Content；用户从列表选择新过滤结果时才跳转（避免编辑中被动换文件）。
5. viewer：无新建 / 编辑 / 删除，浏览、结构树与定位能力完整。
6. 大纲加载失败：结构树态显示「结构加载失败」+ 重试；不阻塞 Content 编辑器。
7. 历史 v1 / v2 快照：沿用 `source: "content"` 派生口径，结构树态标注「历史快照派生」。
8. 未保存草稿：切换产品沿用现有路由重挂载行为（草稿不跨产品保留）；本需求不新增离开确认，风险在 Consequences 记录。
9. 窄屏（`<1023.98px`）：侧栏不常驻，由汉堡入口打开抽屉；抽屉内两态与桌面一致，点击产品后收起抽屉，Content 占满宽度。

### 5. 迁移

无。

### 6. 前端

| 层 | 文件 | 改动 |
|---|---|---|
| 根页 | `frontend/src/pages/design/DesignsPage.tsx` | 由「整页双栏」改为「侧栏宿主」：加载设计清单 → 默认选中最近更新并 `replace` 跳 `/design/:id`；无设计时渲染 Content 空态；内部渲染产品列表态（搜索 / 筛选 / 新建 / 行动作 / Modal）与结构树态（返回键 + 大纲） |
| 结构树态 | `frontend/src/pages/design/DesignStructureNav.tsx` | 由「设计清单 + 大纲」嵌套树改为**单产品结构树**：接收 `design` + `onBack`，复用 `designsApi.outline`、IR 缓存、`outlineToTree`、`?line=` 反选与 `scrollTo`；树态头部显示产品名、版本 / 依赖陈旧 / 历史快照 Tag 与「产品列表」返回 |
| 编辑器 | `frontend/src/pages/design/DesignEditorPage.tsx` | 移除工具栏返回管理页箭头；其余布局与数据流不动 |
| 布局 | `frontend/src/layouts/MainLayout.tsx` | 删除 `onDesignRoot` 隐藏分支；设计上下文（根页 / 编辑器）始终渲染侧栏；`renderDesignNav` 改为把当前 `designId` 与移动端收起回调传给新侧栏 |
| 路由 | `frontend/src/App.tsx` | 路由结构不变；根页职责改为选择 / 重定向（组件内实现） |
| 样式 | `frontend/src/index.css` | 退役根页双栏与 `.cn-ds-outline-tree` 专用样式；侧栏列表行复用 `cn-qc-row` 紧凑口径并按 240px 宽度收敛 Tag；新增类只用 `--cn-*` token |
| 帮助 / 文档 | `frontend/src/pages/help/content/*`、`docs/adr/0084-*.md`、`docs/adr/0103-*.md` | 设计模块形态描述改为「侧栏产品列表 / 结构树 + Content 编辑器」；0084 D4 / D5、0103 C8 / D12 / 交接失效行改写引用本 ADR；CHANGELOG 记录 |

### 7. 测试清单

**判定层 / 接口层 / 迁移备份**：不适用（零后端、零契约变更）。

**前端单测**：

- `DesignsPage.test.tsx`：根页自动重定向到最近更新产品；无设计时 Content 空态 + 侧栏新建；列表态渲染搜索 / 筛选 / 新建 / 行动作；点击产品 → 树态 + URL；「产品列表」返回 → 列表态且 URL 不变；筛选 / 搜索；新建 / 改名 / 删除；viewer 门控；删除当前产品后的回落。
- `DesignStructureNav.test.tsx`：单产品大纲渲染、懒加载触发、IR 缓存优先、`?line=` 反选与祖先展开、加载失败重试、历史快照 Tag。
- `MainLayout.test.tsx`：设计根页与编辑器页均渲染侧栏；移动端汉堡入口可用；其他模块侧栏形态回归。
- `DesignEditorPage.test.tsx`：工具栏不再有返回管理页链接；编辑器主流程回归。

**e2e（前端）**：

- `design-structure-tree.spec.ts` 改写为「侧栏列表 → 选产品 → 侧栏树 → 点节点进编辑器定位」；补「根页自动进入最近更新产品」断言。
- `design-sidebar-assembly.spec.ts` 改写为单产品结构树断言（三级装配仍可见）。
- `design-tree-viewport-linkage.spec.ts` / `design-editor-layout.spec.ts` 只改「根页无侧栏」相关注释与定位，断言不变。

### 8. 分期

| 期 | 内容 | 风险 |
|---|---|---|
| **P0** | 侧栏宿主化：`DesignsPage` 改为产品列表态（搜索 / 筛选 / 新建 / 行动作 / Modal）+ 根页默认选中重定向 + 无设计空态；`MainLayout` 设计上下文始终渲染侧栏 | 中（路由重定向与首帧空态、侧栏宽度容纳行内 Tag） |
| **P1** | 侧栏结构树态：`DesignStructureNav` 单产品化 + 返回键 + 大纲懒加载 / 缓存 / `?line=` 反选；编辑器移除返回箭头；Content 清理双栏 | 中（两态切换与既有定位闭环） |
| **P2** | 样式退役 + 单测 / e2e 改写 + 帮助文案 + ADR 0084 / 0103 失效行清理 + CHANGELOG | 低（回归面为主） |

## 决策记录（唯一决策台账）

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | 整体方案选型 | 合并为单一工作台：侧栏 = 产品列表 / 结构树两态，Content = 现有编辑器工作台；根页 `/design` 只负责选择 / 重定向；「设计结构」二级页签在整个设计上下文保持激活 | 用户明确「共享侧边栏、就地切入结构树、Content 留给 DSL 与视图」；编辑器已是完整工作台，零重写；进入设计即落编辑器后子页仍应保持选中 | 保留根页双栏（与需求直接冲突，Content 被列表占用）；侧栏常驻「清单 + 嵌套树」一棵树（产品与结构语义混杂，选中产品后仍看到全部产品）；编辑器页取消子页激活（进入设计却无选中项） | `DesignsPage.tsx`、`MainLayout.tsx` |
| D2 | 产品列表态形态 | 侧栏内扁平可选列表 + 行内 Tag（类型 / 目录 / 依赖陈旧 / 版本）；顶部搜索 + 类型筛选 + 新建；行尾 打开 / 编辑 / 删除；新建 / 改名 / 删除 Modal 迁入侧栏 | 入口收进侧栏（用户确认）；0109 既有扁平列表与 0103 D12「目录分组退役为行内 Tag」口径不变 | 保留 Content 页头（与「Content 留给编辑器」冲突）；侧栏使用目录树（240px 内层级过重） | `DesignsPage.tsx`、`index.css` |
| D3 | 默认选中 | 进入 `/design` 自动选中最近更新的设计并 `replace` 到 `/design/:id`；无设计时停留根页显示空态 | 用户确认「自动打开最近更新」；对齐需求 0107 默认选中口径；编辑器即默认落地视图 | 空态等待点击（多一次交互，与用户确认相反）；默认选第一个（列表顺序不等于最近工作） | `DesignsPage.tsx` |
| D4 | 侧栏两态切换 | `view` 为侧栏本地状态，初始由路由推导（有 `designId` = `tree`，否则 `list`）；「产品列表」返回键只切 `view`，不改 URL、不卸载 Content；选产品才改 URL | 「就地切入」的语义是侧栏内部切换；返回列表时保留当前编辑器上下文，避免无意义重载与草稿丢失 | 用 `?view=list` 表达（URL 噪声，刷新后语义反直觉）；返回即跳 `/design`（会触发重定向到最近更新，可能换掉用户当前产品） | `DesignsPage.tsx` |
| D5 | 结构树态交互 | 结构树只展示当前产品：根 = 产品（点击进编辑器），下挂 系统 → 组件 → 分组 → 零件；节点点击沿用 `?line=` 定位；根节点 / 产品标题点击打开编辑器 | 复用 0083 D7 已定型的「树 = 可导航结构目录」；单产品化后层级语义更纯 | 保留全部产品的嵌套树（无法表达「当前产品」上下文）；树节点内联编辑（侧栏只读口径 0084 D6） | `DesignStructureNav.tsx` |
| D6 | 结构树数据获取 | 复用 `GET /designs/{id}/outline` + IR 快照缓存优先（键 `['designs', wid, String(id), 'ir']`），虚拟滚动高度按侧栏可用高度 | 0083 D4 / 0086 D10 已定型按需获取；三处共享缓存不重复请求 | 列表响应内联大纲（体积膨胀）；另外拉 `/ir`（重复载荷） | `DesignStructureNav.tsx` |
| D7 | Content 归属 | Content 只保留编辑器工作台；根页页头 / 双栏 / 列表全部移出；编辑器工具栏返回箭头移除 | 用户明确「Content 区域留给 DSL 编辑和视图」；返回列表由侧栏返回键承担 | 编辑器上方再挂面包屑 / 页头（挤压视口高度，违背 0103 C6 单行工具栏口径） | `DesignEditorPage.tsx`、`DesignsPage.tsx` |
| D8 | 侧栏渲染范围 | 设计上下文（`/design` 与 `/design/:id`）始终渲染 `siderMode='design'`；移动抽屉共用；仅当工作区未开放设计模块时回落 | 「共享侧边栏」要求根页也有侧栏；根页重定向后仍是同一侧栏，避免首帧跳动 | 根页继续隐藏侧栏（需求冲突）；只在编辑器页渲染（根页选择产品无处可放） | `MainLayout.tsx` |

门禁：`Proposed` → `Accepted` 前本表不得有「待定」；结论只在本书出现，别处只引用编号。

## Consequences

- **正向**：设计模块收敛为「侧栏选产品 / 看结构 → 主区编辑 / 预览」的单一工作流；Content 宽度全部让给 DSL 与 3D 视图；产品列表与结构树共享同一侧栏，不再同屏争抢横向空间；根页进入即落编辑器，减少一次点击。
- **负向**：`DesignsPage` 与 `DesignStructureNav` 职责重写，单测 / e2e 断言大面积迁移；侧栏 240px 内行内 Tag 需收敛，信息密度高于原双栏；侧栏两态是本地状态，刷新后回到结构树态（不回列表）。
- **风险与缓解**：
  - 切换产品会丢弃未保存草稿（沿用现有路由重挂载行为）→ 属既有行为，本需求不扩大承诺；若后续需要，单开「离开确认」需求。
  - 根页重定向首帧可能闪空态 → 列表 loading 期间渲染骨架，就绪后再判定重定向。
  - 侧栏宽度容不下长标题 + Tag → 标题单行省略 + Tooltip，Tag 按需折叠为次级文本。
  - e2e 依赖侧栏两态切换 → 断言以 `design-products-panel` / `design-outline-panel` 的可见性为准，避免依赖动画时序。

被否决的替代方案见「决策记录」对应行，此处不重复。

## 行业对照（可选）

| 维度 | SolidWorks | Onshape | 本设计 |
|---|---|---|---|
| 产品 / 文档选择 | 打开文档后进入工作区 | Documents 页 → 打开进入工作区 | 侧栏产品列表，选中即进工作台（D3 / D4） |
| 结构浏览 | FeatureManager 左树 | Browser 左树 | 侧栏结构树态（D4 / D5） |
| 编辑与预览 | 左树 + 主视口 | 左树 + 主视口 | 侧栏 + Content（DSL / 视图），同构（D7） |

来源：ADR 0103「行业对照」（同源调研，口径一致）。

## 与既有 ADR 的关系（可选）

| 轴 | 载体 | 决定 | 由谁 |
|---|---|---|---|
| 大纲获取与定位交互 | `GET /designs/{id}/outline` + `?line=` | 端点与交互协议零变更，结构树态复用 | ADR 0083 D4 / D7 / 本 ADR D5 / D6 |
| 历史快照兼容 | `source: "content"` 派生 | 口径不变，结构树态同文案标注 | ADR 0083 D5 |
| 侧栏形态 | `DesignStructureNav` / `MainLayout` | 由「清单嵌套树、仅编辑器页」改为「单产品两态、设计上下文始终渲染」 | ADR 0084 D4 → 本 ADR D4 / D8 修订 |
| 主区「设计结构」页形态 | `DesignsPage` | 由左右双栏改为侧栏宿主 + Content 空态 / 重定向 | ADR 0084 D5 → 本 ADR D1 / D2 / D7 修订 |
| 管理页组织 | folder 分组 + kind 筛选 | 分组仍退役为行内 Tag，筛选移入侧栏 | ADR 0103 D12 → 本 ADR D2 修订 |
| 树 ↔ 代码双向定位闭环 | `?line=` 反选 + `scrollTo` | 不动（结构树态承载） | ADR 0103 C1 |
| 权限口径 | 设计读写边界 | viewer 只读浏览完整，零写路径 | ADR 0083 D8 / 本 ADR 边界 #5 |

## 落地状态（随实现更新）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 | 已落地 | `frontend/src/pages/design/DesignsPage.tsx`、`frontend/src/pages/design/designDefaults.ts`、`frontend/src/pages/design/designOutline.ts`、`frontend/src/layouts/MainLayout.tsx` | `frontend/src/pages/design/DesignsPage.test.tsx`、`frontend/src/layouts/MainLayout.test.tsx` | — |
| P1 | 已落地 | `frontend/src/pages/design/DesignStructureNav.tsx`、`frontend/src/pages/design/DesignEditorPage.tsx` | `frontend/src/pages/design/DesignStructureNav.test.tsx`、`frontend/src/pages/design/DesignEditorPage.test.tsx` | — |
| P2 | 已落地 | `frontend/src/index.css`、`frontend/src/pages/help/content/quickStart.tsx`、`frontend/src/pages/help/content/tutorials.tsx`、`docs/adr/0084-design-sidebar-assembly-and-system-level.md`、`docs/adr/0103-design-editor-layout-optimization.md`、`CHANGELOG.md` | `frontend/tests/e2e/critical/design-structure-tree.spec.ts`、`frontend/tests/e2e/critical/design-3d-preview.spec.ts`、`frontend/tests/e2e/critical/navigation.spec.ts`、`frontend/tests/e2e/perf/design-assembly-open.spec.ts` | — |

> 状态只取「未开始 / 进行中 / 已落地」。标「已落地」的期必须有代码落点与测试文件；全期落地后由人确认 `Status` 是否改 `Accepted` / `Implemented`。`make adr-check` 会校验本表与代码、测试、CHANGELOG 的对应关系。

## 交接（会话结束更新）

- 当前阶段：P0-P2 全部落地，`Status: Implemented`，待提交
- 已完成：侧栏宿主与根页重定向（P0）、单产品结构树与编辑器 Content 归位（P1）、样式退役 / 单测与 e2e 改写 / 帮助文案 / 0084·0103 失效行清理 / CHANGELOG（P2）
- 下一步：提交后回填本表「提交」列；如需发版按 release 流程走人工卡点
- 已知坑：① 根页重定向需在清单 loading 完成后执行，避免闪空态；② 结构树缓存键必须与编辑器一致（`['designs', wid, String(id), 'ir']`）；③ 侧栏两态为本地状态，刷新回到树态属预期；④ 移动端点击产品后需收起抽屉；⑤ 测试环境 `gcTime` 为 0，IR 缓存优先用例需在缓存写入后同步点击
- 最近一次全绿：2026-11-06 `make check-fast` / `make test`（6667 passed）通过，前端全量 `253 files / 3092 tests` 通过，目标 e2e（`design-structure-tree` / `design-sidebar-assembly` / `design-3d-preview` / `navigation`，15 例）通过
