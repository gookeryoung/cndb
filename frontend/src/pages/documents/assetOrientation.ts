/** 原件方向判定（ADR 0164 P1）：EXIF / PDF 页面方向 + 长宽比兜底.
 *
 * 全部为纯函数，组件只消费结果，方便单测覆盖：
 * - 图片：EXIF Orientation 1..8 映射为 `(rotate, flip)`；无 EXIF 时按长宽比兜底；
 * - PDF：页面 `/Rotate` 由浏览器渲染时已生效，基线保持 0；无 `/Rotate` 时按长宽比兜底；
 * - 兜底只在高置信度（横置比例落在扫描件区间且阅读区竖置）自动应用，其余保持原始方向。
 */

export type Rotate = 0 | 90 | 180 | 270

export interface Orientation {
  rotate: Rotate
  flip: boolean
}

export interface PageOrientation {
  rotate: number
  width: number
  height: number
}

/** 后端 `/asset/orientation` 的响应（ADR 0164 P0） */
export interface PdfOrientationInfo {
  page_count: number
  uniform_rotate: number | null
  uniform_aspect: 'portrait' | 'landscape' | 'square' | 'mixed' | string
  pages: PageOrientation[]
}

export type AutoOrientationReason = 'exif' | 'pdf-rotate' | 'aspect' | 'none'

export interface AutoOrientationResult {
  orientation: Orientation
  confident: boolean
  reason: AutoOrientationReason
}

export interface DetectInput {
  kind: 'image' | 'pdf'
  /** 图片 EXIF Orientation（1..8），无则为 null */
  exifOrientation: number | null
  /** 图片原始尺寸（naturalWidth / naturalHeight），无则为 null */
  imageSize: { width: number; height: number } | null
  /** PDF 页面方向信息，非 PDF 或未取到则为 null */
  pdf: PdfOrientationInfo | null
  /** 阅读区尺寸（决定「横置页面 + 竖置阅读区」的兜底是否成立） */
  viewport: { width: number; height: number }
}

/** 扫描件横置的长宽比区间：覆盖 A4 横置 1.414 与 4:3 照片 1.333，排除 16:9 演示页与方图 */
export const LANDSCAPE_MIN_RATIO = 1.15
export const LANDSCAPE_MAX_RATIO = 1.5

const NO_ROTATION: Orientation = { rotate: 0, flip: false }

/** EXIF Orientation → 显示方向（变换顺序：先旋转、再在显示方向做水平镜像） */
export function orientationFromExif(value: number): Orientation {
  switch (value) {
    case 2:
      return { rotate: 0, flip: true }
    case 3:
      return { rotate: 180, flip: false }
    case 4:
      return { rotate: 180, flip: true }
    case 5:
      return { rotate: 90, flip: true }
    case 6:
      return { rotate: 90, flip: false }
    case 7:
      return { rotate: 270, flip: true }
    case 8:
      return { rotate: 270, flip: false }
    default:
      return NO_ROTATION
  }
}

/** 顺时针累加，0/90/180/270 回环 */
export function rotateBy(current: Orientation, degrees: number): Orientation {
  const next = (((current.rotate + degrees) % 360) + 360) % 360
  return { ...current, rotate: next as Rotate }
}

export function toggleFlip(current: Orientation): Orientation {
  return { ...current, flip: !current.flip }
}

/** 叠加手动调整：旋转相加取模，镜像异或（自动基线 + 用户手动） */
export function combineOrientations(base: Orientation, delta: Orientation): Orientation {
  const rotate = (((base.rotate + delta.rotate) % 360) + 360) % 360
  return { rotate: rotate as Rotate, flip: base.flip !== delta.flip }
}

export function sameOrientation(a: Orientation, b: Orientation): boolean {
  return a.rotate === b.rotate && a.flip === b.flip
}

export function isDefaultOrientation(state: Orientation): boolean {
  return state.rotate === 0 && !state.flip
}

/** CSS 变换：先旋转，再在显示方向做水平镜像（与 PDF 后端口径一致） */
export function orientationTransform(state: Orientation): string {
  const flip = state.flip ? -1 : 1
  return `scaleX(${flip}) rotate(${state.rotate}deg)`
}

function landscapeRatio(width: number, height: number): number | null {
  if (width <= 0 || height <= 0) return null
  const ratio = Math.max(width, height) / Math.min(width, height)
  return width > height ? ratio : null
}

function isPortraitViewport(viewport: { width: number; height: number }): boolean {
  return viewport.height > viewport.width
}

/** 长宽比兜底：横置且比例落在扫描件区间 + 阅读区竖置 → 顺时针 90° */
function aspectFallback(
  width: number | null,
  height: number | null,
  viewport: { width: number; height: number },
): Orientation | null {
  if (width === null || height === null) return null
  const ratio = landscapeRatio(width, height)
  if (ratio === null || ratio < LANDSCAPE_MIN_RATIO || ratio > LANDSCAPE_MAX_RATIO) return null
  if (!isPortraitViewport(viewport)) return null
  return { rotate: 90, flip: false }
}

/** 自动方向判定唯一入口（ADR 0164 D4）：高置信度才返回非原始方向 */
export function detectAutoOrientation(input: DetectInput): AutoOrientationResult {
  const { kind, exifOrientation, imageSize, pdf, viewport } = input

  if (kind === 'image') {
    if (exifOrientation !== null && exifOrientation >= 1 && exifOrientation <= 8) {
      return { orientation: orientationFromExif(exifOrientation), confident: true, reason: 'exif' }
    }
    const fallback = aspectFallback(imageSize?.width ?? null, imageSize?.height ?? null, viewport)
    if (fallback) return { orientation: fallback, confident: true, reason: 'aspect' }
    return { orientation: NO_ROTATION, confident: false, reason: 'none' }
  }

  if (pdf) {
    // 浏览器已按页面 /Rotate 渲染：基线保持 0，仅标记「已按页面方向标记显示」
    if (pdf.uniform_rotate !== null && pdf.uniform_rotate !== 0) {
      return { orientation: NO_ROTATION, confident: true, reason: 'pdf-rotate' }
    }
    const first = pdf.pages[0]
    if (pdf.uniform_aspect === 'landscape' && first) {
      const fallback = aspectFallback(first.width, first.height, viewport)
      if (fallback) return { orientation: fallback, confident: true, reason: 'aspect' }
    }
    return { orientation: NO_ROTATION, confident: false, reason: 'none' }
  }

  return { orientation: NO_ROTATION, confident: false, reason: 'none' }
}

/** 读取 JPEG 的 EXIF Orientation（1..8）；非 JPEG / 无 EXIF / 解析失败一律 null */
export function readExifOrientation(buffer: ArrayBuffer): number | null {
  const view = new DataView(buffer)
  if (view.byteLength < 4 || view.getUint16(0) !== 0xffd8) return null

  let offset = 2
  while (offset + 4 <= view.byteLength) {
    const marker = view.getUint16(offset)
    // EXIF APP1：FFE1 + 长度 + "Exif\0\0" + TIFF
    if (marker === 0xffe1) {
      const length = view.getUint16(offset + 2)
      const isExif =
        offset + 10 <= view.byteLength &&
        view.getUint32(offset + 4) === 0x45786966 && // "Exif"
        view.getUint16(offset + 8) === 0x0000
      if (isExif) {
        if (length < 8) return null
        return readTiffOrientation(view, offset + 10)
      }
      // 非 EXIF 的 APP1（如 XMP）：按长度跳过，继续找下一个段
      if (length < 2) return null
      offset += 2 + length
      continue
    }
    // 其它段：跳过（长度含自身 2 字节）；0xFFDA 之后是图像数据，不再有 EXIF
    if (marker === 0xffda || (marker & 0xff00) !== 0xff00) return null
    const length = view.getUint16(offset + 2)
    if (length < 2) return null
    offset += 2 + length
  }
  return null
}

function readTiffOrientation(view: DataView, start: number): number | null {
  const byteOrder = view.getUint16(start)
  const little = byteOrder === 0x4949
  if (!little && byteOrder !== 0x4d4d) return null
  if (view.getUint16(start + 2, little) !== 0x002a) return null

  const ifdOffset = view.getUint32(start + 4, little)
  const ifd = start + ifdOffset
  if (ifd + 2 > view.byteLength) return null

  const count = view.getUint16(ifd, little)
  for (let i = 0; i < count; i += 1) {
    const entry = ifd + 2 + i * 12
    if (entry + 12 > view.byteLength) return null
    if (view.getUint16(entry, little) !== 0x0112) continue
    const value = view.getUint16(entry + 8, little)
    return value >= 1 && value <= 8 ? value : null
  }
  return null
}
