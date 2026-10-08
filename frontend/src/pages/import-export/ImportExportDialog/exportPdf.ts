/** 视图内容导出 PDF —— 前端视觉快照（html2canvas-pro + jsPDF）.
 *
 * 与数据导出（exportApi.download → 后端 /export）不同：本模块将视图内容区 DOM
 * 渲染为 canvas，按 A4 纵向宽度等比缩放后垂直切片分页写入 PDF。
 * jspdf / html2canvas-pro 均在导出点击时动态导入，生成独立 chunk，不进入主包。
 */
/** A4 纵向页面尺寸（pt） */
export const A4_PAGE_PT = { width: 595.28, height: 841.89 } as const
/** 页边距（pt），约 10mm */
export const PAGE_MARGIN_PT = 28.35

/** 一页切片：源内容（按宽度缩放后）上的垂直区间 */
export interface PageSlice {
  /** 区间起点（缩放后坐标） */
  y: number
  /** 区间高度（缩放后坐标） */
  height: number
}

/** 计算垂直切片区间：把总高 contentHeight 均分为若干个不超过 pageContentHeight 的连续区间.
 *
 * 返回空数组表示无可导出内容（非法输入或高度 <= 0）。
 */
export function computePageSlices(contentHeight: number, pageContentHeight: number): PageSlice[] {
  if (!Number.isFinite(contentHeight) || !Number.isFinite(pageContentHeight)) return []
  if (contentHeight <= 0 || pageContentHeight <= 0) return []
  const slices: PageSlice[] = []
  let y = 0
  while (y < contentHeight) {
    const height = Math.min(pageContentHeight, contentHeight - y)
    slices.push({ y, height })
    y += height
  }
  return slices
}

/** 将目标元素渲染为 PDF 并触发下载.
 *
 * @param target 视图内容区根元素（GridPage 的 gridAreaRef 容器，含全部视图渲染内容）
 * @param filename 下载文件名（需以 .pdf 结尾）
 * @throws 渲染或 PDF 生成失败时向上抛出原始错误，由调用方提示
 */
export async function exportViewToPdf(target: HTMLElement, filename: string): Promise<void> {
  const [{ default: html2canvas }, { jsPDF }] = await Promise.all([
    import('html2canvas-pro'),
    import('jspdf'),
  ])
  const canvas = await html2canvas(target, { scale: 2, backgroundColor: '#ffffff', useCORS: true })
  const pdf = new jsPDF({ unit: 'pt', format: 'a4', orientation: 'portrait' })

  const pageWidthPt = pdf.internal.pageSize.getWidth()
  const pageHeightPt = pdf.internal.pageSize.getHeight()
  const margin = PAGE_MARGIN_PT
  const contentWidthPt = pageWidthPt - margin * 2
  const contentHeightPt = pageHeightPt - margin * 2
  // 内容按宽度等比缩放：pxPerPt 为源 canvas 像素 / pt 比例
  const pxPerPt = canvas.width / contentWidthPt
  const scaledContentHeight = canvas.height / pxPerPt
  const slices = computePageSlices(scaledContentHeight, contentHeightPt)

  slices.forEach((slice, index) => {
    if (index > 0) pdf.addPage()
    const sy = slice.y * pxPerPt
    const sh = slice.height * pxPerPt
    // 源 canvas 按页切片，避免整图重复嵌入每页
    const pageCanvas = document.createElement('canvas')
    pageCanvas.width = canvas.width
    pageCanvas.height = Math.max(1, Math.ceil(sh))
    const ctx = pageCanvas.getContext('2d')
    if (!ctx) throw new Error('PDF 导出失败：无法创建画布上下文')
    ctx.fillStyle = '#ffffff'
    ctx.fillRect(0, 0, pageCanvas.width, pageCanvas.height)
    ctx.drawImage(canvas, 0, sy, canvas.width, sh, 0, 0, canvas.width, pageCanvas.height)
    pdf.addImage(pageCanvas.toDataURL('image/jpeg', 0.92), 'JPEG', margin, margin, contentWidthPt, slice.height)
  })

  pdf.save(filename)
}
