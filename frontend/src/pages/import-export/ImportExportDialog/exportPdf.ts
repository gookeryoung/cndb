/** 视图内容导出 PDF —— 前端视觉快照（html2canvas-pro + jsPDF）.
 *
 * 与数据导出（exportApi.download → 后端 /export）不同：本模块将视图内容区 DOM
 * 渲染为 canvas，按 A4 宽度等比缩放后垂直切片分页写入 PDF。
 * jspdf / html2canvas-pro 均在导出点击时动态导入，生成独立 chunk，不进入主包。
 *
 * 滚动内容与纸张方向：
 * - 捕获前对目标内所有 overflow:auto/scroll 容器临时放开为 visible 并清零滚动偏移，
 *   配合调用方在导出模式下关闭虚拟滚动（DOM 已含全部行），超出屏幕的滚动内容整体纳入；
 * - 画布尺寸取目标及全部后代的包围盒（展开后的溢出内容也在内），不再受目标可视框限制；
 * - 纸张方向按内容宽高比自适应：宽 > 高用横版（landscape），否则竖版（portrait）。
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

/** 依据内容宽高比选择纸张方向：内容宽 > 高为横向内容，用横版；否则竖版. */
export function pickOrientation(contentWidth: number, contentHeight: number): 'portrait' | 'landscape' {
  return contentWidth > contentHeight ? 'landscape' : 'portrait'
}

/** 展开前的样式/滚动偏移快照（恢复用） */
interface ExpansionRecord {
  el: HTMLElement
  inlineOverflowX: string
  inlineOverflowY: string
  scrollLeft: number
  scrollTop: number
  touchedOverflow: boolean
  touchedScroll: boolean
}

/** 临时放开目标内全部滚动容器并清零滚动偏移，返回恢复函数.
 *
 * 仅处理 computed overflow 为 auto/scroll 的容器（真实滚动容器）；overflow:hidden 的
 * 文本 ellipsis 容器不动，避免破坏列宽布局（结构性 hidden 裁剪由视图在导出模式下自行放开）。
 * 两轴必须同时置 visible：CSS 规定 visible 与非 visible 组合时 visible 被强制按 auto
 * 计算，只放开单轴会保留滚动容器语义、内容仍被裁剪。
 * 随后将全部后代的非零 scrollLeft/scrollTop 清零并记录 —— overflow:hidden 的同步裁剪
 * 容器（如甘特表头）仍可能带偏移，归零后全部内容从原点渲染、同步双栏天然对齐。
 * 恢复函数按快照还原内联 overflow 与滚动偏移。
 */
export function expandScrollContainers(target: HTMLElement): () => void {
  const elements: HTMLElement[] = [target, ...target.querySelectorAll<HTMLElement>('*')]
  const records = new Map<HTMLElement, ExpansionRecord>()

  const ensureRecord = (el: HTMLElement): ExpansionRecord => {
    let rec = records.get(el)
    if (!rec) {
      rec = {
        el,
        inlineOverflowX: el.style.overflowX,
        inlineOverflowY: el.style.overflowY,
        scrollLeft: el.scrollLeft,
        scrollTop: el.scrollTop,
        touchedOverflow: false,
        touchedScroll: false,
      }
      records.set(el, rec)
    }
    return rec
  }

  for (const el of elements) {
    const cs = getComputedStyle(el)
    const { overflowX: ox, overflowY: oy } = cs
    if (ox !== 'auto' && ox !== 'scroll' && oy !== 'auto' && oy !== 'scroll') continue
    const rec = ensureRecord(el)
    rec.touchedOverflow = true
    el.style.overflowX = 'visible'
    el.style.overflowY = 'visible'
  }

  for (const el of elements) {
    if (el.scrollLeft === 0 && el.scrollTop === 0) continue
    const rec = ensureRecord(el)
    rec.touchedScroll = true
    el.scrollLeft = 0
    el.scrollTop = 0
  }

  return () => {
    for (const rec of records.values()) {
      if (rec.touchedOverflow) {
        rec.el.style.overflowX = rec.inlineOverflowX
        rec.el.style.overflowY = rec.inlineOverflowY
      }
      if (rec.touchedScroll) {
        rec.el.scrollLeft = rec.scrollLeft
        rec.el.scrollTop = rec.scrollTop
      }
    }
  }
}

/** 测量目标及全部后代的包围盒尺寸（相对目标左上角）.
 *
 * 展开滚动容器后溢出内容渲染在目标可视框之外，html2canvas 需显式传入画布尺寸
 * 才能把溢出部分画进画布；仅统计有实际面积的元素（跳过 display:none 等）。
 */
export function measureContentBounds(target: HTMLElement): { width: number; height: number } {
  const base = target.getBoundingClientRect()
  let maxRight = base.right
  let maxBottom = base.bottom
  for (const el of target.querySelectorAll<HTMLElement>('*')) {
    const r = el.getBoundingClientRect()
    if (r.width === 0 && r.height === 0) continue
    if (r.right > maxRight) maxRight = r.right
    if (r.bottom > maxBottom) maxBottom = r.bottom
  }
  return {
    width: Math.max(base.width, maxRight - base.left),
    height: Math.max(base.height, maxBottom - base.top),
  }
}

/** 将目标元素渲染为 PDF 并触发下载.
 *
 * @param target 视图内容区根元素（GridPage 的 gridAreaRef 容器；调用方须已在导出模式下
 *   关闭虚拟滚动，使全部行进入 DOM）
 * @param filename 下载文件名（需以 .pdf 结尾）
 * @throws 渲染或 PDF 生成失败时向上抛出原始错误，由调用方提示
 */
export async function exportViewToPdf(target: HTMLElement, filename: string): Promise<void> {
  const [{ default: html2canvas }, { jsPDF }] = await Promise.all([
    import('html2canvas-pro'),
    import('jspdf'),
  ])

  // 放开滚动容器 → 按展开后的包围盒定画布尺寸 → 渲染完成后立即还原 DOM
  const restore = expandScrollContainers(target)
  let canvas: HTMLCanvasElement
  try {
    const bounds = measureContentBounds(target)
    canvas = await html2canvas(target, {
      scale: 2,
      backgroundColor: '#ffffff',
      useCORS: true,
      width: Math.ceil(bounds.width),
      height: Math.ceil(bounds.height),
    })
  } finally {
    restore()
  }

  const orientation = pickOrientation(canvas.width, canvas.height)
  const pdf = new jsPDF({ unit: 'pt', format: 'a4', orientation })

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
