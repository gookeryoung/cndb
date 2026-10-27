/**
 * 图表保存图片（纯浏览器端）。
 *
 * 渲染链路产出的是后端 SVG 字符串，本模块把它转成可下载文件：
 * - SVG：文本直接下载（保留矢量，放大不失真）；
 * - PNG / JPEG：SVG → Blob URL → Image → canvas 栅格化（2x），JPEG 垫白底。
 */

export type ChartImageFormat = 'svg' | 'png' | 'jpeg'

export const CHART_IMAGE_FORMATS: { value: ChartImageFormat; label: string; ext: string }[] = [
  { value: 'png', label: 'PNG 图片', ext: 'png' },
  { value: 'jpeg', label: 'JPEG 图片', ext: 'jpg' },
  { value: 'svg', label: 'SVG 矢量图', ext: 'svg' },
]

/** 栅格化倍率（2x 保证常规截图场景清晰） */
const RASTER_SCALE = 2

/** SVG 缺命名空间时 Blob 加载会失败，补齐必需的 xmlns */
function ensureXmlns(svg: string): string {
  if (/<svg[^>]*\sxmlns=/.test(svg)) return svg
  return svg.replace(/<svg/, '<svg xmlns="http://www.w3.org/2000/svg"')
}

/** 从 SVG 文本读出像素尺寸；读不到时回退默认画布大小 */
function readSvgSize(svg: string): { width: number; height: number } {
  const wAttr = /<svg[^>]*\swidth="([\d.]+)(px)?"/.exec(svg)
  const hAttr = /<svg[^>]*\sheight="([\d.]+)(px)?"/.exec(svg)
  const width = wAttr ? Number(wAttr[1]) : 640
  const height = hAttr ? Number(hAttr[1]) : 400
  return {
    width: Number.isFinite(width) && width > 0 ? width : 640,
    height: Number.isFinite(height) && height > 0 ? height : 400,
  }
}

/** 触发浏览器下载 */
function triggerDownload(url: string, filename: string): void {
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
}

/** SVG 文本直接下载 */
export function downloadChartSvg(svg: string, filename: string): void {
  const blob = new Blob([ensureXmlns(svg)], { type: 'image/svg+xml;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  try {
    triggerDownload(url, filename)
  } finally {
    URL.revokeObjectURL(url)
  }
}

/** SVG → canvas 栅格化 dataURL（JPEG 垫白底，避免透明区域变黑） */
export async function rasterizeChartSvg(svg: string, format: 'png' | 'jpeg'): Promise<string> {
  const { width, height } = readSvgSize(svg)
  const blob = new Blob([ensureXmlns(svg)], { type: 'image/svg+xml;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  try {
    const img = await new Promise<HTMLImageElement>((resolve, reject) => {
      const image = new Image()
      image.onload = () => resolve(image)
      image.onerror = () => reject(new Error('svg load failed'))
      image.src = url
    })
    const canvas = document.createElement('canvas')
    canvas.width = Math.max(1, Math.round(width * RASTER_SCALE))
    canvas.height = Math.max(1, Math.round(height * RASTER_SCALE))
    const ctx = canvas.getContext('2d')
    if (!ctx) throw new Error('canvas unavailable')
    if (format === 'jpeg') {
      ctx.fillStyle = '#ffffff'
      ctx.fillRect(0, 0, canvas.width, canvas.height)
    }
    ctx.drawImage(img, 0, 0, canvas.width, canvas.height)
    return canvas.toDataURL(format === 'jpeg' ? 'image/jpeg' : 'image/png')
  } finally {
    URL.revokeObjectURL(url)
  }
}

/**
 * 按格式保存图表；返回是否已触发下载（供上层提示失败场景）。
 * 同一格式重复点击直接重走流程，不做缓存。
 */
export async function saveChartImage(svg: string, format: ChartImageFormat, title: string): Promise<boolean> {
  if (!svg) return false
  const safeTitle = (title || '图表').replace(/[\\/:*?"<>|]/g, '_').trim() || '图表'
  const def = CHART_IMAGE_FORMATS.find(f => f.value === format) ?? CHART_IMAGE_FORMATS[0]!
  if (format === 'svg') {
    downloadChartSvg(svg, `${safeTitle}.${def.ext}`)
    return true
  }
  try {
    const dataUrl = await rasterizeChartSvg(svg, format)
    triggerDownload(dataUrl, `${safeTitle}.${def.ext}`)
    return true
  } catch {
    return false
  }
}
