/**
 * docTreeSort 纯函数与共享偏好状态测试 —— 侧栏 / 内容区两处排序按钮与标题过滤框的联动基础（需求 0065）.
 */

import { act, renderHook } from '@testing-library/react'
import { describe, expect, it, beforeEach } from 'vitest'
import {
  DEFAULT_DOC_SORT,
  setDocSortPref,
  setDocTitleFilter,
  sortFlatByDocSort,
  useDocSortPref,
  useDocTitleFilter,
  type SortableDocBase,
} from './docTreeSort'

describe('sortFlatByDocSort 平铺排序', () => {
  const items = [
    { id: 1, title: '项目10', is_folder: false, pinned: false, created_at: '2026-01-02T00:00:00Z', updated_at: '2026-01-02T00:00:00Z' },
    { id: 2, title: '项目2', is_folder: false, pinned: false, created_at: '2026-01-03T00:00:00Z', updated_at: '2026-01-03T00:00:00Z' },
    { id: 3, title: '甲文件夹', is_folder: true, pinned: false, created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z' },
    { id: 4, title: '置顶文档', is_folder: false, pinned: true, created_at: '2026-01-04T00:00:00Z', updated_at: '2026-01-04T00:00:00Z' },
  ] satisfies SortableDocBase[]

  it('manual 档保持原顺序，仅置顶前置', () => {
    const out = sortFlatByDocSort(items, DEFAULT_DOC_SORT)
    expect(out.map(d => d.id)).toEqual([4, 1, 2, 3])
  })

  it('name 档文件夹恒在前，数字感知排序（项目2 < 项目10），置顶优先级最高', () => {
    const out = sortFlatByDocSort(items, { key: 'name', order: 'asc' })
    expect(out.map(d => d.id)).toEqual([4, 3, 2, 1])
  })

  it('created_at desc 档按时间倒序，文件夹仍在前', () => {
    const out = sortFlatByDocSort(items, { key: 'created_at', order: 'desc' })
    expect(out.map(d => d.id)).toEqual([4, 3, 2, 1])
  })
})

describe('共享排序偏好（useDocSortPref）', () => {
  beforeEach(() => {
    setDocSortPref(DEFAULT_DOC_SORT)
  })

  it('一处更新，所有订阅 hook 同步', () => {
    const a = renderHook(() => useDocSortPref())
    const b = renderHook(() => useDocSortPref())

    act(() => a.result.current[1]({ key: 'name', order: 'desc' }))

    expect(b.result.current[0]).toEqual({ key: 'name', order: 'desc' })
    // 偏好写入 localStorage（刷新后仍生效）
    expect(localStorage.getItem('cn-doc-tree-sort')).toBe('name-desc')
  })
})

describe('共享标题过滤关键词（useDocTitleFilter）', () => {
  it('侧栏与内容区输入框联动：一处输入两处可见', () => {
    const sidebar = renderHook(() => useDocTitleFilter())
    const content = renderHook(() => useDocTitleFilter())

    act(() => setDocTitleFilter('需求'))

    expect(content.result.current[0]).toBe('需求')
    act(() => content.result.current[1](''))
    expect(sidebar.result.current[0]).toBe('')
  })
})
