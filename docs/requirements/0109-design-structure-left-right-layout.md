# 需求卡片：设计结构页左右分栏（对齐质量检查 / 修改申请风格）

- 编号：0109（与 ADR `docs/adr/0109-*.md` 同号；S2 项，方案见 ADR）
- 来源 / 提出人：用户
- 日期：2026-11-06
- 关联 ADR：`docs/adr/0109-design-structure-left-right-layout.md`（S2，Proposed）

> 本卡片是**需求原文与约束编号的唯一副本**：ADR 只引用 C1..Cn，不复制原文；需求澄清后先改这里，再同步 ADR「口径」表。

## 需求原句（逐字）

> 设计结构的UI布局也参考数据表质量检查、修改申请的设计风格，采取左右布局设计，左侧为产品列表，右侧为具体结构树。

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 「参考数据表质量检查、修改申请的设计风格」 | `/w/:wid/design` 根容器改为 `cn-page cn-qc-page` + `cn-page-head` 紧凑页头（`ApartmentOutlined` 图标、标题「设计结构」、口径副标题「左侧产品列表、右侧选中产品的结构树」）；类型筛选 `Segmented`（全部 / 零件 / 装配）与「新建设计」主按钮上移页头；内容经 `SectionBox` 方盒 + `.cn-qc-row` 行态组织，弃用 `maxWidth: 960` 居中单栏与 `cn-design-structure` / `cn-design-folder*` 旧类 | `frontend/src/pages/design/DesignsPage.tsx`、`frontend/src/index.css` | 前端单测（页头标题 / 双栏 testId / 筛选器迁移断言） |
| C2 | 「采取左右布局设计」 | 主区改为 `cn-qc-split` 双栏（窄屏由既有断点收为纵向堆叠）：左 `SectionBox`「产品列表」（extra 计数「共 N 个」），右 `SectionBox`「结构树」（标题带选中产品名，未选中时为「结构树」） | `frontend/src/pages/design/DesignsPage.tsx` | 前端单测（`design-products-box` / `design-outline-box` 双栏 testId） |
| C3 | 「左侧为产品列表」 | 左栏 = 设计清单可选列表（`role=listbox/option`、`cn-qc-row--selectable/--active` 选中态）：行内名称 + 零件 / 装配 Tag + 目录 Tag + 「依赖陈旧」Tag + `v{version_count}` + 更新时间；**扁平列表**（0103 C8 目录分组形态退役，目录改行内 Tag）；点击选中（再点取消），行尾 hover 动作保留 打开 / 编辑 / 删除；页头 `Segmented` 过滤左栏 | `frontend/src/pages/design/DesignsPage.tsx` | 前端单测（选中 / 取消 / 筛选 / 新建 / 改名 / 删除主流程回归） |
| C4 | 「右侧为具体结构树」 | 右栏展示**选中产品**的装配树：复用 `designOutline.ts` 映射与 `GET /designs/{id}/outline`（懒加载 + 本页缓存，IR 快照缓存优先口径与侧栏一致）；树根 = 产品名（点击进编辑器），层级 系统 → 组件 → 分组 → 零件，节点带类型 / 行号 / 零件数；**默认选中最近更新的设计**（对齐需求 0107 默认选中口径），选中项被删除 / 被筛掉时自动回落到列表首个；未选中空态「选择左侧产品查看结构树」，清单为空空态「还没有结构设计」 | `frontend/src/pages/design/DesignsPage.tsx`、`frontend/src/pages/design/designOutline.ts`（只读复用，不改映射） | 前端单测（默认选中 / 懒加载触发 / 空态 / 选中失效回落） |
| C5 | （布局重构不减能力） | 节点点击交互与侧栏口径一致：设计根 / 大纲节点 → `designEditorPath`（大纲节点带 `?line=` 定位源行）；管理能力不减少（新建 / 改名 / 描述 / 删除 Modal 与模板内容原样保留）；viewer 只读（无新建 / 编辑 / 删除入口） | `frontend/src/pages/design/DesignsPage.tsx` | 前端单测（跳转 URL 含 `?line=`、viewer 门控） |
| C6 | （配套回归） | 「设计结构」根页不再渲染模块侧栏（`siderMode='design'` 仅 `/design/:id` 编辑器页保留，避免与右栏双树冗余；0103 C1 双向定位闭环不动）；样式新增类全部走 `--cn-*` token、断点只用既有 `1023.98px / 767.98px`；ADR 0084 D4 / D5、ADR 0103 D12 失效行随实现改写引用 ADR 0109；`MainLayout` / `DesignsPage` 单测与 e2e（`design-structure-tree` / `design-sidebar-assembly`）同步；CHANGELOG 记录 | `frontend/src/layouts/MainLayout.tsx`、`frontend/src/index.css`、`docs/adr/0084-*.md`、`docs/adr/0103-*.md`、`frontend/tests/e2e/critical/*` | `make flow` + 目标 e2e 全绿；`make adr-check` 通过 |

## 现状影响面（候选，已粗查）

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | 设计管理页布局（居中列表 + 目录分组） | `frontend/src/pages/design/DesignsPage.tsx:258-315` | 本次重构对象；mutation / Modal / 模板不动 |
| 2 | 模块侧栏渲染条件 | `frontend/src/layouts/MainLayout.tsx:449-456`、`:759-769` | `siderMode='design'` 需排除根页；编辑器页不动 |
| 3 | 设计页样式类 | `frontend/src/index.css`（`.cn-design-structure` / `.cn-design-folder*`） | 旧类退役，复用 `cn-qc-*` 原语，新增 `.cn-ds-*` 排版类 |
| 4 | 前端单测 | `frontend/src/pages/design/DesignsPage.test.tsx`、`frontend/src/layouts/MainLayout.test.tsx` | 列表用例改写为双栏口径；侧栏渲染条件补根页分支 |
| 5 | e2e | `frontend/tests/e2e/critical/design-structure-tree.spec.ts`、`design-sidebar-assembly.spec.ts` | 主区结构树断言回归；补根页无侧栏断言 |
| 6 | 既有 ADR 失效行 | `docs/adr/0084-design-sidebar-assembly-and-system-level.md`（D4/D5）、`docs/adr/0103-design-editor-layout-optimization.md`（D12） | 随实现改写并引用 ADR 0109；落地状态 / 交接 / CHANGELOG 同步 |
| 7 | 帮助文案 | `frontend/src/pages/help/content/*`（设计模块页形态描述） | 触及处同步为左右分栏口径 |

## 未决问题

- [x] Q1 左栏组织：扁平列表 + 目录 / 类型行内 Tag（替代 0103 目录分组）——结论见 ADR 0109 D2（2026-11-06 编制 ADR 时定稿，随 ADR 评审确认）
- [x] Q2 右栏默认：默认选中最近更新的设计并立即懒加载大纲——结论见 ADR 0109 D3
- [x] Q3 节点点击：与侧栏口径一致（设计根 / 大纲节点进编辑器，大纲节点带 `?line=` 定位）——结论见 ADR 0109 D5
- [x] Q4 侧栏去留：根页隐藏、编辑器页保留（双向定位闭环不动）——结论见 ADR 0109 D4

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [x] 未决问题全部有结论（结论落在 ADR 0109 决策记录 D2–D5；卡片随 ADR 一并评审）
