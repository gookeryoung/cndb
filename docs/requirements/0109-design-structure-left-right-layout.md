# 需求卡片：设计模块单一工作台（侧栏产品列表 ↔ 结构树，Content = DSL / 视图）

- 编号：0109（与 ADR `docs/adr/0109-*.md` 同号；S2 项，方案见 ADR）
- 来源 / 提出人：用户
- 日期：2026-11-06（同日修订：由「根页左右分栏」改为「侧栏共享 + 就地钻孔」）
- 关联 ADR：`docs/adr/0109-design-structure-left-right-layout.md`（S2，Proposed）

> 本卡片是**需求原文与约束编号的唯一副本**：ADR 只引用 C1..Cn，不复制原文；需求澄清后先改这里，再同步 ADR「口径」表。

## 需求原句（逐字）

> 设计的UI布局应当进行优化，产品列表和结构树共享侧边栏，选取产品后就地切入结构树，Content区域留给DSL编辑和视图

## 澄清结论（2026-11-06 用户确认）

- Q1 页面形态：**合并为单一工作台** —— `/w/:wid/design/:id` 与根页 `/design` 共用同一页面，侧栏承载产品列表 / 结构树，Content 只放 DSL 编辑器 + 3D 视图。
- Q2 默认选中：进入设计模块（`/design` 无具体产品）时**自动打开最近更新的产品**。
- Q3 列表入口：新建 / 类型筛选 / 搜索 / 改名 / 删除**全部收进侧栏产品列表态**，Content 不再有页头。

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 「产品列表和结构树共享侧边栏」 | 设计模块只保留一个侧栏（桌面 Sider / 移动抽屉共用同一组件），侧栏有「产品列表」与「结构树」两态，互斥渲染；全仓不再出现同屏两份产品列表或两棵树 | `frontend/src/layouts/MainLayout.tsx`、`frontend/src/pages/design/*` | 前端单测（侧栏两态互斥、同时只有一个 testId 可见） |
| C2 | 「选取产品后就地切入结构树」 | 在侧栏产品列表点击产品：URL 切到 `/w/:wid/design/:id`，侧栏就地切为该产品的结构树态（不新开页面 / 不跳管理页）；结构树态头部提供「产品列表」返回键，返回时 URL 保持不变（Content 继续显示当前产品编辑器）；大纲节点点击沿用 `?line=` 定位 | `frontend/src/pages/design/DesignStructureNav.tsx`（或替代组件）、`frontend/src/pages/design/DesignsPage.tsx` | 前端单测（选中 → 树态 + URL；返回 → 列表态 + URL 不变；节点点击带 `?line=`） |
| C3 | 「Content区域留给DSL编辑和视图」 | `/design/:id` 的 Content 仅渲染现有编辑器工作台（工具栏 + 诊断 + DSL + 3D 预览 + 参数面板）；原根页的页头、`cn-qc-split` 双栏、产品列表 / 结构树全部移出 Content；编辑器工具栏不再保留指向管理页的返回箭头（由侧栏返回键承担） | `frontend/src/pages/design/DesignEditorPage.tsx`、`frontend/src/pages/design/DesignsPage.tsx`、`frontend/src/index.css` | 前端单测（Content 无 `cn-qc-split` / 页头；编辑器工具栏无返回管理页链接） |
| C4 | （入口收进侧栏） | 侧栏产品列表态顶部承载搜索、类型筛选（全部 / 零件 / 装配）与「新建设计」；行内保留名称 / 类型 / 目录 / 依赖陈旧 / 版本 / 更新时间，行尾动作 打开 / 编辑 / 删除；viewer 只读门控不变 | `frontend/src/pages/design/DesignsPage.tsx` | 前端单测（筛选 / 搜索 / 新建 / 改名 / 删除 / viewer 门控回归） |
| C5 | （默认选中与空态） | `/design` 无具体产品时取最近更新的设计并以 `replace` 跳到 `/design/:id`；工作区无设计时侧栏仍显示空列表 + 新建入口，Content 显示「还没有结构设计」引导空态；选中产品被删除时回落到最近更新的其余产品，全部删除则回根页空态 | `frontend/src/pages/design/DesignsPage.tsx`、`frontend/src/pages/design/DesignEditorPage.tsx` | 前端单测（根页重定向 / 无设计空态 / 删除回落） |
| C6 | （配套回归） | 设计上下文（根页 + 编辑器页）始终渲染侧栏，移除 `onDesignRoot` 隐藏分支；移动端汉堡入口同样可用；样式新增类走 `--cn-*` token、断点只用既有 `1023.98px / 767.98px`；ADR 0084 D4 / D5、ADR 0103 相关失效行随实现改写引用 ADR 0109；单测 / e2e / 帮助文案 / CHANGELOG 同步 | `frontend/src/layouts/MainLayout.tsx`、`frontend/src/index.css`、`docs/adr/0084-*.md`、`docs/adr/0103-*.md`、`frontend/tests/e2e/critical/*` | `make flow` + 目标 e2e 全绿；`make adr-check` 通过 |

## 现状影响面（已核对）

| # | 受影响能力 | 位置 | 备注 |
|---|---|---|---|
| 1 | 根页左右分栏（产品列表 + 结构树） | `frontend/src/pages/design/DesignsPage.tsx` | 整页形态退役；列表 / 筛选 / 新建 / 改名 / 删除迁入侧栏 |
| 2 | 设计上下文侧栏渲染条件（根页隐藏） | `frontend/src/layouts/MainLayout.tsx` | 改为设计上下文始终渲染 |
| 3 | 侧栏装配树（设计清单 + 大纲树） | `frontend/src/pages/design/DesignStructureNav.tsx` | 改为「产品列表 ↔ 单产品结构树」两态 |
| 4 | 编辑器工具栏返回箭头 | `frontend/src/pages/design/DesignEditorPage.tsx` | 移除（侧栏返回键承担） |
| 5 | 设计路由 | `frontend/src/App.tsx` | 根页保留为选择 / 重定向页，编辑器页不变 |
| 6 | 样式 | `frontend/src/index.css` | `.cn-ds-outline-tree` 等根页专用类退役 |
| 7 | 单测 / e2e | `DesignsPage.test.tsx`、`DesignStructureNav.test.tsx`、`MainLayout.test.tsx`、`frontend/tests/e2e/critical/design-*.spec.ts` | 断言改写为侧栏两态 |
| 8 | 既有 ADR 失效行 | `0084` D4 / D5、`0103` C8 / D12 / 交接 | 改写并引用 ADR 0109 |

## 未决问题

- [x] Q1 页面形态：合并为单一工作台 —— ADR 0109 D1
- [x] Q2 默认选中：自动打开最近更新产品 —— ADR 0109 D3
- [x] Q3 列表入口：收进侧栏产品列表态 —— ADR 0109 D2
- [x] Q4 结构树返回：返回键只切侧栏态、URL 不变 —— ADR 0109 D4

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [x] 未决问题全部有结论（结论落在 ADR 0109 决策记录 D1–D8；卡片随 ADR 一并评审）
