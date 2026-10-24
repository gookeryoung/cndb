/** 视图内容导出 PDF —— 前端视觉快照（html2canvas-pro + jsPDF）.
 *
 * 与数据导出（exportApi.download → 后端 /export）不同：本模块将视图内容区 DOM
 * 渲染为 canvas，再按「屏幕实际大小」1:1 写入 PDF。
 * jspdf / html2canvas-pro 均在导出点击时动态导入，生成独立 chunk，不进入主包。
 *
 * 滚动内容与纸张方向：
 * - 捕获前对目标内所有 overflow:auto/scroll 容器临时放开为 visible 并清零滚动偏移，
 *   配合调用方在导出模式下关闭虚拟滚动（DOM 已含全部行），超出屏幕的滚动内容整体纳入；
 * - 画布尺寸取目标及全部后代的包围盒（展开后的溢出内容也在内），不再受目标可视框限制。
 *
 * 清晰度（排版与分辨率）：
 * - 旧实现把内容等比压缩进 A4 宽度：1390px 宽的看板压到 785pt，字号只剩 75%，
 *   用户必须放大看，一放大就虚。现在改为 1 CSS px = 0.75pt（96dpi 实际大小）排版，
 *   页面尺寸跟着内容长（computePageSize，不低于 A4），内容不再被缩小。
 * - 渲染倍数按目标 DPI 反算（computeRenderScale）：1:1 排版下位图 DPI = scale × 96，
 *   故 scale = TARGET_RENDER_DPI / 96，并受画布像素预算约束。
 * - 位图以 JPEG（PDF_IMAGE_QUALITY）写入：jsPDF 对 JPEG 走 DCTDecode 原样嵌入、
 *   不做二次压缩；PNG 在 jsPDF 4 下会退化成未压缩流（实测同一页 1.4MB → 32MB），不可用。
 */
// jspdf 内部使用 Array.prototype.at（Chrome 92+），导出路径内先于动态导入补齐
import '@/compat/polyfills'

/** Chrome 81 没有 Intl.Segmenter（Chrome 87+），而 html2canvas-pro 无条件构造它。
 * 只在导出路径按需加载垫片，不进入首屏 chunk（ADR 0026 D3）。 */
export async function ensureIntlSegmenter(): Promise<void> {
  const hasSegmenter = typeof Intl !== 'undefined'
    && typeof (Intl as unknown as Record<string, unknown>).Segmenter === 'function'
  if (hasSegmenter) return
  await import('@formatjs/intl-segmenter/polyfill.js')
}

/** A4 纵向页面尺寸（pt） */
export const A4_PAGE_PT = { width: 595.28, height: 841.89 } as const
/** 页边距（pt），约 10mm */
export const PAGE_MARGIN_PT = 28.35
/** CSS px → pt 换算比：1 CSS px = 1/96 inch = 0.75pt（按此排版即「屏幕实际大小」） */
export const PX_TO_PT = 72 / 96
/** 单个 PDF 页面的尺寸上限（pt）：PDF 规范限制 14400 userUnit，超出部分改为分页 */
export const MAX_PAGE_PT = 14_400
/** 分页判定的浮点容差（pt）：避免「刚好等于一页」被进位成两页 */
export const EPSILON_PT = 0.01
/** 目标渲染 DPI —— 位图写入 PDF 后的等效每英寸像素数（300 满足印刷与放大查看） */
export const TARGET_RENDER_DPI = 300
/** 1:1 排版下 1 CSS px 即 1/96 inch，故位图 DPI = scale × CSS_DPI */
export const CSS_DPI = 96
/** 渲染缩放下限：避免位图比 CSS 像素还稀 */
export const MIN_RENDER_SCALE = 2
/** 渲染缩放上限：再高只是徒增内存与耗时 */
export const MAX_RENDER_SCALE = 4
/** 单张画布像素预算（面积），超出会触发浏览器画布限制或内存风险 */
export const MAX_CANVAS_PIXELS = 32_000_000
/** 单张画布单边上限（px） */
export const MAX_CANVAS_SIDE = 16_384
/** 写入 PDF 的 JPEG 质量（×100），低于此文字边缘会出现可见压缩伪影 */
export const PDF_IMAGE_QUALITY = 0.95

/** 依据内容宽高比选择纸张方向：内容宽 > 高为横向内容，用横版；否则竖版. */
export function pickOrientation(contentWidth: number, contentHeight: number): 'portrait' | 'landscape' {
  return contentWidth > contentHeight ? 'landscape' : 'portrait'
}

/** 依据内容物理尺寸（pt）计算 PDF 页面尺寸（pt）.
 *
 * 页面尺寸「不低于 A4」：取内容方向对应的 A4 边长作为基准，内容更大时页面按内容长大，
 * 保证内容始终以 1:1 尺寸落纸（不被压缩）；窄内容仍在 A4 页内居中。
 * 超过 MAX_PAGE_PT 时钳到上限，由调用方改为多页平铺。
 */
export function computePageSize(
  contentWidthPt: number,
  contentHeightPt: number,
  marginPt: number = PAGE_MARGIN_PT,
): { width: number; height: number } {
  const landscape = pickOrientation(contentWidthPt, contentHeightPt) === 'landscape'
  const baseWidthPt = landscape ? A4_PAGE_PT.height : A4_PAGE_PT.width
  const baseHeightPt = landscape ? A4_PAGE_PT.width : A4_PAGE_PT.height
  const width = Math.min(MAX_PAGE_PT, Math.max(baseWidthPt, contentWidthPt + marginPt * 2))
  const height = Math.min(MAX_PAGE_PT, Math.max(baseHeightPt, contentHeightPt + marginPt * 2))
  return { width, height }
}

/** 依据内容尺寸（CSS px）计算渲染缩放系数（html2canvas 的 scale）.
 *
 * 目标：位图写入 PDF 后达到 TARGET_RENDER_DPI。1:1 排版下 DPI = scale × CSS_DPI，
 * 故所需 scale 与内容尺寸无关（恒为 300/96 ≈ 3.125）。
 * 约束：
 *   - 结果不低于 MIN_RENDER_SCALE；
 *   - 受画布像素预算（面积 / 单边）与 MAX_RENDER_SCALE 压制 —— 超大内容时预算优先，
 *     宁可略糊也不能分配失败；
 *   - 非法输入回退到 MIN_RENDER_SCALE。
 */
export function computeRenderScale(contentWidth: number, contentHeight: number): number {
  if (!Number.isFinite(contentWidth) || !Number.isFinite(contentHeight)) return MIN_RENDER_SCALE
  if (contentWidth <= 0 || contentHeight <= 0) return MIN_RENDER_SCALE
  const desired = TARGET_RENDER_DPI / CSS_DPI
  const pixelCap = Math.sqrt(MAX_CANVAS_PIXELS / (contentWidth * contentHeight))
  const sideCap = MAX_CANVAS_SIDE / contentWidth
  const cap = Math.min(pixelCap, sideCap, MAX_RENDER_SCALE)
  const scale = Math.min(Math.max(MIN_RENDER_SCALE, desired), cap)
  // cap 可能低于 MIN（超大内容），但仍不放到 1 以下：位图至少要 1:1 覆盖 CSS 像素
  return Math.max(1, Number.isFinite(scale) ? scale : MIN_RENDER_SCALE)
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
 * 排版口径为「屏幕实际大小」：1 CSS px → PX_TO_PT(0.75pt)，页面尺寸跟着内容长（不低于 A4），
 * 因此内容永不被压扁、字号与屏幕上一致；窄内容仍在 A4 页内居中，视觉与旧版一致。
 *
 * @param target 视图内容区根元素（GridPage 的 gridAreaRef 容器；调用方须已在导出模式下
 *   关闭虚拟滚动，使全部行进入 DOM）
 * @param filename 下载文件名（需以 .pdf 结尾）
 * @throws 渲染或 PDF 生成失败时向上抛出原始错误，由调用方提示
 */
export async function exportViewToPdf(target: HTMLElement, filename: string): Promise<void> {
  // html2canvas-pro 内部无条件 new Intl.Segmenter：旧内核必须先补垫片再加载它
  await ensureIntlSegmenter()
  const [{ default: html2canvas }, { jsPDF }] = await Promise.all([
    import('html2canvas-pro'),
    import('jspdf'),
  ])

  // 放开滚动容器 → 按展开后的包围盒定画布尺寸 → 渲染完成后立即还原 DOM
  const restore = expandScrollContainers(target)
  const bounds = measureContentBounds(target)
  const renderScale = computeRenderScale(Math.ceil(bounds.width), Math.ceil(bounds.height))
  let canvas: HTMLCanvasElement
  try {
    canvas = await html2canvas(target, {
      scale: renderScale,
      backgroundColor: '#ffffff',
      useCORS: true,
      // 背景图/图标/圆角在缩放时的插值质量（文本不受影响）
      imageSmoothingQuality: 'high',
      width: Math.ceil(bounds.width),
      height: Math.ceil(bounds.height),
    })
  } finally {
    restore()
  }

  // 内容物理尺寸（pt）：1:1 排版，故直接由画布像素 / scale 换算，不依赖页面尺寸
  const contentWidthPt = (canvas.width / renderScale) * PX_TO_PT
  const contentHeightPt = (canvas.height / renderScale) * PX_TO_PT
  if (!(contentWidthPt > 0) || !(contentHeightPt > 0)) {
    throw new Error('PDF 导出失败：视图内容尺寸为空')
  }

  const { width: pageWidthPt, height: pageHeightPt } = computePageSize(contentWidthPt, contentHeightPt)
  // jsPDF 会按 orientation 给 format 排序：宽 > 高必须用 landscape，否则宽高会被交换
  const pdf = new jsPDF({
    unit: 'pt',
    format: [pageWidthPt, pageHeightPt],
    orientation: pageWidthPt > pageHeightPt ? 'landscape' : 'portrait',
  })

  const margin = PAGE_MARGIN_PT
  const availWidthPt = pageWidthPt - margin * 2
  const availHeightPt = pageHeightPt - margin * 2
  // 只有内容超出单页上限（MAX_PAGE_PT）时才分页；正常导出一律单页
  const cols = Math.max(1, Math.ceil((contentWidthPt - EPSILON_PT) / availWidthPt))
  const rows = Math.max(1, Math.ceil((contentHeightPt - EPSILON_PT) / availHeightPt))
  const offsetXPt = cols === 1 ? Math.max(0, (availWidthPt - contentWidthPt) / 2) : 0
  const offsetYPt = rows === 1 ? Math.max(0, (availHeightPt - contentHeightPt) / 2) : 0
  // 源 canvas 像素 / pt —— 用于按页裁切源位图（1:1 拷贝，不做二次缩放）
  const pxPerPt = canvas.width / contentWidthPt

  let pageIndex = 0
  for (let row = 0; row < rows; row++) {
    for (let col = 0; col < cols; col++) {
      const xPt = col * availWidthPt
      const yPt = row * availHeightPt
      const sliceWidthPt = Math.min(availWidthPt, contentWidthPt - xPt)
      const sliceHeightPt = Math.min(availHeightPt, contentHeightPt - yPt)
      if (!(sliceWidthPt > 0) || !(sliceHeightPt > 0)) continue

      if (pageIndex > 0) pdf.addPage()
      const sx = Math.round(xPt * pxPerPt)
      const sy = Math.round(yPt * pxPerPt)
      const sw = Math.max(1, Math.round(sliceWidthPt * pxPerPt))
      const sh = Math.max(1, Math.round(sliceHeightPt * pxPerPt))
      // 源 canvas 按页切片，避免整图重复嵌入每页
      const pageCanvas = document.createElement('canvas')
      pageCanvas.width = sw
      pageCanvas.height = sh
      const ctx = pageCanvas.getContext('2d')
      if (!ctx) throw new Error('PDF 导出失败：无法创建画布上下文')
      ctx.fillStyle = '#ffffff'
      ctx.fillRect(0, 0, sw, sh)
      ctx.drawImage(canvas, sx, sy, sw, sh, 0, 0, sw, sh)
      pdf.addImage(
        pageCanvas.toDataURL('image/jpeg', PDF_IMAGE_QUALITY),
        'JPEG',
        margin + offsetXPt + xPt,
        margin + offsetYPt + yPt,
        sliceWidthPt,
        sliceHeightPt,
      )
      pageIndex++
    }
  }

  pdf.save(filename)
}
