/** 图片上传队列：排序 / 值归一化的纯逻辑测试. */

import { describe, expect, it, vi } from 'vitest'
import { act, renderHook } from '@testing-library/react'
import { useImageUploadQueue } from './useImageUploadQueue'

const A = { file_key: 'a.png', filename: 'a.png', mime_type: 'image/png' }
const B = { file_key: 'b.png', filename: 'b.png', mime_type: 'image/png' }
const C = { file_key: 'c.png', filename: 'c.png', mime_type: 'image/png' }

describe('useImageUploadQueue 排序', () => {
  it('reorder 按拖拽目标调整顺序并回写字段值', () => {
    const onChange = vi.fn()
    const { result } = renderHook(() =>
      useImageUploadQueue({ wid: 5, value: [A, B, C], onChange }),
    )

    // meta key 形如 m<index>:<file_key>
    act(() => result.current.reorder('m0:a.png', 'm2:c.png'))

    expect(onChange).toHaveBeenCalledWith([B, C, A])
  })

  it('reorder 忽略非 meta 项（上传中 / 失败项不参与排序）', () => {
    const onChange = vi.fn()
    const { result } = renderHook(() =>
      useImageUploadQueue({ wid: 5, value: [A, B], onChange }),
    )

    act(() => result.current.reorder('m0:a.png', 'not-exist'))

    expect(onChange).not.toHaveBeenCalled()
  })
})
