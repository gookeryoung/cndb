# 视图内容导出 PDF

## 需求来源

用户需求：在「更新 / 导出」中增加导出 PDF 功能，将看板、列表等视图的实际内容区域导出为 PDF，忽略顶部栏等无关区域。技术方案经用户确认：html2canvas-pro + jsPDF（前端视觉快照导出，非数据导出），覆盖全部视图类型。

## 与数据导出的关系

- 数据导出（json/csv/xlsx）走后端 `GET /export` 接口，见 `.trae/designs/export-view-scope.md`，本设计不改变其行为。
- PDF 导出为纯前端视觉快照：将当前视图内容区 DOM 渲染为图片并写入 PDF，不经后端、不受「按视图筛选 / 全表」范围开关影响（该开关仅针对数据导出）。

## 行为定义

- [x] 导出 Tab 格式选项新增 `PDF（当前视图画面）`。
- [x] 选择 PDF 时：隐藏「按视图筛选 / 全表」范围开关，展示提示「导出当前视图可见内容画面（不含顶部栏），PDF 为视觉快照，不受视图筛选影响」；后端导出接口不被调用。
- [x] 捕获目标为 GridPage 主内容容器（`gridAreaRef`，`GridPage.tsx` 主内容 div）：包含 grid / kanban / gantt / wbs / matrix / chart / calendar 全部视图的实际渲染内容，天然排除页头与视图栏（GridViewBar）。
- [x] PDF 页面为 A4 纵向（595.28×841.89pt，页边距 28.35pt ≈ 10mm）：内容按宽度等比缩放后垂直切片分页；内容高度不足一页时单页输出。
- [x] 生成期间下载按钮 loading；成功提示「导出完成」；失败 message.error 原始错误信息。
- [x] 文件名：`table-{tid}-view.pdf`；若激活视图存在则为 `view-{视图名}-{YYYYMMDD_HHMMSS}.pdf`。

## 依赖与加载策略

- 新增前端依赖（用户已授权）：`jspdf@^4.2.1`、`html2canvas-pro@^2.5.2`（html2canvas 的 fork，支持 AntD 5 的 oklch / color-mix 色彩）。
- 两个库均在导出点击时通过动态 `import()` 懒加载，生成独立 chunk，不进入 GridPage 主包（已核对 bundle budget：GridPage chunk 增量约 0.02KiB，远低于容差）。

## 组件职责与数据流

- `GridPage.tsx`：向 `ImportExportDialog` 传入 `getPdfTarget: () => HTMLElement | null`（返回 `gridAreaRef.current`）。
- `ImportExportDialog/index.tsx`：透传 `getPdfTarget` 给 `ExportPanel`。
- `ExportPanel.tsx`：格式为 `pdf` 时调用 `exportViewToPdf(target, filename)`；不调用 `exportApi.download`。
- `frontend/src/pages/import-export/ImportExportDialog/exportPdf.ts`（新模块，与 ExportPanel 同目录内聚）：
  - `computePageSlices(contentHeight, pageContentHeight): Array<{ y, height }>` — 纯函数，计算垂直切片区间（缩放后坐标），供单测；非法输入返回空数组。
  - `exportViewToPdf(target, filename)` — 动态导入库 → `html2canvas(target, { scale: 2, backgroundColor: '#ffffff', useCORS: true })` → 按 A4 内容区高度切片（`computePageSlices`）→ 逐页以 `drawImage` 切出页画布 → `addImage`（JPEG 0.92）→ `save(filename)`。
  - canvas 输出尺寸 = 元素 scrollWidth × scrollHeight × scale，横向滚动内容（如宽看板）整体纳入。
  - 常量：`A4_PAGE_PT`、`PAGE_MARGIN_PT`。

## 异常处理

- `getPdfTarget()` 返回 null（容器未挂载）：message.error「未找到可导出的视图内容」，不调用生成。
- html2canvas / jsPDF 动态导入失败或渲染抛错：捕获并 message.error 原始错误信息，不产生半截文件（save 前抛错即无文件）。

## 边界与风险

| 类别 | 说明 |
|---|---|
| 超宽内容 | 宽看板等比缩放到 A4 宽度后文字可能偏小，v1 接受；不做横向 PDF |
| 长内容 | 切片分页，页间不做内容裁剪补偿（卡片可能被切分），v1 接受 |
| 滚动位置 | html2canvas 克隆 DOM 渲染完整元素，不受当前视口滚动影响 |
| 暗色主题 | 背景色取内容区自身渲染，统一垫白底避免透明黑字 |

## 测试覆盖

- `exportPdf.test.ts`：`computePageSlices` 纯函数（不足一页 / 整除 / 有余数 / 非法输入）；`exportViewToPdf` 编排（库 mock）：多页 addPage / addImage 次数、页宽一致性、save 文件名、渲染失败抛错。
- `ImportExportDialog.test.tsx`：选择 PDF 后点击下载 → 调用 `exportViewToPdf`（模块 mock）且后端导出接口未被调用；范围开关在 PDF 格式下隐藏、csv 格式下保留；目标为 null 时报错提示。
- `GridPage.importExportView.test.tsx`：回归 `getPdfTarget` 接线（返回主内容区元素）。

## 验收标准

- [x] AC-1 导出 Tab 选 PDF 并下载 → 浏览器收到 .pdf 文件，内容仅含视图内容区，不含页头与视图栏（单测验证调用链；实际画面建议人工抽查一次）。
- [x] AC-2 grid / kanban / gantt / wbs / matrix / chart / calendar 七类视图共用同一捕获目标（gridAreaRef 容器），均可成功导出。
- [x] AC-3 内容超过一页高度时 PDF 正确分为多页，页宽等比一致（exportPdf.test.ts 覆盖 3 页切片）。
- [x] AC-4 选择 PDF 时范围开关隐藏，`exportApi.download` 不被调用（ImportExportDialog.test.tsx 覆盖）。
- [x] AC-5 `make check` 全绿（lint / typecheck / cov 全部通过）。
