/** imageRef 纯函数测试 —— 站内图片引用构造与解析. */

import { describe, expect, it } from 'vitest'

import { buildImageSnippet, isImageFile, parseImageRef } from './imageRef'

describe('buildImageSnippet', () => {
  it('生成站内 file: 引用', () => {
    expect(buildImageSnippet('架构图.png', 'abc-123.png')).toBe('![架构图.png](file:abc-123.png)')
  })

  it('文件名中的方括号被剔除，避免语法被截断', () => {
    expect(buildImageSnippet('[草稿] 图.png', 'k.png')).toBe('![草稿 图.png](file:k.png)')
  })

  it('文件名全为特殊字符时回退为「图片」', () => {
    expect(buildImageSnippet('[]', 'k.png')).toBe('![图片](file:k.png)')
  })
})

describe('parseImageRef', () => {
  it('解析站内引用为 file_key', () => {
    expect(parseImageRef('file:abc.png')).toBe('abc.png')
  })

  it('去除引用周围空白', () => {
    expect(parseImageRef('file:  abc.png  ')).toBe('abc.png')
  })

  it('外部 URL / data: / 空值均返回 null', () => {
    expect(parseImageRef('https://example.com/a.png')).toBeNull()
    expect(parseImageRef('/api/v1/workspaces/1/files/a.png')).toBeNull()
    expect(parseImageRef('data:image/png;base64,AAAA')).toBeNull()
    expect(parseImageRef('file:   ')).toBeNull()
    expect(parseImageRef('')).toBeNull()
    expect(parseImageRef(undefined)).toBeNull()
    expect(parseImageRef(null)).toBeNull()
  })
})

describe('isImageFile', () => {
  it('按 MIME 判断', () => {
    expect(isImageFile({ type: 'image/png', name: 'a.bin' })).toBe(true)
    expect(isImageFile({ type: 'application/pdf', name: 'a.png' })).toBe(false)
  })

  it('MIME 缺失时回退扩展名判断（含大写）', () => {
    expect(isImageFile({ name: '照片.JPEG' })).toBe(true)
    expect(isImageFile({ name: 'diagram.webp' })).toBe(true)
    expect(isImageFile({ name: 'report.docx' })).toBe(false)
    expect(isImageFile({})).toBe(false)
  })
})
