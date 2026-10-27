# ADR 0036: 帮助文档四级层级（部分 / 主题 / 小节 / 条目）与内容补全

Status: Implemented（已评审；2026-10-27 人工确认 P0-P2 全期落地）
Date: 2026-10-26
Related: `frontend/src/pages/help/helpNav.tsx`、`frontend/src/pages/help/HelpDocsPage.tsx`、`frontend/src/pages/help/helpNav.test.tsx`、`frontend/src/pages/help/HelpDocsPage.test.tsx`、`frontend/src/pages/help/content/HelpDoc.tsx`、`frontend/src/pages/help/content/primitives.tsx`、`frontend/src/pages/help/content/quickStart.tsx`、`frontend/src/pages/help/content/tutorials.tsx`、`frontend/src/pages/help/content/configuration.tsx`、`frontend/src/pages/help/content/troubleshooting.tsx`、`frontend/src/pages/help/content/examples.tsx`、`frontend/src/pages/help/content/ExamplesSection.tsx`、`frontend/src/index.css`、`frontend/tests/e2e/critical/help-docs.spec.ts`
需求卡片: `docs/requirements/0036-help-docs-hierarchy.md`（需求原文与约束编号的唯一副本）

## 口径（需求 → 设计落点）

需求原文：见需求卡片 §需求原句（逐字，ADR 不复制第二份）。

卡片约束沿用各自编号（C1..Cn），本表只补「设计怎么落地」，不重新拆句：

| 卡片约束 # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | 对现有帮助文档的结构做进一步细分梳理 | `HelpTopic` 由 `content: ReactNode` 改为 `intro + subsections[]`，`HelpSubsection` 带 `items[]`；L3 → `h2`、L4 → `h3`，锚点由 `subsectionAnchor` / `itemAnchor` 统一生成 |
| C2 | 明确第三、第四层级文档的划分方式与归属关系 | §2.1 划分规则 + §2.2 归属规则；代码注释同步；单测校验「空壳小节」「重复 key / label」 |
| C3 | 识别其中缺失或内容不完整的文档 | §Context 现状表按「功能面」逐条判定缺失 / 不完整，缺口清单见 §1.2 |
| C4 | 并补充完善 | 新增 6 个主题（见 §2.3），原有 16 个主题全部按四级重写 |
| C5 | 说明梳理后的层级结构 | §2.1 四级树 + §2.2 每级定位 |
| C6 | 各层级文档的定位与覆盖范围 | §2.2 定位表（回答什么问题 / 不写什么 / 数量口径） |
| C7 | 新增或补全的文档清单和主要内容要点 | §2.3 新增主题与要点表 |
| C8 | 确保层级清晰、内容完整、无重复与遗漏 | I1 单一真相源、I2 不复制段落、I3 锚点唯一；页内目录与正文同源生成 |

决策结论只在「决策记录」写一次；本节与正文不再罗列「已确认决策」。

## Context

现状逐条核对（以代码为准）。

| # | 现状 | 位置 | 影响 | 与卡片的关系 |
|---|---|---|---|---|
| 1 | 导航只有两级（`HelpSection.topics[].content`），主题内是单块 JSX | `frontend/src/pages/help/helpNav.tsx:47` | 6 个原主题被「重组」为 16 个主题后，单页正文 60~200 行无结构，无法定位、无法深链 | 确认（C1/C2） |
| 2 | 页面只渲染 `h1` + `topic.content`，无页内目录 | `frontend/src/pages/help/HelpDocsPage.tsx:108` | 长正文只能滚动查找；也无法从外部直接指向某一节 | 确认（C1/C5） |
| 3 | 正文里的小标题用 `<Text strong> + <br />` 手写 | `content/tutorials.tsx:17`、`content/configuration.tsx:16` | 语义层级缺失：屏幕阅读器与目录都无法识别「这是第 3 层」 | 确认（C1） |
| 4 | 功能面与帮助主题对不上：文档、数据分析、搜索收藏、管理台、界面导航、诊断反馈在帮助里没有主题 | 全部 `content/*.tsx` | 用户在产品里能看到的功能，帮助里查不到；「文档」只在快速入门一句话带过 | 确认（C3/C4） |
| 5 | 部分主题事实偏薄：权限只写三角色表、缺表级 / 行级 / 视图可见性；排障只有 5 条，缺大模型、备份、兼容性 | `content/tutorials.tsx:108`、`content/troubleshooting.tsx:58` | 「内容不完整」：能查到概念，查不到怎么判断与处理 | 确认（C3/C4） |
| 6 | 示例正文一个组件平铺 5 段内容（清单 / 预览 / 亮点 / 步骤） | `content/ExamplesSection.tsx` | 无小节层级，也不能只分享「数据表清单」这一段 | 新增（C1/C4） |
| 7 | 现有样式只有 `--cn-help-docs-*` 的页面骨架与图例外壳 | `frontend/src/index.css:3838` | `h2` / `h3` / 目录 / 列表 / 提示块无样式，直接加标题会退化成浏览器默认样式 | 新增（C1） |
| 8 | 图示（ADR 0030）按 key 内联，与正文层级无关 | `registry.py:FIGURE_SPECS` | 加层级不需要动图示，图示继续挂在对应 L3 的 body 上 | 排除（无改动） |
| 9 | 导航即路由真相源，深链靠 `topicPath` | `helpNav.tsx:81` | 加锚点必须扩展地址生成函数，否则页内定位无法分享 | 新增（C8） |

**核心缺陷（需求要补的）**：帮助文档只有「部分 / 主题」两级可寻址结构，主题内部是无层级的文字堆，导致**定位粒度太粗**（整页才能分享）与**覆盖不全**（产品已有能力在帮助里没有落点）。

设计目标（不变量）：

- **I1 单一真相源**：`HELP_SECTIONS` 同时决定侧栏、路由、页内目录与正文层级；不存在「目录里有、正文没有」或反向情形。
- **I2 不复制段落**：同一事实只在一条 L4 写全，其它位置用 `helpLink` 链接；`roles` 是权限口径的唯一出处，`configuration/*` 只写操作入口。
- **I3 锚点可寻址**：L3 / L4 都有稳定锚点（`help-<小节>` / `help-<小节>--<条目>`），同一主题内唯一，可直接分享。
- **I4 不留空层**：每个主题 ≥2 个 L3；每个 L3 要么有正文，要么 ≥2 个 L4；单个 L4 不足以撑起一个 L3。
- **I5 零后端变更**：正文仍是前端静态内容，不落库、不加接口、不改备份。

## Decision

### 1. 现状盘点：缺失与不完整清单

#### 1.1 覆盖矩阵（功能面 → 原有落点）

| 功能面 | 代码位置 | 原帮助落点 | 判定 |
|---|---|---|---|
| 工作区 / 数据表 / 视图 / 字段 | `pages/workspace`、`pages/grid` | 快速入门 + 教程 4 主题 | 有，但无层级 |
| 文档（结构树 / 版本 / 导入 / 分享） | `pages/documents`、`plugins/documents` | 快速入门一句话 | **缺失** |
| 数据分析（公式 / 分组汇总 / 图表 / AI） | `pages/analytics` | 无 | **缺失** |
| 全局搜索 / 收藏视图 / 排序 | `components/GlobalSearch.tsx`、`pages/workspace/MyViewsPanel.tsx` | 无 | **缺失** |
| 修改申请与审批 | `pages/changeRequests`、`plugins/change_requests` | 一句「转修改申请」 | **不完整** |
| 行级权限 / 表级授权 / 视图可见性 | `tables/services/core/{row_access,view_access}.py` | 仅三角色 | **不完整** |
| 数据源同步（含大规模增量） | `pages/datasource` | 系统配置 1 主题 | 有，缺小节 |
| 管理台（用户 / 事件流 / 空间 / 备份恢复） | `pages/admin` | 只在存储主题里提一句 | **缺失** |
| 界面导航（顶栏 / 页签 / 视图栏 / 入口） | `layouts/MainLayout.tsx` | 无 | **缺失** |
| 诊断与反馈（收集信息 / 事件流 / 问题清单） | `pages/issues` | 排障末条一句话 | **缺失** |

#### 1.2 缺口结论

- 缺失（整块无落点）：文档、数据分析、搜索与收藏、管理台、界面导航、诊断与反馈 → 6 个新主题。
- 不完整（有落点但查不到判断与处理）：权限（缺表级 / 行级 / 视图可见性 / 审批）、排障（缺大模型、备份恢复、老内核）、示例（无小节）。
- 重复：原「数据存在哪里」同时出现在 FAQ 与系统配置 → 统一收口到 `configuration/storage`，FAQ 只留一句并链接。

### 2. 四级层级模型

#### 2.1 结构与划分规则

```
/help/:section/:topic[#anchor]
L1 部分（5）          侧栏分组，无独立地址
└─ L2 主题（22）      一个页面 + 一条路由
   └─ L3 小节（114）  页面内 h2 + 锚点，进「本页目录」
      └─ L4 条目（78）小节内 h3 + 锚点，多条目小节才在目录里展开
```

| 层级 | 划分方式（怎么切） | 归属规则 |
|---|---|---|
| L1 部分 | 按用户意图：入门 / 学习 / 照做 / 配置 / 求助，固定 5 个且顺序不变 | 由 `HELP_SECTIONS` 顺序决定，不新增 |
| L2 主题 | 按**对象或任务族**：一个对象（视图、字段、文档、数据源、管理台）或一个任务族（导入导出、权限、搜索） | 主题 key 在部分内唯一；主题即路由，不可寄生在别的主题里 |
| L3 小节 | 按**阶段或属性维度**：流程阶段（预览 → 识别 → 落表）、属性维度（角色 / 可见性 / 表级 / 行级）、症状域（登录、导入、同步） | 每个主题 ≥2 个；L3 不跨主题存在，通用口径只在一处，其余链接 |
| L4 条目 | **单一实例**：一个视图模式、一个字段类型、一个设置项、一条排障症状、一个 FAQ 问题 | 只挂一个 L3；key 在小节内唯一；title 即症状 / 对象名，可单独分享 |

#### 2.2 各层级定位与覆盖范围

| 层级 | 回答什么问题 | 不写什么 | 数量（本次） |
|---|---|---|---|
| L1 部分 | 「我现在该看哪一类」 | 任何具体操作 | 5 |
| L2 主题 | 「这个对象 / 任务族整体怎么用」 | 与其它主题重复的口径（用链接） | 22 |
| L3 小节 | 「这件事分几步 / 分几个维度」 | 单一实例的细节（下沉到 L4） | 114 |
| L4 条目 | 「这一条具体怎么判断、怎么处理」 | 跨条目综述（上浮到 L3 导语） | 78 |

主题层（L2）分布：快速入门 3 / 教程&最佳实践 8 / 典型示例 3 / 系统配置 5 / 问题排查 3。

#### 2.3 新增与补全清单

| 类型 | 主题（section/topic） | 主要内容要点 |
|---|---|---|
| 新增 | `quick-start/ui-tour` 界面导航 | 顶栏 / 工作区页签 / 侧栏与视图栏 / 内容区工具条；六个常用入口速查；统一交互习惯（单元格编辑、拖拽排序、视图保存规则、窄屏行为） |
| 新增 | `tutorials/documents` 文档：编辑、导入与分享 | 结构树与可见性补链、草稿 / 发布 / 归档三态、版本时间线与回滚、PDF / Office / 图片资产、Obsidian 库导入、匿名只读分享、修改申请 |
| 新增 | `tutorials/analytics` 数据分析与图表 | 数据范围与行级权限共用、公式与实时校验、分组汇总与描述统计、图表类型选择、大模型生成 / 解读（不自动保存）、模板保存与 `?template=` 深链 |
| 新增 | `tutorials/search` 搜索与收藏 | 三档范围（全部 / 数据表 / 文档）与收敛差异、结果分组与跳转、我的视图收藏、拖拽排序按用户保存 |
| 新增 | `configuration/admin` 管理台 | 用户管理、空间分配（快照秒开）、事件流、系统备份（三种模式）、系统恢复（不可撤销）、系统信息 |
| 新增 | `troubleshooting/feedback` 诊断与反馈 | 复现路径 / 环境 / 时间点 / 版本四要素、事件流追溯、问题清单提交、不要贴密钥、提交前自检 |
| 补全 | `tutorials/roles` | 新增表级授权（隐藏字段、数据治理阈值）、行级读范围合成、视图可见性三档、修改申请兜底 |
| 补全 | `tutorials/view-types` | 从 6 种补齐到 10 种模式（新增树 / 矩阵 / 流程）+ 行详情 + 管理与授权 |
| 补全 | `tutorials/field-types` | 按六类重组，补默认值 / 唯一约束 / 自动编号 / 选型建议 |
| 补全 | `tutorials/import-export` | 拆出表头识别、类型推断、更新已有数据、错误行处理、视图配置迁移 |
| 补全 | `configuration/workspace` | 补编辑权限开关的影响、统计与配额、删除 / 转让的危险操作 |
| 补全 | `configuration/datasource` | Provider 分型、凭证会话、调度与运行记录、大规模增量、WAL / VACUUM 维护 |
| 补全 | `tutorials/*` 与 `configuration/*` 交叉引用 | 权限口径统一指向 `roles`，数据落点统一指向 `storage`，删除重复段落 |
| 重写 | `troubleshooting/guide` | 由 5 条扩为 8 个症状域 19 条（登录、权限、导入、文档、同步、大模型、备份、兼容性） |
| 重写 | 示例 3 个主题 | 每个主题统一 4 个 L3：场景说明 / 数据表与下载 / 数据预览 / 怎么练与导入步骤（部分组件化） |

### 3. API 变更清单

无。示例清单与图示接口（ADR 0029/0030）不变。

### 4. 边界与例外

1. 未知 section / topic：仍回落首主题并 replace；未知 hash 只不滚动，不纠正（锚点可能来自旧版本）。
2. 单条目小节不进页内目录展开层：`items.length > 1` 才展开，避免目录与 L3 同名重复。
3. 窄屏（< 768px）：页内目录不渲染，侧栏仍在抽屉；层级完整保留在正文。
4. 内容与代码漂移：字段类型数量、权限枚举仍由图示（ADR 0030）自动生成，正文只写分类与判断依据，不写数量。
5. `scrollIntoView` 缺失（jsdom）：定位失败不抛错，不影响地址栏与阅读。

### 5. 迁移

无。零表变更、零数据迁移、零备份影响；旧深链 `/help/<section>/<topic>` 全部继续有效（主题 key 未改）。

### 6. 前端

| 层 | 文件 | 改动 |
|---|---|---|
| 导航模型 | `helpNav.tsx` | `HelpItem` / `HelpSubsection` / `HelpTopic{intro,subsections}`；`subsectionAnchor` / `itemAnchor` / `helpLink` / `topicAnchors` |
| 渲染器 | `content/HelpDoc.tsx` | 统一生成 `h2` / `h3` 与锚点，正文不再手写标题 |
| 原语 | `content/primitives.tsx` | `P` / `Bullets` / `Steps` / `Note` / `HelpLink` / `Strong` |
| 内容 | `content/{quickStart,tutorials,configuration,troubleshooting,examples}.tsx` | 全部改为声明式四级数据；新增 6 个主题 |
| 示例 | `content/ExamplesSection.tsx` | 拆为 4 个部分组件（Summary / Tables / Previews / Practice），共用 `useExample` |
| 页面 | `HelpDocsPage.tsx` | 右侧「本页目录」（L3 + 多条目小节展开 L4）、锚点点击写 hash、带 hash 进入定位、窄屏不渲染目录 |
| 样式 | `index.css` | `h2`/`h3`、导语、列表、提示块、目录（sticky）与当前项高亮 |

### 7. 测试清单

**导航层（单测）**
- 一级 5 个且顺序固定；section / topic key 唯一；每个主题有 intro。
- 每个主题 ≥2 个 L3；L3「有正文或 ≥2 个 L4」；L4 key / label 小节内唯一且有正文。
- 锚点在主题内唯一；`subsectionAnchor` / `itemAnchor` 输出可直接作 DOM id。
- `topicPath` / `helpLink` 生成地址；`findTopic` 未知参数回落。

**前端组件**
- 正文 L3 渲染 `h2` 且与本页目录一致；L4 渲染 `h3` 并随小节进目录；正文型小节不产生 `h3`。
- 点击目录项高亮并定位到锚点元素；带 `#anchor` 深链直接高亮。
- 窄屏不渲染页内目录与常驻侧栏，抽屉选中后关闭。
- 示例四个部分：清单渲染、鉴权 blob 下载、失败重试、缺省场景。

**e2e**
- 既有链路（入口 → 两级导航 → 刷新 / 后退 → 示例 → 下载 → 窄屏）保持；新增「点击页内目录写入 `#help-row-level` 且锚点元素可见」。

### 8. 分期

| 期 | 内容 | 风险 |
|---|---|---|
| **P0** | 四级模型 + 渲染器 + 页内目录 + 原 16 主题按层级重写 | 低（纯前端） |
| **P1** | 新增 6 个主题、示例小节化、交叉引用收口 | 低（内容为主） |
| **P2** | 层级不变量单测、e2e 锚点断言、样式收尾 | 低 |

## 决策记录（唯一决策台账）

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | 层级怎么加 | 四级：部分 / 主题 / 小节 / 条目，L3 为 `h2`、L4 为 `h3` | 需求点名三、四层；两级不够定位，五级过度设计 | 三级（主题下只有小节）：仍无法区分「小节总述」与「单条实例」 | `helpNav.tsx` |
| D2 | L3 / L4 是否进侧栏 | 不进，改右侧「本页目录」 | 侧栏保持两级（ADR 0029 D4）；四级侧栏在 240px 宽下不可读 | 四级侧栏：挤压正文且与移动端抽屉冲突 | `HelpDocsPage.tsx` |
| D3 | 标题与锚点由谁生成 | 由 `HelpDoc` 从数据统一渲染 | 手写标题必然与目录漂移（现状 3） | 内容里手写 `h2`/`h3` + 另存目录数组：两份真相 | `content/HelpDoc.tsx` |
| D4 | 空壳层级怎么办 | 禁止：L3 必须「有正文或 ≥2 个 L4」 | 单条实例撑不起一个层级，会造成目录噪音 | 允许单条小节：目录与 L3 同名重复 | `helpNav.test.tsx` |
| D5 | 跨主题重复内容怎么处理 | 唯一出处 + `helpLink` 交叉引用 | 权限、数据落点等口径原有多处复制，已出现漂移 | 各主题各写一份：必然漂移 | `primitives.tsx` `HelpLink` |
| D6 | 示例正文怎么有小节 | 拆 4 个部分组件，共用 `useExample` 单次请求 | 保留「清单是唯一来源」且拿到 L3 层级 | 每部分各拉一次独立接口：重复请求 | `ExamplesSection.tsx` |
| D7 | 页内目录是否做滚动高亮 | 不做滚动监听，只做点击 / hash 高亮 | 滚动监听需 IntersectionObserver，收益低且在测试环境不可用 | scroll-spy：额外复杂度 | `HelpDocsPage.tsx` |
| D8 | 是否把帮助正文搬到后端 | 不搬，仍是前端静态内容 | 零表零接口零备份，走现有前端门禁 | 复用文档插件存帮助：引入权限 / 版本 / 备份面 | `content/` |

门禁：`Proposed` → `Accepted` 前本表不得有「待定」。

## Consequences

- **正向**：任意一节可深链分享；主题内部从「一块文字」变成可扫读的 3~8 个小节；产品能力与帮助落点一一对应（新增 6 个主题）；权限等易漂移口径收敛为单点真源。
- **负向**：内容文件从「一个主题一个函数」变成结构化数据，改动需要同时维护 label 与 body；正文总量增加（约 2.5 倍），后续维护成本上升。
- **风险与缓解**：① 层级空壳 → 单测拦截；② 目录与正文漂移 → 同源生成；③ 窄屏信息密度 → 目录不渲染、正文单列；④ 内容与代码漂移 → 数量类事实交给图示，正文只写判断口径。

## 与既有 ADR 的关系

| 轴 | 载体 | 决定 | 由谁 |
|---|---|---|---|
| 帮助路由 / 两级导航 / 示例下载 | `helpNav.tsx`、`plugins/help/` | 本次只在其内部加层级，不改路由与接口 | ADR 0029 |
| 图示 | `figures/registry.py` | 图示继续挂 L3 body，按指纹重建 | ADR 0030 |
| 权限口径 | `roles` 主题 | 三角色 / 视图三档 / 行级合成以本主题为唯一出处 | ADR 0003、0004 |
| 排版口径 | `index.css` | 新样式只用 `--cn-*` 令牌，不引入新特性 | ADR 0031、0026 |

## 落地状态（随实现更新）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 | 已落地 | `frontend/src/pages/help/helpNav.tsx`、`frontend/src/pages/help/HelpDocsPage.tsx`、`frontend/src/pages/help/content/HelpDoc.tsx`、`frontend/src/pages/help/content/primitives.tsx`、`frontend/src/pages/help/content/quickStart.tsx`、`frontend/src/pages/help/content/tutorials.tsx`、`frontend/src/pages/help/content/configuration.tsx`、`frontend/src/pages/help/content/troubleshooting.tsx`、`frontend/src/index.css` | `frontend/src/pages/help/helpNav.test.tsx`、`frontend/src/pages/help/HelpDocsPage.test.tsx` | 851481d3 |
| P1 | 已落地 | `frontend/src/pages/help/content/examples.tsx`、`frontend/src/pages/help/content/ExamplesSection.tsx` | `frontend/src/pages/help/content/ExamplesSection.test.tsx` | 851481d3 |
| P2 | 已落地 | `frontend/tests/e2e/critical/help-docs.spec.ts`、`frontend/src/index.css` | `frontend/tests/e2e/critical/help-docs.spec.ts` | 16eea08b |

> 状态只取「未开始 / 进行中 / 已落地」。标「已落地」的期必须有代码落点与测试文件；全期落地后由人确认 `Status` 是否改 `Accepted` / `Implemented`。`make adr-check` 会校验本表与代码、测试、CHANGELOG 的对应关系。

## 交接（会话结束更新）

- 当前阶段：P0 / P1 / P2 全部落地，待 `make flow` 与 e2e 复跑确认
- 已完成：四级模型（5 / 22 / 114 / 78）、页内目录与锚点深链、6 个新主题、示例小节化、权限与数据落点口径收口、层级不变量单测
- 下一步：`make flow` + `make e2e`（`help-docs.spec.ts`）复跑；后续新增主题只需在对应 `content/*` 里加 `HelpTopic` 并挂到 `HELP_SECTIONS`
- 已知坑：L3 / L4 的 `key` 一旦发布不要再改（锚点即外链）；单条目小节不会在目录里展开 L4；`HelpDoc` 是唯一渲染入口，内容文件里禁止手写 `h2`/`h3`；示例四个部分共用 `['help','examples']` 查询，新增部分不要另起 queryKey
- 最近一次全绿：`frontend` 定向 4 文件 32 用例 + `pnpm typecheck` + `pnpm eslint src/pages/help`（2026-10-26）
