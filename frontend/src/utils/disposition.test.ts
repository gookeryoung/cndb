import { describe, expect, it } from 'vitest'
import { parseContentDispositionFilename } from './disposition'

describe('parseContentDispositionFilename', () => {
  it('优先解析 RFC 5987 filename*（中文解码）', () => {
    expect(
      parseContentDispositionFilename(
        "attachment; filename=\"vault.zip\"; filename*=UTF-8''%E6%88%91%E7%9A%84%E7%9F%A5%E8%AF%86%E5%BA%93-obsidian-20261030-1200.zip",
      ),
    ).toBe('我的知识库-obsidian-20261030-1200.zip')
  })

  it('filename* 非法编码时回退 ASCII filename', () => {
    expect(parseContentDispositionFilename("attachment; filename=\"a.zip\"; filename*=UTF-8''%ZZ")).toBe('a.zip')
  })

  it('仅 ASCII filename 时直接返回', () => {
    expect(parseContentDispositionFilename('attachment; filename="a.zip"')).toBe('a.zip')
    expect(parseContentDispositionFilename('attachment; filename=a.zip')).toBe('a.zip')
  })

  it('缺失或无法解析时返回 null', () => {
    expect(parseContentDispositionFilename(undefined)).toBeNull()
    expect(parseContentDispositionFilename('attachment')).toBeNull()
  })
})
