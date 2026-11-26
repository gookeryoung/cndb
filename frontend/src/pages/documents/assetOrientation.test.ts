/** 原件方向判定单测（ADR 0164 P1 / §7 判定层）.
 *
 * 纯逻辑：EXIF 1..8 映射、长宽比兜底、PDF 页面方向、旋转回环与变换字符串。
 */
import { describe, expect, it } from 'vitest'
import {
  combineOrientations,
  detectAutoOrientation,
  isDefaultOrientation,
  orientationFromExif,
  orientationTransform,
  readExifOrientation,
  rotateBy,
  sameOrientation,
  toggleFlip,
  type PdfOrientationInfo,
} from './assetOrientation'

/** 构造只含 EXIF Orientation 的最小 JPEG（FFD8 + APP1 + TIFF + FFD9） */
function jpegWithExif(orientation: number): ArrayBuffer {
  const tiff = new Uint8Array(26)
  const tiffView = new DataView(tiff.buffer)
  tiffView.setUint16(0, 0x4949) // little endian
  tiffView.setUint16(2, 0x002a, true)
  tiffView.setUint32(4, 8, true) // IFD0 offset
  tiffView.setUint16(8, 1, true) // entry count
  tiffView.setUint16(10, 0x0112, true) // Orientation tag
  tiffView.setUint16(12, 3, true) // SHORT
  tiffView.setUint32(14, 1, true)
  tiffView.setUint16(18, orientation, true)
  tiffView.setUint32(22, 0, true) // next IFD

  const exifHeader = new Uint8Array([0x45, 0x78, 0x69, 0x66, 0, 0]) // "Exif\0\0"
  const payload = new Uint8Array(exifHeader.length + tiff.length)
  payload.set(exifHeader)
  payload.set(tiff, exifHeader.length)

  const out = new Uint8Array(6 + payload.length + 2)
  out[0] = 0xff
  out[1] = 0xd8
  out[2] = 0xff
  out[3] = 0xe1
  new DataView(out.buffer).setUint16(4, payload.length + 2)
  out.set(payload, 6)
  out[out.length - 2] = 0xff
  out[out.length - 1] = 0xd9
  return out.buffer
}

function pdfInfo(patch: Partial<PdfOrientationInfo> = {}): PdfOrientationInfo {
  return {
    page_count: 1,
    uniform_rotate: 0,
    uniform_aspect: 'portrait',
    pages: [{ rotate: 0, width: 595, height: 842 }],
    ...patch,
  }
}

const PORTRAIT_VIEWPORT = { width: 800, height: 1000 }
const LANDSCAPE_VIEWPORT = { width: 1200, height: 700 }

describe('orientationFromExif', () => {
  it('covers all 8 EXIF orientations', () => {
    expect(orientationFromExif(1)).toEqual({ rotate: 0, flip: false })
    expect(orientationFromExif(2)).toEqual({ rotate: 0, flip: true })
    expect(orientationFromExif(3)).toEqual({ rotate: 180, flip: false })
    expect(orientationFromExif(4)).toEqual({ rotate: 180, flip: true })
    expect(orientationFromExif(5)).toEqual({ rotate: 90, flip: true })
    expect(orientationFromExif(6)).toEqual({ rotate: 90, flip: false })
    expect(orientationFromExif(7)).toEqual({ rotate: 270, flip: true })
    expect(orientationFromExif(8)).toEqual({ rotate: 270, flip: false })
  })

  it('falls back to original for unknown values', () => {
    expect(orientationFromExif(0)).toEqual({ rotate: 0, flip: false })
    expect(orientationFromExif(9)).toEqual({ rotate: 0, flip: false })
  })
})

describe('readExifOrientation', () => {
  it('reads orientation from JPEG APP1', () => {
    expect(readExifOrientation(jpegWithExif(6))).toBe(6)
    expect(readExifOrientation(jpegWithExif(1))).toBe(1)
    expect(readExifOrientation(jpegWithExif(8))).toBe(8)
  })

  it('returns null for non-JPEG, no EXIF and truncated data', () => {
    expect(readExifOrientation(new Uint8Array([0x89, 0x50, 0x4e, 0x47]).buffer)).toBeNull()
    expect(readExifOrientation(new Uint8Array([0xff, 0xd8, 0xff, 0xd9]).buffer)).toBeNull()
    expect(readExifOrientation(jpegWithExif(6).slice(0, 10))).toBeNull()
  })
})

describe('orientation helpers', () => {
  it('rotates with wraparound', () => {
    expect(rotateBy({ rotate: 0, flip: false }, 90)).toEqual({ rotate: 90, flip: false })
    expect(rotateBy({ rotate: 270, flip: false }, 90)).toEqual({ rotate: 0, flip: false })
    expect(rotateBy({ rotate: 270, flip: true }, 180)).toEqual({ rotate: 90, flip: true })
  })

  it('toggles flip and compares states', () => {
    const flipped = toggleFlip({ rotate: 0, flip: false })
    expect(flipped).toEqual({ rotate: 0, flip: true })
    expect(toggleFlip(flipped)).toEqual({ rotate: 0, flip: false })
    expect(sameOrientation({ rotate: 90, flip: true }, { rotate: 90, flip: true })).toBe(true)
    expect(isDefaultOrientation({ rotate: 0, flip: false })).toBe(true)
    expect(isDefaultOrientation({ rotate: 0, flip: true })).toBe(false)
  })

  it('builds CSS transform with rotate then displayed-horizontal mirror', () => {
    expect(orientationTransform({ rotate: 90, flip: false })).toBe('scaleX(1) rotate(90deg)')
    expect(orientationTransform({ rotate: 0, flip: true })).toBe('scaleX(-1) rotate(0deg)')
  })

  it('combines auto baseline with manual delta', () => {
    expect(combineOrientations({ rotate: 0, flip: false }, { rotate: 90, flip: false })).toEqual({
      rotate: 90,
      flip: false,
    })
    expect(combineOrientations({ rotate: 270, flip: false }, { rotate: 180, flip: true })).toEqual({
      rotate: 90,
      flip: true,
    })
    expect(combineOrientations({ rotate: 0, flip: true }, { rotate: 0, flip: true })).toEqual({
      rotate: 0,
      flip: false,
    })
  })
})

describe('detectAutoOrientation / image', () => {
  const base = {
    kind: 'image' as const,
    exifOrientation: null,
    imageSize: null,
    pdf: null,
    viewport: PORTRAIT_VIEWPORT,
  }

  it('uses EXIF when present', () => {
    const result = detectAutoOrientation({ ...base, exifOrientation: 6 })
    expect(result).toEqual({ orientation: { rotate: 90, flip: false }, confident: true, reason: 'exif' })
  })

  it('falls back to aspect for landscape scan in portrait area', () => {
    const result = detectAutoOrientation({
      ...base,
      imageSize: { width: 1600, height: 1200 }, // 4:3
    })
    expect(result).toEqual({ orientation: { rotate: 90, flip: false }, confident: true, reason: 'aspect' })
  })

  it('does not auto-rotate for 16:9, square, portrait image or landscape area', () => {
    expect(
      detectAutoOrientation({ ...base, imageSize: { width: 1920, height: 1080 } }).confident,
    ).toBe(false)
    expect(
      detectAutoOrientation({ ...base, imageSize: { width: 1000, height: 1000 } }).confident,
    ).toBe(false)
    expect(
      detectAutoOrientation({ ...base, imageSize: { width: 1200, height: 1600 } }).confident,
    ).toBe(false)
    expect(
      detectAutoOrientation({
        ...base,
        imageSize: { width: 1600, height: 1200 },
        viewport: LANDSCAPE_VIEWPORT,
      }).confident,
    ).toBe(false)
  })
})

describe('detectAutoOrientation / pdf', () => {
  const base = {
    kind: 'pdf' as const,
    exifOrientation: null,
    imageSize: null,
    viewport: PORTRAIT_VIEWPORT,
  }

  it('keeps baseline 0 when pages declare rotation (browser already applies it)', () => {
    const result = detectAutoOrientation({
      ...base,
      pdf: pdfInfo({ uniform_rotate: 90, uniform_aspect: 'portrait' }),
    })
    expect(result).toEqual({ orientation: { rotate: 0, flip: false }, confident: true, reason: 'pdf-rotate' })
  })

  it('falls back to aspect for undeclared landscape pages', () => {
    const result = detectAutoOrientation({
      ...base,
      pdf: pdfInfo({ uniform_aspect: 'landscape', pages: [{ rotate: 0, width: 842, height: 595 }] }),
    })
    expect(result).toEqual({ orientation: { rotate: 90, flip: false }, confident: true, reason: 'aspect' })
  })

  it('does not auto-rotate mixed or portrait pages, or without info', () => {
    expect(
      detectAutoOrientation({ ...base, pdf: pdfInfo({ uniform_aspect: 'mixed' }) }).confident,
    ).toBe(false)
    expect(detectAutoOrientation({ ...base, pdf: null }).confident).toBe(false)
  })
})
