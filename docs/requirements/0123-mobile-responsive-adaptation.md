# 需求卡片：全站移动端显示适配专项

> 需求原文与约束编号 C1..Cn 的唯一副本在本卡片，ADR 只引用不复制（H26）。

- 编号：0123
- 来源 / 提出人：用户（2026-11-08 会话）
- 日期：2026-11-08
- 关联 ADR：`docs/adr/0123-mobile-responsive-adaptation.md`

> 本卡片是**需求原文与约束编号的唯一副本**：ADR 只引用 C1..Cn，不复制原文；需求澄清后先改这里，再同步 ADR「口径」表。

## 需求原句（逐字）

> 请针对当前项目在手机端的显示适配，制定开发计划。如工作区列表当前完全看不到名称了。请给出建议方案。

会话内补充确认（2026-11-08）：

> 范围与定级：「先修 P0 + 立项 S2 专项」；整体策略：「响应式优先」；网格数据表页手机端形态：「横向滚动 + 首列冻结」。

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 手机端的显示适配 | 核心页面在 <768px 视口（375px 基准）可用：无横向溢出、关键信息（名称 / 标题）可读、触控目标不小于既有口径（24px 行内图标 / 32px 顶栏控件，ADR 0044 I4） | frontend | 移动视口页面单测 + e2e 冒烟 |
| C2 | 工作区列表当前完全看不到名称了 | 移动端收起态行内名称完整可读（省略号截断而非挤压为 0）；角色徽标保留 | `frontend/src/pages/workspace/WorkspaceList.tsx`、`frontend/src/index.css` | `WorkspaceList.test.tsx` 移动端用例（已随 S0 热修复落地） |
| C3 | 制定开发计划（整体策略） | 响应式优先：一套代码 + 断点适配，不新建移动端独立路由 / 页面 | frontend | 代码评审 + `make check-fast` |
| C4 | 网格数据表页手机端形态（会话确认） | 网格页移动端保持表格形态：容器横向滚动 + 首列冻结（吸附），行详情走既有 RowDetailDrawer | `frontend/src/pages/grid/` | GridPage 移动端单测 |
| C5 | 既有能力与入口不丢失 | 移动端不删减功能入口（次级入口可收进「更多」菜单，对齐 ADR 0044 C5 口径）；桌面端（≥768px）零回归 | frontend | 桌面端既有用例断言不变 |
| C6 | 断点体系 | 沿用 `useResponsive` 768 / 1024 / 1280 断点，不新增断点 | `frontend/src/hooks/useResponsive.ts` | `make check-fast` |
| C7 | 适配实现口径收敛 | 样式型适配（间距 / 字号 / 显隐 / flex 占比）收敛到 `index.css` 媒体查询层；`useResponsive` 的 JS 分支只用于结构性切换（渲染不同组件 / 布局分支） | `frontend/src/index.css`、各页面 | 代码评审 |
| C8 | 复杂交互兜底 | 3D 设计编辑器等复杂交互在移动端只读兜底（可查看 / 不承诺编辑），不做移动端编辑能力 | `frontend/src/pages/design/` | 页面单测 |
| C9 | 测试门禁 | 专项触及的页面补移动端（375px 视口）单测；移动视口 e2e 冒烟（关键路径：登录 → 工作区列表 → 进入工作区）加入 critical 套件 | `frontend/tests/e2e/critical/` | `make flow` |

约束编号在 ADR 中原样引用；不重编号、不合并。

## 现状影响面（候选，待 ADR 核实）

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | 工作区列表行内名称被模块徽标挤压为 0 | `frontend/src/pages/workspace/WorkspaceList.tsx:543-548`、`frontend/src/index.css:1326-1341` | 已随 S0 热修复（2026-11-08） |
| 2 | CSS 媒体查询仅 6 处，移动适配主要靠 JS `isMobile` 内联样式散落各页 | `frontend/src/index.css`、33 个页面文件 | C7 主缺口 |
| 3 | 全局壳层（顶栏 / 抽屉导航 / 移动搜索 / 页签简化）已有移动端基础 | `frontend/src/layouts/MainLayout.tsx:144-1080` | 走查收尾即可 |
| 4 | 文档列表页已按 ADR 0044 完成移动端紧凑化 | `frontend/src/pages/documents/DocumentsPage.tsx` | 范式参考，不重做 |
| 5 | 网格数据表页移动端形态未定 | `frontend/src/pages/grid/GridPage.tsx`、`frontend/src/pages/grid/gridViewBar.tsx` | C4 主缺口 |
| 6 | Modal / Drawer 移动端宽度未全量规约（部分已 `calc(100vw - 32px)`） | 各页 Modal（如 `WorkspaceList.tsx:356`、`:878`） | P1 规约 |
| 7 | 设计 3D 编辑器移动端可用性未知 | `frontend/src/pages/design/DesignEditorPage.tsx` | C8 |
| 8 | 模板结构化编辑器（ADR 0121，已随功能移除）移动端形态 | — | 不再实施 |
| 9 | admin 管理台页面移动端未适配 | `frontend/src/pages/admin/` | P3 兜底 |
| 10 | e2e 无移动视口用例 | `frontend/tests/e2e/` | C9 |

> 编号与 ADR「Context」表对齐：ADR 逐条给「确认 / 排除 / 新增」并补齐 `file:line`。本阶段只粗查，精查归 ADR。

## 未决问题

- [x] 范围与定级：先修 P0（S0 热修复）+ 立项 S2 专项 —— 用户 2026-11-08 确认
- [x] 整体策略：响应式优先 —— 用户 2026-11-08 确认
- [x] 网格页手机端形态：横向滚动 + 首列冻结 —— 用户 2026-11-08 确认

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [x] 未决问题全部有结论，需求方确认
