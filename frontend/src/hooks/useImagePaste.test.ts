/**
 * useImagePaste 测试 —— 剪贴板取图口径 + 图片字段粘贴派发.
 *
 * 两条关键约束（改实现前先看这里）：
 * 1. 剪贴板带非空文本时必须当作「粘贴文本」，否则 Excel / Word / 网页复制的文字会消失；
 * 2. 多实例（整行编辑 / 详情抽屉）时只派发给最近获得焦点的实例，不猜。
 */

import { describe, expect, it, vi } from 'vitest'
import { fireEvent, renderHook, waitFor } from '@testing-library/react'
import { clipboardImageFiles, useImagePaste } from './useImagePaste'

/** 构造一个最小 DataTransfer 替身（jsdom 不实现剪贴板） */
function makeData(overrides: { files?: File[]; text?: string }): DataTransfer {
  const files = overrides.files ?? []
  const items = files.map(f => ({
    kind: 'file',
    type: f.type,
    getAsFile: () => f,
  }))
  return {
    items,
    files,
    types: files.length ? ['Files'] : ['text/plain'],
    getData: (type: string) => (type === 'text/plain' ? (overrides.text ?? '') : ''),
  } as unknown as DataTransfer
}

/** 派发一次 paste 事件（jsdom 的 ClipboardEvent 只读，手工挂 clipboardData） */
function firePaste(target: Element | Document | Window, data: DataTransfer) {
  const event = new Event('paste', { bubbles: true, cancelable: true })
  Object.defineProperty(event, 'clipboardData', { value: data })
  fireEvent(target, event)
  return event
}

const png = () => new File([new Uint8Array([1, 2, 3])], 'screenshot.png', { type: 'image/png' })

describe('clipboardImageFiles', () => {
  it('空剪贴板返回空数组', () => {
    expect(clipboardImageFiles(null)).toEqual([])
  })

  it('纯图片剪贴板提取为 File', () => {
    const file = png()
    expect(clipboardImageFiles(makeData({ files: [file] }))).toEqual([file])
  })

  it('同时带非空文本时不劫持（按粘贴文本处理）', () => {
    expect(clipboardImageFiles(makeData({ files: [png()], text: '单元格文字' }))).toEqual([])
  })

  it('只有空白文本时仍按图片处理', () => {
    expect(clipboardImageFiles(makeData({ files: [png()], text: '   ' }))).toHaveLength(1)
  })

  it('filename 为空时补可读名，保证后端 filename 非空', () => {
    const unnamed = new File([new Uint8Array([1])], '', { type: 'image/png' })
    const [file] = clipboardImageFiles(makeData({ files: [unnamed] }))
    expect(file.name).toMatch(/^paste-\d+-\d+\.png$/)
    expect(file.type).toBe('image/png')
  })

  it('非图片文件被忽略', () => {
    const pdf = new File([new Uint8Array([1])], 'a.pdf', { type: 'application/pdf' })
    expect(clipboardImageFiles(makeData({ files: [pdf] }))).toEqual([])
  })
})

describe('useImagePaste', () => {
  it('单实例：未聚焦也接收粘贴', () => {
    const handler = vi.fn()
    renderHook(() => useImagePaste(handler))

    const event = firePaste(document.body, makeData({ files: [png()] }))
    expect(handler).toHaveBeenCalledTimes(1)
    // 阻止默认，避免浏览器把图片当文件名文本插入
    expect(event.defaultPrevented).toBe(true)
  })

  it('多实例：只派发给最近聚焦的实例', async () => {
    const first = vi.fn()
    const second = vi.fn()
    const zoneA = document.createElement('div')
    const zoneB = document.createElement('div')
    zoneA.tabIndex = 0
    zoneB.tabIndex = 0
    document.body.append(zoneA, zoneB)

    const { result } = renderHook(() => ({
      a: useImagePaste(first),
      b: useImagePaste(second),
    }))
    result.current.a(zoneA)
    result.current.b(zoneB)

    zoneB.focus()
    firePaste(document.body, makeData({ files: [png()] }))
    await waitFor(() => expect(second).toHaveBeenCalledTimes(1))
    expect(first).not.toHaveBeenCalled()

    zoneA.focus()
    firePaste(document.body, makeData({ files: [png()] }))
    await waitFor(() => expect(first).toHaveBeenCalledTimes(1))
    expect(second).toHaveBeenCalledTimes(1)

    zoneA.remove()
    zoneB.remove()
  })

  it('enabled=false 时不接收粘贴', () => {
    const handler = vi.fn()
    renderHook(() => useImagePaste(handler, false))
    firePaste(document.body, makeData({ files: [png()] }))
    expect(handler).not.toHaveBeenCalled()
  })
})
