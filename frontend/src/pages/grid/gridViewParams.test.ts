import { describe, expect, it } from 'vitest'
import { normalizeFilters, resolveLandingView, viewModeOf } from './gridViewParams'
import type { View } from '@/api'

function view(partial: Partial<View>): View {
  return { id: 1, name: 'v', ...partial } as View
}

describe('viewModeOf', () => {
  it('独立视图类型映射到同名模式', () => {
    expect(viewModeOf('gallery')).toBe('gallery')
    expect(viewModeOf('dashboard')).toBe('dashboard')
  })

  it('表格 / 空值回落 grid', () => {
    expect(viewModeOf('table')).toBe('grid')
    expect(viewModeOf(null)).toBe('grid')
    expect(viewModeOf(undefined)).toBe('grid')
  })
})

describe('normalizeFilters', () => {
  it('list 形态原样归一化，空值字段不带 value', () => {
    expect(normalizeFilters([{ field_name: 'status', op: '=', value: 'open' }, { field_name: 'x', op: '>', value: null }]))
      .toEqual([
        { field_name: 'status', op: '=', value: 'open' },
        { field_name: 'x', op: '>' },
      ])
  })

  it('dict 形态转成 list，跳过 $query', () => {
    expect(normalizeFilters({ status: { op: '=', value: 'open' }, name: '张三', $query: 'x' })).toEqual([
      { field_name: 'status', op: '=', value: 'open' },
      { field_name: 'name', op: '=', value: '张三' },
    ])
  })

  it('空值 / 非法类型返回空数组', () => {
    expect(normalizeFilters(null)).toEqual([])
    expect(normalizeFilters('bad')).toEqual([])
    expect(normalizeFilters([null, 1])).toEqual([])
  })
})

describe('resolveLandingView', () => {
  it('URL 指定视图优先', () => {
    const views = [view({ id: 1, is_default: true }), view({ id: 2 })]
    expect(resolveLandingView(views, '2')?.id).toBe(2)
  })

  it('URL 视图不存在时回落默认视图', () => {
    const views = [view({ id: 1 }), view({ id: 2, is_default: true })]
    expect(resolveLandingView(views, '99')?.id).toBe(2)
  })

  it('无默认视图时取第一个；空列表返回 null', () => {
    expect(resolveLandingView([view({ id: 3 }), view({ id: 4 })], null)?.id).toBe(3)
    expect(resolveLandingView([], null)).toBeNull()
  })
})
