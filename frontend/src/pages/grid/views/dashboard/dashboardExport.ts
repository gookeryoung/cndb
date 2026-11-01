/** dashboard 整屏导出编排（ADR 0077 P0）.
 *
 * 与「更新 / 导出」弹窗里的通用 PDF 不同，这里面向画布语境：
 * - 捕获目标由 `DashboardView` 提供的专用容器（全局筛选栏 + 画布主体），不含工具栏；
 * - 背景取当前主题页面色，避免深色主题的浅色文字落到白底上不可读；
 * - PNG / PDF 共用 `captureElement`，导出库继续动态导入。
 */

export type DashboardExportFormat = 'png' | 'pdf'

/** 本地时间戳 YYYYMMDD_HHMMSS（与通用 PDF 导出口径一致） */
export function formatExportTimestamp(date: Date): string {
  const p = (n: number) => String(n).padStart(2, '0')
  return `${date.getFullYear()}${p(date.getMonth() + 1)}${p(date.getDate())}_${p(date.getHours())}${p(date.getMinutes())}${p(date.getSeconds())}`
}

/** 生成导出文件名：`<视图名>-<YYYYMMDD_HHMMSS>.<png|pdf>`.
 *
 * 视图名按 Windows 非法字符清洗；空名 / 全非法字符回退「画布」。
 */
export function dashboardExportFilename(
  viewName: string | null | undefined,
  format: DashboardExportFormat,
  date: Date = new Date(),
): string {
  const cleaned = (viewName ?? '').replace(/[\\/:*?"<>|]/g, '_').trim()
  return `${cleaned || '画布'}-${formatExportTimestamp(date)}.${format}`
}

/** 读取当前主题页面背景色；CSS 变量缺失或为空时回退白色. */
export function resolveExportBackground(root: HTMLElement | null): string {
  if (!root || typeof getComputedStyle !== 'function') return '#ffffff'
  const value = getComputedStyle(root).getPropertyValue('--cn-bg-page').trim()
  return value || '#ffffff'
}

/** 导出当前画布（PNG / PDF），失败时向上抛出由调用方提示.
 *
 * 导出实现按格式动态导入：既有 PDF 模块顶部含兼容垫片与导出库引用，
 * 静态引入会把它们拉进 `DashboardView` chunk（ADR 0077 D10）。
 */
export async function exportDashboard(
  target: HTMLElement,
  viewName: string | null | undefined,
  format: DashboardExportFormat,
  date: Date = new Date(),
  backgroundRoot: HTMLElement | null = typeof document !== 'undefined' ? document.documentElement : null,
): Promise<void> {
  const filename = dashboardExportFilename(viewName, format, date)
  const background = resolveExportBackground(backgroundRoot)
  if (format === 'png') {
    const { exportElementToPng } = await import('../../../import-export/ImportExportDialog/exportPng')
    await exportElementToPng(target, filename, background)
    return
  }
  const { exportViewToPdf } = await import('../../../import-export/ImportExportDialog/exportPdf')
  await exportViewToPdf(target, filename, background)
}
