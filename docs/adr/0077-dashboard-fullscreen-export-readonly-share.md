# ADR 0077: dashboard 整屏导出与登录态只读分享

Status: Accepted
Date: 2026-11-01
Related: `frontend/src/pages/grid/views/dashboard/DashboardView.tsx`、`frontend/src/pages/grid/views/dashboard/DashboardGrid.tsx`、`frontend/src/pages/grid/views/dashboard/widgets/ChartWidget.tsx`、`frontend/src/pages/grid/views/dashboard/useDashboardData.ts`、`frontend/src/pages/grid/GridPage.tsx`、`frontend/src/pages/grid/gridViewBar.tsx`、`frontend/src/pages/grid/ViewPermissionDrawer.tsx`、`frontend/src/pages/import-export/ImportExportDialog/exportPdf.ts`、`frontend/src/pages/import-export/ImportExportDialog/ExportPanel.tsx`、`src/cndb/plugins/tables/services/core/view_access.py`、`docs/adr/0023-configurable-view-dashboard.md`、`docs/adr/0003-view-visibility-permission-model.md`、`docs/adr/0017-guest-document-share.md`
需求卡片: `docs/requirements/0077-dashboard-fullscreen-export-readonly-share.md`（需求原文与约束编号的唯一副本）

## 口径（需求 → 设计落点）

需求原文：见需求卡片 §需求原句（逐字，ADR 不复制第二份）。

| 卡片约束 # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | 整屏导出 | 新增画布级捕获目标：按 `normalizeLayout` 当前布局一次性把全部 widget 渲染进同一张 PNG / PDF；单卡 PNG 保留为快捷入口，不替代整屏 |
| C2 | 整屏导出 | `DashboardView` 工具栏从「仅 `canEdit`」改为「所有可见者」；导出 / 刷新 / 复制链接不要求 `EDIT_VIEWS`（D5） |
| C3 | 整屏导出 | PNG（默认）与 PDF（可选）；复用 `html2canvas-pro` + `jsPDF`，两者继续在导出点击时动态导入（D3） |
| C4 | 整屏导出 | 捕获区 = 全局筛选栏 + 画布主体；排除画布工具栏与应用导航；背景取当前主题页面色，空 / 错状态照实输出（D4） |
| C5 | 只读分享 | 「复制只读链接」生成带 `view` / `mode=dashboard` / `present=1` 的深链；打开即进入只读展示（D6 / D7） |
| C6 | 只读分享 | 不新增匿名入口，不新增 share token；接收者走既有登录态 + 表 `READ` + 视图可见性判定（D2 / D8） |
| C7 | 只读分享 | 可见范围沿用视图三档（`private` / `shared` / `table`）与既有授权名单；分享设置直接复用「视图权限」抽屉（D8） |
| C8 | 只读分享 | 展示态要求 `view` 必须解析成功，**不回落到默认视图**；不可见 / 已删 / 非 dashboard 视图按「链接无效」处理（D9） |
| C9 | 只读分享 | 展示态隐藏 `GridToolbar` / `GridViewBar` / 聚合条与行详情入口，保留刷新、导出、退出展示；窄屏沿用单列塌陷（D7） |
| C10 | 整屏导出 | 既有 `ExportPanel` 的 PDF 默认行为不变；新增导出辅助函数按需导入，不进入 `GridPage` / `DashboardView` 主 chunk（D10） |
| C11 | 整屏导出 / 只读分享 | 零后端端点、零表结构、零迁移；权限判定复用 `get_table_or_404` + `get_view_or_404`（D1 / D8） |

决策结论只在「决策记录」写一次；本节与正文不再罗列「已确认决策」。

## Context

现状逐条核对（以代码为准，标注 `文件:行号`）。沿用卡片「现状影响面」编号，ADR 新发现项从 14 起编号。

| # | 现状 | 位置 | 影响 | 与卡片的关系 |
|---|---|---|---|---|
| 1 | 画布工具栏整体由 `canEdit && (...)` 控制，只读用户看不到任何画布操作 | `frontend/src/pages/grid/views/dashboard/DashboardView.tsx:406` | 只读用户无法导出整屏，也无法手动刷新画布 | 确认（C2 / C5 缺口） |
| 2 | 图表卡右上角已有单卡 PNG 导出，走 ECharts `getDataURL` | `frontend/src/pages/grid/views/dashboard/widgets/ChartWidget.tsx:79`、`chart/ChartCanvas.tsx:64` | 只能逐卡导出，无法得到整屏；KPI / 表格 / 文本不覆盖 | 确认（C1 需整屏） |
| 3 | 通用「更新 / 导出」弹窗已支持当前视图 PDF，前端视觉快照 + 自动分页 | `frontend/src/pages/import-export/ImportExportDialog/ExportPanel.tsx:65`、`exportPdf.ts:209` | 渲染、分页、清晰度、旧内核垫片已成熟，可复用 | 确认（C3 / C4 复用） |
| 4 | PDF 捕获目标是 `gridAreaRef`，对 dashboard 而言包含画布工具栏，且入口埋在数据导入 / 导出弹窗 | `frontend/src/pages/grid/GridPage.tsx:1170`、`:1355` | 导出图里出现「编辑画布 / 应用模板」等按钮；普通用户找不到面向画布的导出入口 | 确认（C4 需专用捕获区） |
| 5 | 视图读权限唯一入口为 `resolve_view_action` / `get_view_or_404`，不可见 404、可见不可写 403 | `src/cndb/plugins/tables/services/core/view_access.py:46`、`:215` | 只读分享必须沿用它，不能新增旁路 | 确认（C6 / C7） |
| 6 | 视图权限抽屉已支持 `private / shared / table` 三档与成员 viewer/editor 授权 | `frontend/src/pages/grid/gridViewBar.tsx:291`、`ViewPermissionDrawer.tsx:69` | 分享范围配置已有唯一产品入口，无需新建分享模型 | 确认（C7） |
| 7 | `GridPage` 已按 URL `?view=` 深链精确选中视图，并同步 `?mode=` | `frontend/src/pages/grid/GridPage.tsx:426-430` | 只读链接可复用现有路由与取数链路 | 确认（C8） |
| 8 | `GridPage` 的视图解析在 `?view` 未命中时会继续回落到默认视图 / `?mode` / 第一个视图 | `frontend/src/pages/grid/GridPage.tsx:431-447` | 若只读链接的目标视图被收回授权或删除，会静默展示另一张视图，语义与「链接失效」不符 | 新增（C8 必须禁止回落） |
| 9 | dashboard 行点击统一接到 `openDetailWithPrefetch`，会打开行详情抽屉 | `frontend/src/pages/grid/GridPage.tsx:1274` | 展示态若保留该入口，会暴露行级详情与后续操作面 | 新增（C9 需禁用） |
| 10 | `DashboardGrid` 画布自身 `overflow: auto`，CSS Grid 行可超出可视高度 | `frontend/src/pages/grid/views/dashboard/DashboardGrid.tsx:214-233` | 整屏导出必须展开滚动容器并按后代包围盒取尺寸，不能只截可视框 | 新增（C4 捕获边界） |
| 11 | `html2canvas-pro` / `jsPDF` 已在依赖内，导出路径动态导入并处理 Chrome 81 垫片 | `frontend/package.json:56`、`exportPdf.ts:26`、`:209-215` | 不需要新增依赖，但要沿用同一条旧内核兼容路径 | 确认（C3 / C10） |
| 12 | dashboard 体积预算单独登记，当前约 57 KiB | `frontend/scripts/bundle-budget.json` | 导出 / 分享代码若静态挂进 `DashboardView` 会顶破预算 | 确认（C10） |
| 13 | 匿名分享链接已在 ADR 0003 D5 彻底移除，表 / 视图只允许登录态深链分发 | `docs/adr/0003-view-visibility-permission-model.md:211`、`docs/adr/0017-guest-document-share.md:23` | 本设计不能为 dashboard 复活匿名读取面 | 确认（C6） |
| 14 | 大表 / 跨表画布走服务端批量取数，`loading` 独立于页面行集 | `frontend/src/pages/grid/views/dashboard/useDashboardData.ts:56-70` | 导出必须在服务端数据就绪后再捕获，否则会截到骨架屏 | 新增（C4 / C9） |
| 15 | 既有 PDF 导出把背景写死为 `#ffffff` | `frontend/src/pages/import-export/ImportExportDialog/exportPdf.ts:225` | 深色主题下图表文字为浅色，导出到白底会不可读 | 新增（C4 需按主题取背景） |
| 16 | 视图栏「更多」菜单只有视图权限 / 删除 / 导入 / 导出视图，没有复制只读链接 | `frontend/src/pages/grid/gridViewBar.tsx:290-322` | 缺少可分发的稳定只读入口 | 新增（C5 / C8） |

**核心缺陷（需求要补的）**：dashboard 目前只有「单卡 PNG」和「埋在数据更新 / 导出弹窗里的整视图 PDF」，没有面向读用户的整屏导出入口；同时也没有可转发、打开即只读的稳定链接，外部协作只能靠零散截图或整表数据文件。

设计目标（不变量）：

- **I1 所见即所得**：导出捕获的是当前已渲染的画布（同一份 `Dataset`、同一套主题与全局筛选），不做服务端第二次重算，不出现「屏幕与文件不一致」。
- **I2 权限天花板不放大**：导出只输出当前用户本来就能看到的数据；只读链接不新增匿名身份、不携带授权信息，仍走表 `READ` + 视图可见性 + 行级权限 + 字段隐藏。
- **I3 展示只读**：`present=1` 下不存在编辑、保存、拖拽、删除、新增、模板应用与行详情入口；所有写请求即便被构造也被既有后端权限拒绝。
- **I4 单一实现**：导出复用 `exportPdf.ts` 的展开 / 测量 / 渲染 / 分页能力，分享复用视图三档可见性与权限判定，不造第二套。
- **I5 失败可恢复**：导出期间临时放开的滚动容器、滚动偏移与导出态在 `finally` 中恢复；导出失败只提示，不破坏当前画布。
- **I6 入口无权限门槛**：整屏导出与复制链接对「能看到该视图」的用户开放，不因缺少 `EDIT_VIEWS` 而消失。

## Decision

### 1. 数据模型

**无新增表、无新增列、无新增迁移**：

- 画布配置继续存 `tables_dataview.view_options`（ADR 0023 D2）。
- 分享范围继续由 `tables_dataview.visibility` + `tables_dataviewpermission` 授权名单表达（ADR 0003）。
- 只读链接是**无状态深链**：`?view=<id>&mode=dashboard&present=1`，不落库、不生成 token、不存快照。链接本身不携带任何权限或数据。

### 2. 判定算法（唯一入口）

**后端权限判定不变**：分享链接打开后仍由 `GridPage` 走既有链路——`useTable` / `useTableViews` 取当前用户可见视图，`get_table_or_404(READ)` + `get_view_or_404(VIEW_READ)` 决定 404/403；`records` / `dashboard/data` 继续叠加行级权限与字段隐藏。本 ADR **不新增任何判定入口**。

前端新增两个纯函数（`dashboardShare.ts`），只负责链接与展示态解析，不做权限判定：

```ts
export interface DashboardShareInput {
  origin: string
  pathname: string      // /w/{wid}/tables/{tid}
  viewId: number | string
}
export function buildDashboardShareUrl(input: DashboardShareInput): string
// `${origin}${pathname}?view=${viewId}&mode=dashboard&present=1`

export type PresentTarget =
  | { kind: 'normal' }
  | { kind: 'present'; view: View }
  | { kind: 'invalid'; reason: 'missing_view' | 'not_visible' | 'not_dashboard' }

export function resolvePresentTarget(
  views: View[],
  requestedViewId: string | null,
  present: boolean,
): PresentTarget
```

判定顺序固定：

1. `present !== true` → `normal`（既有回落逻辑不变）。
2. `requestedViewId` 缺失 → `invalid/missing_view`。
3. `views` 中不存在该 id → `invalid/not_visible`（**禁止回落到默认视图**，I2 / C8）。
4. 目标视图 `view_type !== 'dashboard'` → `invalid/not_dashboard`。
5. 命中 → `present`。

`GridPage` 在 `present` 模式下以该结果驱动渲染：`invalid` 显示「链接无效或无权访问」空态；`present` 隐藏工具栏并渲染只读画布。

### 3. API 变更清单

| 端点 | 变更 |
|---|---|
| `GET /api/v1/workspaces/{wid}/tables/{tid}/views` | 不变：只返回当前用户可见视图，作为 `resolvePresentTarget` 的输入 |
| `GET .../views/{view_id}` / `POST .../views/{view_id}/dashboard/data` / 行记录读取 | 不变：权限、行级权限、字段隐藏与缓存口径全部沿用 |
| `PATCH .../views/{view_id}` / 可见性与授权端点 | 不变：分享设置复用「视图权限」抽屉 |
| 新增导出 / 分享端点 | **无**：整屏导出为前端视觉快照；只读分享为无状态深链 |

### 4. 边界与例外

1. **导出目标**：`DashboardView` 内新增专用捕获容器，包住 `GlobalFilterBar` + `DashboardGrid`，不含画布工具栏、应用侧栏 / 顶栏、弹窗与行详情抽屉（C4）。
2. **数据就绪**：页面行集加载中、或服务端批量取数 `loading` 时导出按钮禁用；捕获前连续等待两帧，确保 `Skeleton` 已退出、图表已 `setOption`（C4 / I1）。
3. **空 / 错状态**：单卡取数失败或空数据照实导出，不中断整屏；整张画布无 widget 时禁用导出并提示。
4. **主题与背景**：捕获背景取当前 `--cn-bg-page`（读取失败回退 `#ffffff`）；PDF 背景通过新增可选参数传入，既有 `ExportPanel` 默认仍为白色（C10 / 16）。
5. **尺寸与清晰度**：沿用 `computeRenderScale` 的画布像素预算与单边上限；超大画布宁可降低 scale 也不分配失败；PDF 继续走 `computePageSize` + `MAX_PAGE_PT` 分页。
6. **文件名**：`<视图名>-<YYYYMMDD_HHMMSS>.<png|pdf>`，视图名按 Windows 非法字符清洗，空名回退「画布」。
7. **只读链接**：链接只在 dashboard 视图生成；非 dashboard 视图不展示「复制只读链接」入口。链接不含 `q` / 其他视图参数，保证转发结果稳定。
8. **权限变化**：视图删除、转 `private`、从 `shared` 名单移除、表 / 工作区删除后，接收者打开链接得到「链接无效或无权访问」，不回落到默认视图（C8）。
9. **展示态交互**：隐藏 `GridToolbar`、`GridViewBar`、底部聚合条、行详情与导入 / 导出入口；保留刷新、导出、退出展示；表格 widget 点击行不打开详情（C9 / I3）。
10. **窄屏**：沿用 ADR 0023 D4 的单列塌陷；展示态与正常态一致，不额外存储移动端布局。
11. **自动刷新**：展示态沿用画布 `settings.refresh_interval`，后台标签页不轮询（ADR 0023 P3）；不新增推送。
12. **导出与权限**：导出结果只反映当前用户可见字段与行；不生成可被他人越权读取的服务器快照（I2）。

### 5. 迁移

无迁移。分享为无状态深链，导出为客户端行为；`tables_dataview` / 授权表 / 备份格式均不变，存量零迁移、无 downgrade。

### 6. 前端

| 层 | 文件 | 改动 |
|---|---|---|
| 导出编排 | `frontend/src/pages/grid/views/dashboard/dashboardExport.ts`（新增） | `exportDashboardToPng` / `exportDashboardToPdf`：等待就绪 → 捕获专用容器 → 下载；文件名与主题背景 |
| 捕获复用 | `frontend/src/pages/import-export/ImportExportDialog/exportPdf.ts` | 抽出 `captureElement(target, backgroundColor)`（展开滚动 / 测量 / 渲染 / 恢复）；新增可选背景参数；保持既有 `exportViewToPdf` 默认行为 |
| 图片导出 | `frontend/src/pages/import-export/ImportExportDialog/exportPng.ts`（新增或并入 `exportPdf.ts`） | 用同一 `captureElement` 产出 PNG Blob 并触发下载 |
| 链接与展示解析 | `frontend/src/pages/grid/views/dashboard/dashboardShare.ts`（新增） | `buildDashboardShareUrl`、`resolvePresentTarget` 纯函数 |
| 画布页 | `frontend/src/pages/grid/views/dashboard/DashboardView.tsx` | 工具栏对所有可见者渲染；新增导出（PNG / PDF）、复制链接、退出展示；新增捕获容器 ref；展示态隐藏编辑并禁用行点击 |
| 页面接线 | `frontend/src/pages/grid/GridPage.tsx` | 解析 `present=1`；展示态隐藏 `GridToolbar` / `GridViewBar` / 聚合条；向 `DashboardView` 传 `presenting` / `onExitPresent` / 分享回调；`invalid` 显示空态 |
| 视图栏 | `frontend/src/pages/grid/gridViewBar.tsx` | 桌面 / 移动「更多」菜单新增「复制只读链接」，仅当前视图为 dashboard 时可用 |
| 体积预算 | `frontend/scripts/bundle-budget.json` | 若新增独立导出 chunk，按实测补条目与 `reason`；`DashboardView` 基线不得因静态引入上涨 |

### 7. 测试清单

**判定层（单测）**

- `buildDashboardShareUrl`：origin / pathname 组合正确；仅保留 `view` / `mode=dashboard` / `present=1`；数字 / 字符串 id 一致；不丢路径前缀。
- `resolvePresentTarget`：非展示态返回 `normal`；缺 `view` / 视图不在可见列表 / 非 dashboard → 对应 `invalid`；命中返回 `present`；**显式断言不回落到默认视图**。
- 文件名构造：非法字符清洗、空视图名回退、时间戳格式。
- `captureElement` / `exportViewToPng`（html2canvas mock）：背景色传入、包围盒尺寸、scale 上限、滚动容器恢复（成功与抛错两条路径）。

**组件（vitest）**

- `DashboardView`：只读身份仍渲染导出 / 刷新 / 复制链接；编辑身份保留原工具栏；加载中禁用导出；展示态无编辑 / 模板 / 删除入口，且行点击不触发回调。
- `GridPage`：`present=1` 时隐藏页面工具栏与聚合条；目标视图不可见或非 dashboard 显示「链接无效或无权访问」；正常模式渲染不变。
- `GridViewBar`：dashboard 视图出现「复制只读链接」并复制正确 URL；非 dashboard 不出现 / 禁用。
- `ViewPermissionDrawer`：既有三档与名单用例回归，分享设置未引入新写口径。

**接口层**

- 无新增端点。回归：不可见视图 `GET` → 404；可见只读视图可读、写 → 403；行级权限 / 字段隐藏在 `records` 与 `dashboard/data` 两种取数路径均生效。
- 匿名访问只读链接仍被 `ProtectedRoute` 挡到登录页；不存在绕过登录的 dashboard 公开端点。

**迁移 / 备份**

- 无迁移；工作区备份 / 恢复、视图导入导出不新增字段，往返用例不改。

**e2e（前端）**

- owner 建 dashboard → 视图权限设为 `shared` 并授权 viewer → 复制只读链接 → viewer 在第二个登录态直达链接：画布可见、无编辑 / 删除 / 行详情入口。
- 只读链接触发 PNG / PDF 下载（Playwright `download` 事件，文件名与后缀正确、文件非空）。
- 收回报权 / 视图转 `private` / 删除视图后，同一链接显示「链接无效或无权访问」，不展示默认视图。
- 只读用户（无 `EDIT_VIEWS`）仍可使用整屏导出。

### 8. 分期

| 期 | 内容 | 风险 |
|---|---|---|
| **P0** | 抽取 `captureElement`；新增整屏 PNG / PDF 编排；`DashboardView` 工具栏对所有可见者开放并加导出入口；主题背景参数 | 中（捕获尺寸与旧内核兼容需实测；既有 PDF 行为须保持不变） |
| **P1** | `dashboardShare` 纯函数；`GridPage` 展示态与禁止回落；画布展示态工具栏；视图栏复制链接 | 中（展示态权限语义与既有深链回落逻辑交叉，需单测锁定） |
| **P2** | 分享设置入口联动（复用视图权限抽屉）、只读 / 失效 e2e、体积预算与文档回填 | 低 |

## 决策记录（唯一决策台账）

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | 整体方案选型 | **前端视觉快照导出 + 登录态只读深链**，零后端模型 / 端点 / 迁移 | 导出与分享都建立在「当前用户已可见的渲染结果」上；现有 `html2canvas-pro`、`jsPDF` 与视图权限链路可直接复用 | ① 服务端渲染 PDF / PNG：需新增图像渲染与中文字体链路，且要与前端图表口径保持同构；② 新建 dashboard 分享表与 token：需复制文档分享的撤销 / 计数 / 归属校验，本需求无匿名诉求 | `dashboardExport.ts`、`dashboardShare.ts`、`GridPage.tsx` |
| D2 | 是否支持匿名只读分享 | **不支持**；只读链接必须登录，匿名能力仍只属于文档分享（ADR 0017） | ADR 0003 D5 已彻底移除表 / 视图匿名分享，理由是匿名面会绕过表权限、行级权限与字段隐藏；dashboard 数据聚合面更大，不能例外 | ① 新增 dashboard 匿名 token（等于复活 D5 已删除的公开读取面）；② 导出静态快照托管为公开链接（需新增对象存储、清理与访问控制） | `view_access.py`、`GridPage.tsx` |
| D3 | 导出格式 | **PNG（默认）+ PDF（可选）** | PNG 适合聊天 / 文档直接粘贴；PDF 适合打印与归档；两者都已有成熟前端实现 | ① 仅 PDF：聊天场景不便；② 仅 PNG：长画布打印不友好；③ 后端导出新格式：重复实现 | `dashboardExport.ts`、`exportPng.ts` |
| D4 | 导出捕获范围与背景 | 捕获 **全局筛选栏 + 画布主体**；排除画布工具栏 / 应用导航；背景取当前主题色 | 筛选值决定数据口径，必须与画面一起出现；工具栏属于操作面，不属于展示内容；白底 + 深色图表不可读 | ① 只截画布主体：导出图缺少筛选口径；② 截整个 `gridAreaRef`：会把编辑按钮带进文件；③ 固定白底：深色主题不可读 | `DashboardView.tsx`、`exportPdf.ts` |
| D5 | 导出入口与权限 | `DashboardView` 工具栏对所有可见者渲染，导出 / 刷新 / 复制链接不需要 `EDIT_VIEWS` | 用户能看见数据就应能带走自己的视图；导出不放大权限；只读用户目前完全没有画布操作入口 | ① 仅编辑者导出：只读协作者只能截图；② 只放在数据导入 / 导出弹窗：入口与画布语境割裂 | `DashboardView.tsx`、`GridPage.tsx` |
| D6 | 只读链接形态 | `?view=<id>&mode=dashboard&present=1` 的现有路由深链，不新增路由 / 端点 | 复用 `GridPage` 的取数与权限链路，链接稳定、可刷新、可转发；无状态最容易撤销（权限一变即失效） | ① 新增 `/present/...` 路由：要复制 table / views / rows 取数逻辑；② 短链 / token：需落库与撤销面 | `dashboardShare.ts`、`GridPage.tsx` |
| D7 | 展示态边界 | 只读展示：隐藏页面工具栏、聚合条、行详情与导入导出；保留刷新 / 导出 / 退出；禁用行点击 | 只读分享用于「看板展示」，不应出现任何写入口；刷新与导出是只读诉求 | ① 复用普通 GridPage：写入口与行详情仍在；② 全屏浏览器 API 自动进入：非用户手势无法可靠全屏 | `DashboardView.tsx`、`GridPage.tsx` |
| D8 | 分享范围与设置 | 沿用视图三档可见性 + 既有授权名单；分享设置复用「视图权限」抽屉 | 已有唯一权限模型与产品入口；不引入第二套 grant 口径 | ① dashboard 独立分享名单：与视图权限双写，易漂移；② 链接自带角色：URL 不可信 | `ViewPermissionDrawer.tsx`、`gridViewBar.tsx` |
| D9 | 目标视图失效 | 展示态 **不回落到默认视图**，直接「链接无效或无权访问」 | 回落会把「无权看 A」静默变成「看到了 B」，与 ADR 0003 I6 的不泄露存在性口径冲突 | ① 继续回落默认视图：语义错误且可能展示未分享内容；② 单独返回 403 文案：泄露视图曾存在 | `resolvePresentTarget`、`GridPage.tsx` |
| D10 | 复用与体积 | 抽出 `captureElement` 供 PDF / PNG 共用；导出与分享辅助模块按需导入，`DashboardView` 不静态膨胀 | 避免两套捕获逻辑漂移；现有体积预算对 dashboard 有独立基线 | ① 复制 PDF 捕获实现到 dashboard：两处维护；② 导出库静态挂主入口：首屏与主 chunk 膨胀 | `exportPdf.ts`、`dashboardExport.ts`、`bundle-budget.json` |

门禁：`Proposed` → `Accepted` 前本表不得有「待定」；结论只在本书出现，别处只引用编号。

## Consequences

- **正向**：读用户也能一键带走整屏画布；对外分发有 PNG / PDF 两种稳定产物；内部协作有可转发的只读深链，且权限完全沿用现有视图模型；零迁移、零新端点，落地面集中在前端。
- **负向**：只读链接仅登录用户可用，不能像文档分享那样发给外部访客；整屏导出的保真度依赖浏览器渲染（字体、图表、旧内核），需要实测与体积预算；展示态与普通深链多了一个参数分支，测试面扩大。
- **风险与缓解**：① 捕获尺寸 / 旧内核失败 → 复用既有 `expandScrollContainers`、像素预算与 Chrome 81 垫片；② 深色主题不可读 → 按主题取背景并保留 `#ffffff` 兼容默认；③ 链接失效语义被回落逻辑破坏 → `resolvePresentTarget` 单测锁定「不回落」；④ 体积超限 → 动态导入 + `bundle-budget` 实测基线。

## 行业对照

| 维度 | Power BI | Tableau | 本设计 |
|---|---|---|---|
| 分享身份 | 工作区内分享需账号；另有「发布到 Web」公开链接 | 分享链接需 Server / Cloud 账号 | **仅登录态**，不提供匿名链接（D2） |
| 导出 | PDF / PNG / 幻灯片 | PDF / 图片 | PNG / PDF，前端所见即所得（D3 / D4） |
| 权限依据 | 工作区角色 + 行级安全 | 项目 / 工作簿权限 | 沿用表 `READ` + 视图三档 + 行级权限（D8） |

来源：Power BI 分享与导出文档、Tableau Server 分享与导出文档；内部权限取舍另见 ADR 0003 的飞书 / Airtable 对照。

## 与既有 ADR 的关系

| 轴 | 载体 | 决定 | 由谁 |
|---|---|---|---|
| dashboard 配置与取数 | `view_options`、`dashboard/data` | 整屏导出消费现有 `Dataset`，分享沿用视图配置 | ADR 0023 |
| 视图可见性与匿名分享 | `visibility` + 授权名单 | 分享只读沿用三档可见性；**不恢复匿名分享** | ADR 0003 D5 |
| 匿名分享能力范围 | `/public/share/:token` | 匿名能力仍只覆盖文档，不扩展到表 / 视图 / dashboard | ADR 0017 C10 |
| 旧内核导出兼容 | `exportPdf.ts` 垫片与动态导入 | 整屏导出沿用同一路径 | ADR 0026 |

## 落地状态（随实现更新）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 | 已落地 | `frontend/src/pages/grid/views/dashboard/dashboardExport.ts`、`frontend/src/pages/import-export/ImportExportDialog/exportPdf.ts`、`frontend/src/pages/import-export/ImportExportDialog/exportPng.ts`、`frontend/src/pages/grid/views/dashboard/DashboardView.tsx` | `frontend/src/pages/grid/views/dashboard/dashboardExport.test.ts`、`frontend/src/pages/import-export/ImportExportDialog/exportPdf.test.ts`、`frontend/src/pages/import-export/ImportExportDialog/exportPng.test.ts`、`frontend/src/pages/grid/views/dashboard/DashboardView.test.tsx` | 待回填 |
| P1 | 已落地 | `frontend/src/pages/grid/views/dashboard/dashboardShare.ts`、`frontend/src/pages/grid/GridPage.tsx`、`frontend/src/pages/grid/gridViewBar.tsx` | `frontend/src/pages/grid/views/dashboard/dashboardShare.test.ts`、`frontend/src/pages/grid/GridPage.present.test.tsx`、`frontend/src/pages/grid/gridViewBar.test.tsx`、`frontend/tests/e2e/critical/dashboard-readonly-share.spec.ts` | 待回填 |
| P2 | 已落地 | `frontend/src/pages/grid/ViewPermissionDrawer.tsx`、`frontend/src/pages/grid/gridViewBar.tsx`、`frontend/src/pages/grid/views/dashboard/DashboardView.tsx` | `frontend/src/pages/grid/ViewPermissionDrawer.test.tsx`、`frontend/tests/e2e/critical/dashboard-export.spec.ts`、`frontend/tests/e2e/critical/dashboard-readonly-share.spec.ts` | 待回填 |

> 状态只取「未开始 / 进行中 / 已落地」。标「已落地」的期必须有代码落点与测试文件；全期落地后由人确认 `Status` 是否改 `Accepted` / `Implemented`。`make adr-check` 会校验本表与代码、测试、CHANGELOG 的对应关系。

## 交接（会话结束更新）

- 当前阶段：P0-P2 已全部落地，`Status` 保持 `Accepted`（待上线后按仓库口径确认是否改 `Implemented`）
- 已完成：整屏导出（PNG / PDF 共用 `captureElement`、专用捕获容器、主题背景、数据就绪门控）、登录态只读深链（禁止回落、展示态隐藏页面 chrome 与行详情、退出展示）、视图栏复制链接、分享设置复用视图权限抽屉并补画布提示、e2e 两条（导出格式校验 / 只读分享与失效）
- 下一步：上线后观察大画布导出在低配设备的表现；如需扩展（例如整屏导出加图片格式选项）另开需求卡片，不改本 ADR 已收口的口径
- 已知坑：① 既有 PDF 捕获目标是 `gridAreaRef`，dashboard 的导出必须换专用容器，否则工具栏会被截进文件；② `html2canvas-pro` 在 Chrome 81 需先加载 `Intl.Segmenter` 垫片（沿用 `exportPdf.ensureIntlSegmenter`）；③ `DashboardGrid` 自身滚动，捕获前必须展开滚动容器并按后代包围盒取尺寸；④ 深色主题导出需传主题背景，不能沿用写死的白色；⑤ 展示态 `?view` 未命中时**绝不能**走 `GridPage` 的默认视图回落；⑥ 大表 / 跨表走服务端取数，导出前要等 `useDashboardData.loading` 结束；⑦ 导出编排与分享辅助全部按需导入（`DashboardView` 内动态 `import('./dashboardExport')`），`DashboardView` 静态依赖只保留类型；⑧ 视图权限抽屉已改为 `lazy` 且仅在打开时挂载，避免回涨 `GridPage` chunk；⑨ Chromium 对含中文的 anchor download 文件名会回落为 `download`，e2e 用文件魔数而非文件名断言；⑩ `present=1` 时先等 `useTableViews` 结束再判失效，避免把「加载中」误判成「链接无效」
- 最近一次全绿：`make check-fast`、`pnpm build` + `pnpm bundle:budget`、新增 e2e 4 例（2026-11-01）
