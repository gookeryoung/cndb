# 需求卡片：dashboard 整屏导出与登录态只读分享

- 编号：0077（与 ADR `docs/adr/0077-*.md` 同号，卡片存 `docs/requirements/0077-<topic>.md`）
- 来源 / 提出人：ADR 0023 §9 P3 遗留项（用户口述「整屏导出 / 只读分享立 ADR」）
- 日期：2026-11-01
- 关联 ADR：`docs/adr/0077-dashboard-fullscreen-export-readonly-share.md`（Proposed）

> 本卡片是**需求原文与约束编号的唯一副本**：ADR 只引用 C1..Cn，不复制原文；需求澄清后先改这里，再同步 ADR「口径」表。

## 需求原句（逐字）

> 整屏导出 / 只读分享

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 整屏导出 | 一次导出**整个 dashboard 画布**（全部 widget 按当前布局同屏输出），不是逐卡分别导出 | `frontend/src/pages/grid/views/dashboard/` | 前端单测：捕获目标含全部卡片；e2e 下载文件非空 |
| C2 | 整屏导出 | 导出入口在画布工具栏内，**只读用户也可用**，不要求编辑视图权限 | `DashboardView.tsx`、`GridPage.tsx` | 只读身份下工具栏可见导出入口 |
| C3 | 整屏导出 | 导出 PNG 图片与 PDF；沿用前端既有 `html2canvas-pro` / `jsPDF`，不新增后端导出依赖 | `frontend/src/pages/import-export/ImportExportDialog/` | 依赖清单无新增；导出路径动态导入 |
| C4 | 整屏导出 | 导出内容为当前渲染结果（全局筛选后的数据、卡片标题与取数口径提示、空态 / 错误态照实输出）；排除应用导航与画布工具栏；不改变取数口径与权限 | `DashboardView.tsx`、`exportPdf.ts` | 捕获目标断言；导出前后权限行为不变 |
| C5 | 只读分享 | 提供可复制的**只读链接**；接收者打开后进入只读展示，无编辑、配置、删除、新增组件入口 | `GridPage.tsx`、`GridViewBar.tsx`、`DashboardView.tsx` | 展示态组件单测 + e2e 角色回归 |
| C6 | 只读分享 | **不新增匿名入口**（保持 ADR 0003 D5、ADR 0017 C10）；接收者仍须具备表 `READ` 与视图可见性，行级权限 / 字段隐藏照常生效 | `view_access.py`、`GridPage.tsx` | 未登录跳登录；越权视图不回落默认视图 |
| C7 | 只读分享 | 分享范围沿用视图三档可见性（`private` / `shared` / `table`）与既有授权名单；链接本身不创建或扩大权限 | `ViewPermissionDrawer.tsx`、`view_access.py` | 复用既有视图权限测试；链接不携带授权信息 |
| C8 | 只读分享 | 链接含 `view` / `mode=dashboard` / `present=1`，刷新、转发可直达；视图删除、转私密、收回授权、表 / 工作区删除后按既有 404 / 403 失效 | `GridPage.tsx`、`dashboardShare.ts` | 纯函数单测 + e2e 撤销后失效 |
| C9 | 只读分享 | 展示态隐藏页面级工具栏与写入口，窄屏按单列塌陷；保留刷新、导出与退出展示 | `GridPage.tsx`、`DashboardView.tsx` | 组件断言工具栏隐藏 / 保留项 |
| C10 | 整屏导出 | 不改动既有 PDF 导出默认行为；新增导出代码动态导入，不进入首屏与主入口 chunk | `exportPdf.ts`、`frontend/scripts/bundle-budget.json` | `pnpm build` + `pnpm bundle:budget` 通过 |
| C11 | 整屏导出 / 只读分享 | 无新增后端端点、无新增表 / 列 / 迁移；后端权限判定复用现有唯一入口 | `plugins/tables` | `make check-docs` / 后续实现轮 `make check` |

约束编号在 ADR 中原样引用；不重编号、不合并。

## 现状影响面（候选，待 ADR 核实）

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | 画布工具栏仅编辑权限可见 | `frontend/src/pages/grid/views/dashboard/DashboardView.tsx:406` | 只读用户没有导出 / 刷新入口 |
| 2 | 单卡 PNG 导出 | `frontend/src/pages/grid/views/dashboard/widgets/ChartWidget.tsx:79` | 仅单个图表，不能整屏 |
| 3 | 通用视图 PDF 导出 | `frontend/src/pages/import-export/ImportExportDialog/ExportPanel.tsx:65`、`exportPdf.ts:209` | 可复用渲染与分页逻辑 |
| 4 | 通用 PDF 捕获目标 | `frontend/src/pages/grid/GridPage.tsx:1170`、`:1355` | 包含 dashboard 工具栏，需专用捕获区 |
| 5 | 视图访问判定 | `src/cndb/plugins/tables/services/core/view_access.py:46`、`:215` | 只读分享必须复用，不得旁路 |
| 6 | 视图权限抽屉 | `frontend/src/pages/grid/gridViewBar.tsx:291` | 分享范围沿用三档可见性 |
| 7 | URL 视图深链 | `frontend/src/pages/grid/GridPage.tsx:426` | 可用于只读链接，无需新路由 |
| 8 | 展示参数未处理 | `frontend/src/pages/grid/GridPage.tsx:363`、`:437` | `present=1` 尚未定义 |
| 9 | 行详情入口 | `frontend/src/pages/grid/GridPage.tsx:1274` | 展示态应禁用，避免进入写路径 |
| 10 | 导出依赖 | `frontend/package.json:56` | `html2canvas-pro` / `jspdf` 已存在 |
| 11 | 体积预算 | `frontend/scripts/bundle-budget.json` | 新导出代码需动态导入 |
| 12 | 匿名分享已移除 | `docs/adr/0003-view-visibility-permission-model.md:211` | 只读分享不得复活匿名链接 |
| 13 | dashboard 取数状态 | `frontend/src/pages/grid/views/dashboard/useDashboardData.ts:56` | 导出前须等待数据就绪 |

> 编号与 ADR「Context」表对齐：ADR 逐条给「确认 / 排除 / 新增」并补齐 `file:line`。本阶段只粗查，精查归 ADR。

## 未决问题

- [x] 分享形态 → **登录态只读深链 + 展示态**；不新增匿名链接（依据 ADR 0003 D5、ADR 0017 C10）。
- [x] 导出范围 → 全局筛选栏 + 画布主体，排除应用导航与画布工具栏。
- [x] 导出格式 → PNG（默认）+ PDF（可选），复用现有前端库。
- [x] 分享设置落点 → 复用既有「视图权限」抽屉；只读链接复制入口置于视图栏与画布工具栏。
- [x] 需求方 / 评审确认：以上口径按仓库既有约束收敛；ADR 0077 已评审通过（Status: Accepted），P0-P2 已落地（实现提交 `b9ccd0b8`）。

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [x] 未决问题全部有结论；最后一条人工评审确认项已随 ADR 0077 评审关闭
