# 需求卡片：设计模块二级导航与设计结构装配树

- 编号：0083
- 来源 / 提出人：用户
- 日期：2026-11-01
- 关联 ADR：`docs/adr/0083-design-structure-subnav-and-assembly-tree.md`（S2：编译产物新增结构大纲，属 IR 双端契约演进）

> 本卡片是**需求原文与约束编号的唯一副本**：ADR 只引用 C1..Cn，不复制原文；需求澄清后先改这里，再同步 ADR「口径」表。

## 需求原句（逐字）

> 【设计】一级模块参考【文档】模块完善，增加【设计结构】二级导航入口作为默认页。使用树形结构展示不同装配层级的组件和零件。

需求澄清结论（用户已确认，2026-11-01）：
1. 装配树口径取**方案 A**（单设计内派生树）：工作区顶层为设计清单，每份设计展开显示其装配树——`module` 实例 = 组件（可嵌套即不同装配层级），图元 = 零件；跨设计 BOM 引用（方案 B）不纳入本期。
2. 范围仅「二级导航入口 + 默认页」：不引入设计区文件夹、修改申请、问题清单等文档模块的其他能力（沿用 ADR 0079 D6 排除双轨）。
3. 节点带 **DSL 源位置**：组件 / 分组 / 零件节点均携带 1 基行列，树中展示并可点击定位到编辑器对应行。

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 「参考【文档】模块完善，增加【设计结构】二级导航入口」 | `MainLayout` 新增 `DESIGN_SUBPAGES`（仅一项「设计结构」，`to: ''`，icon `ApartmentOutlined`），形态与 `DOCUMENT_SUBPAGES` / 表级页签一致（竖线分隔的 `cn-table-tab` 按钮 + `role="tab"` + `data-testid`）；进入 `/w/:wid/design*` 时渲染；落在 `/w/:wid/design`（无子段）时该页签激活，编辑器 `/w/:wid/design/:id` 显示页签但无子页激活 | `frontend/src/layouts/MainLayout.tsx` | `MainLayout.test.tsx` 新增用例 |
| C2 | 「作为默认页」 | `/w/:wid/design` 由平面列表改为「设计结构」树页（改造既有 `DesignsPage`，不新增路由）：既有能力全部保留——新建（示例模板）、打开、改名 / 描述、删除；工作区落地段（`workspaceLandingSegment` = design）落到本页即为结构树 | `frontend/src/pages/design/DesignsPage.tsx` | 前端单测主流程 + 既有列表操作回归 |
| C3 | 「使用树形结构展示不同装配层级的组件和零件」 | 树层级：设计（根）→ 组件（DSL `module` 实例，可嵌套）→ 结构分组（布尔块 union / difference / intersection）→ 零件（六种图元）；变换不入树（信息已下推到图元 `transform`）。层级数据由后端编译链路与 IR 同源产出（前端零解析，ADR 0079 I1），IR 新增顶层 `outline`，`version` 升至 2 | `src/cndb/plugins/design/services/dsl/`、`design/routers.py`、`design/schemas.py` | 判定层单测（大纲结构与 IR 一致性、嵌套层级、行号）+ 接口层用例 |
| C4 | 「节点带 DSL 源位置」（澄清结论 3） | 每个大纲节点携带 1 基 `line` / `col`（语句起始位置）；前端树节点展示「第 N 行」，点击组件 / 分组 / 零件节点打开编辑器并定位到该行（`/w/:wid/design/:id?line=N`，编辑器初始光标与滚动到该行） | `frontend/src/pages/design/`、`src/cndb/plugins/design/services/dsl/compile.py` | 前端单测（节点文案 / 跳转 URL）+ 后端单测（行号取值） |
| C5 | 配套回归 | 设计模块门控（`wsFeatures.design` + URL 门控重定向）回归；帮助文档「工作区二级页签」与设计主题文案同步；CHANGELOG 记录；e2e `navigation.spec.ts` 补设计结构页签断言，新增结构树 e2e | `CHANGELOG.md`、`frontend/src/pages/help/content/*`、`frontend/tests/e2e/critical/navigation.spec.ts` | `make flow` + `make e2e` |

约束编号在 ADR 中原样引用；不重编号、不合并。

## 现状影响面（候选，已核实）

| # | 疑似受影响能力 | 位置 | 备注 |
|---|---|---|---|
| 1 | 文档区二级页签范式（文档结构 / 质量检查 / 修改申请 / 问题清单） | `frontend/src/layouts/MainLayout.tsx:58-63`、`:905-932` | C1 照抄形态；「文档结构」默认页先例见卡片 0082 |
| 2 | 设计区已有 `inDesignContext` / URL 门控分支但无二级页签 | `frontend/src/layouts/MainLayout.tsx:391`、`:433-439` | C1 改造点 |
| 3 | 设计路由：`/w/:wid/design`（列表）+ `/w/:wid/design/:id`（编辑器） | `frontend/src/App.tsx:102-106` | C2 改造点（复用路由，只换页面内容） |
| 4 | IR 把模块实例内联展开，不保留装配层级 | `src/cndb/plugins/design/services/dsl/compile.py:319-331` | C3 关键缺口：需在 `_Emitter` 同步产出 outline |
| 5 | 设计列表页现为平面 Listy（新建 / 改名 / 删除 / 描述） | `frontend/src/pages/design/DesignsPage.tsx` | C2 改造点，能力须保留 |
| 6 | 设计模块排除双轨修改申请（D6） | `docs/adr/0079-design-3d-dsl-module.md` | 二级页签不引入修改申请 / 问题清单 |
| 7 | 设计功能门控 `wsFeatures.design` | `frontend/src/layouts/MainLayout.tsx:289-291` | C5 回归面 |
| 8 | 编辑器无「按行定位」能力（`DslEditor` 仅诊断装饰） | `frontend/src/pages/design/DslEditor.tsx`、`DesignEditorPage.tsx` | C4 新增 `revealLine` 能力 |
| 9 | 设计帮助主题已存在 | `frontend/src/pages/help/content/tutorials.tsx` | C5 文案同步点 |

## 未决问题（已全部有结论）

- [x] ① 装配树语义口径 → 方案 A（单设计内派生树），见澄清结论 1。
- [x] ② 「参考文档模块完善」范围 → 仅二级导航 + 默认页，见澄清结论 2。
- [x] ③ 节点颗粒度 → 名称 / 类型 / 源行号 + 点击定位；实例计数由前端按树children 派生，不落后端，见澄清结论 3 与 C4。

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [x] 未决问题全部有结论，需求方确认（2026-11-01）
