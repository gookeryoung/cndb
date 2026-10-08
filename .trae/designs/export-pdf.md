# 视图内容导出 PDF

## 需求来源

用户需求：在「更新 / 导出」中增加导出 PDF 功能，将看板、列表等视图的实际内容区域导出为 PDF，忽略顶部栏等无关区域。技术方案经用户确认：html2canvas-pro + jsPDF（前端视觉快照导出，非数据导出），覆盖全部视图类型。

第二轮需求：导出时自动识别横版/竖版；把超出屏幕范围需要 scroll 的内容（横向滚动区外的列、纵向滚动区外的行）完整囊括进 PDF。

## 与数据导出的关系

- 数据导出（json/csv/xlsx）走后端 `GET /export` 接口，见 `.trae/designs/export-view-scope.md`，本设计不改变其行为。
- PDF 导出为纯前端视觉快照：将当前视图内容区 DOM 渲染为图片并写入 PDF，不经后端、不受「按视图筛选 / 全表」范围开关影响（该开关仅针对数据导出）。快照范围 = 当前视图在内存中的全部数据（grid 为当前分页的行），不含未拉取的分页数据。

## 行为定义

- [x] 导出 Tab 格式选项新增 `PDF（当前视图画面）`。
- [x] 选择 PDF 时：隐藏「按视图筛选 / 全表」范围开关，展示提示「导出当前视图可见内容画面（不含顶部栏），PDF 为视觉快照，不受视图筛选影响」；后端导出接口不被调用。
- [x] 捕获目标为 GridPage 主内容容器（`gridAreaRef`，`GridPage.tsx` 主内容 div）：包含 grid / kanban / gantt / wbs / matrix / chart / calendar 全部视图的实际渲染内容，天然排除页头与视图栏（GridViewBar）。
- [x] PDF 页面为 A4（页边距 28.35pt ≈ 10mm）：纸张方向按内容宽高比自适应（`pickOrientation`：内容宽 > 高用 landscape，否则 portrait），内容按宽度等比缩放后垂直切片分页；内容高度不足一页时单页输出。
- [x] 生成期间下载按钮 loading；成功提示「导出完成」；失败 message.error 原始错误信息。
- [x] 文件名：`table-{tid}-view.pdf`；若激活视图存在则为 `view-{视图名}-{YYYYMMDD_HHMMSS}.pdf`。

## 滚动内容完整捕获（导出模式）

html2canvas 按目标元素可视框渲染，且虚拟滚动视图的 DOM 只有可视窗口内的行，直接捕获会丢失滚动区外内容。解法为两层配合：

- **导出模式（`pdfExporting`，GridPage 状态）**——关闭虚拟化、放开结构性裁剪，使全部行进入 DOM：
  - `getPdfTarget` 改为 async：置位 `pdfExporting` → 双 rAF 等待 React 提交与布局 → 返回 `gridAreaRef.current`；`releasePdfTarget` 在导出 finally 中复位（恢复虚拟滚动）。
  - grid 视图（`gridTableSection`）：`virtual={!pdfExporting}` 且导出模式去掉 `scroll.y`（表体不分离、当前页全量渲染，横向 scroll.x 保留以维持列宽）。
  - kanban（`KanbanView`）：`useVirtual = rows >= 30 && !pdfExporting`，走既有非虚拟平铺分支（注意：`@tanstack/react-virtual` 的 `enabled: false` 会使 `getVirtualItems()` 返回空数组而非全量，不可用）。
  - gantt（`GanttView`）：行高全部为定高常量，导出模式手动累计偏移合成全量 `VirtualItem` 序列替代虚拟切片（左右两栏共用保证对齐）；表头裁剪容器与左侧固定列容器 `overflow: hidden → visible`。
  - wbs / matrix / chart / calendar 无虚拟化，仅靠下方 CSS 展开即可。
- **CSS 展开（`expandScrollContainers`，exportPdf.ts）**——捕获前临时放开真实滚动容器：
  - 遍历目标及全部后代，computed `overflow-x/y ∈ {auto, scroll}` 的容器内联两轴均置 `visible`（CSS 规定 visible 与非 visible 组合时被强制按 auto 计算，只放开单轴无效）；`overflow: hidden` 的文本 ellipsis 容器不动。
  - 全部后代非零 `scrollLeft/scrollTop` 清零并记录（overflow:hidden 的同步裁剪容器如甘特表头仍可能带偏移，归零后同步双栏从原点天然对齐）。
  - 返回恢复函数：html2canvas resolve（或抛错）后立即还原内联 overflow 与滚动偏移。
  - 画布尺寸由 `measureContentBounds` 提供：目标及全部后代 `getBoundingClientRect` 的包围盒并集（相对目标左上），作为 html2canvas 显式 `width/height`，使溢出目标可视框的展开内容整体入画。

## 依赖与加载策略

- 前端依赖：`jspdf@^4.2.1`、`html2canvas-pro@^2.5.2`（html2canvas 的 fork，支持 AntD 5 的 oklch / color-mix 色彩）。
- 两个库均在导出点击时通过动态 `import()` 懒加载，生成独立 chunk，不进入 GridPage 主包。

## 组件职责与数据流

- `GridPage.tsx`：持有 `pdfExporting` 状态，向 `ImportExportDialog` 传 `getPdfTarget: () => Promise<HTMLElement | null>`（进入导出模式并等待重渲染）与 `releasePdfTarget: () => void`；`pdfExporting` 下传 gridTableSection / KanbanView / GanttView。
- `ImportExportDialog/index.tsx`：透传两个 prop 给 `ExportPanel`。
- `ExportPanel.tsx`：`handleExportPdf` 中 `await getPdfTarget()` 取目标（null 时 message.error「未找到可导出的视图内容」），finally 中调 `releasePdfTarget`；格式为 `pdf` 时不调用 `exportApi.download`。
- `frontend/src/pages/import-export/ImportExportDialog/exportPdf.ts`（与 ExportPanel 同目录内聚）：
  - `computePageSlices(contentHeight, pageContentHeight)` — 纯函数，垂直切片区间（非法输入返回空数组）。
  - `pickOrientation(contentWidth, contentHeight)` — 纯函数，纸张方向自适应。
  - `expandScrollContainers(target)` — 纯 DOM 操作，展开滚动容器 + 清零滚动偏移，返回恢复函数。
  - `measureContentBounds(target)` — 纯 DOM 测量，包围盒并集。
  - `exportViewToPdf(target, filename)` — 动态导入库 → expand → `html2canvas(target, { scale: 2, backgroundColor: '#ffffff', useCORS: true, width, height })` → restore → `pickOrientation` → 切片（`computePageSlices`）→ 逐页 `drawImage` + `addImage`（JPEG 0.92）→ `save(filename)`。
  - 常量：`A4_PAGE_PT`、`PAGE_MARGIN_PT`。

## 异常处理

- `getPdfTarget()` 返回 null（容器未挂载）：message.error「未找到可导出的视图内容」，不调用生成。
- html2canvas / jsPDF 动态导入失败或渲染抛错：expand 的恢复函数在 finally 中执行（DOM 无残留），捕获后 message.error 原始错误信息，不产生半截文件。

## 边界与风险

| 类别 | 说明 |
|---|---|
| 超宽/超高内容 | 画布按展开后包围盒全量渲染，scale=2 下超大看板/甘特内存占用高（实测 8848×12900 与 13876×20230 成功），极大数据可能慢，v1 接受 |
| 导出期间页面 | 导出模式重渲染（几百行全量挂载）期间页面短暂卡顿 + 滚动容器临时展开，导出完成即恢复 |
| 长内容分页 | 切片分页，页间不做内容裁剪补偿（卡片可能被切分），v1 接受 |
| 滚动位置 | 展开后滚动偏移清零，快照始终从内容原点开始渲染，与用户当前滚动位置无关 |
| 暗色主题 | 背景色取内容区自身渲染，统一垫白底避免透明黑字 |
| React 覆盖内联样式 | 展开期间若有无关 React 重渲染覆盖被展开元素的内联样式，恢复函数按快照还原，v1 接受该竞态 |

## 测试覆盖

- `exportPdf.test.ts`：`computePageSlices` 纯函数（不足一页 / 整除 / 有余数 / 非法输入）；`pickOrientation`（宽>高横版、高≥宽竖版）；`expandScrollContainers`（auto/scroll 两轴展开与恢复、hidden ellipsis 不动、滚动偏移清零与还原）；`measureContentBounds`（包围盒并集）；`exportViewToPdf` 编排（库 mock）：竖版多页 / 横版单页与内容区宽度、渲染期展开态生效且渲染后还原、失败抛错且还原。
- `ImportExportDialog.test.tsx`：选择 PDF 后点击下载 → 调用 `exportViewToPdf`（模块 mock）且后端导出接口未被调用；范围开关在 PDF 格式下隐藏、csv 格式下保留；目标为 null 时报错提示；导出结束后 `releasePdfTarget` 被调用。
- `GridPage.importExportView.test.tsx`：回归 `getPdfTarget`（async，resolve 后返回主内容区元素）与 `releasePdfTarget` 接线。

## 验收标准

- [x] AC-1 导出 Tab 选 PDF 并下载 → 浏览器收到 .pdf 文件，内容仅含视图内容区，不含页头与视图栏。
- [x] AC-2 grid / kanban / gantt / wbs / matrix / chart / calendar 七类视图共用同一捕获目标（gridAreaRef 容器），均可成功导出。
- [x] AC-3 内容超过一页高度时 PDF 正确分为多页，页宽等比一致。
- [x] AC-4 选择 PDF 时范围开关隐藏，`exportApi.download` 不被调用。
- [x] AC-5 方向自适应：宽>高内容（宽看板/宽表）导出横版 A4，高≥宽内容导出竖版 A4（浏览器实测：grid 画布 4836×3318 → 横版 MediaBox 841.89×595.28；kanban 8848×12900 → 竖版；gantt 13876×20230 → 竖版）。
- [x] AC-6 滚动区外内容纳入：导出画布尺寸显著大于视口（grid 4836px 宽 vs 视口约 1280；kanban/gantt 高宽均远超视口），虚拟滚动行全部进入快照。
- [x] AC-7 `make check` 全绿（lint / typecheck / cov 全部通过）。
