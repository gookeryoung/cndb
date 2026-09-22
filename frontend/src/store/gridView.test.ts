/** store/gridView 单元测试 —— setters、函数式更新、patch 批量、reset */
import { beforeEach, describe, expect, it } from 'vitest'
import { useGridViewStore } from './gridView'
import type { FilterRule, SortRule } from '@/pages/grid/view-config/ViewConfigDialog'

const filter: FilterRule = { field_name: 'status', op: '=', value: 'active' }
const sorting: SortRule = { field_name: 'created_at', direction: 'desc' }

beforeEach(() => {
  useGridViewStore.getState().reset()
})

describe('基础 setters', () => {
  it('setMode / setActiveViewId', () => {
    const s = useGridViewStore.getState()
    s.setMode('kanban')
    s.setActiveViewId(7)
    const st = useGridViewStore.getState()
    expect(st.mode).toBe('kanban')
    expect(st.activeViewId).toBe(7)
  })

  it('setViewFilters / setViewSortings / setViewFilterLogic', () => {
    const s = useGridViewStore.getState()
    s.setViewFilters([filter])
    s.setViewSortings([sorting])
    s.setViewFilterLogic('OR')
    const st = useGridViewStore.getState()
    expect(st.viewFilters).toEqual([filter])
    expect(st.viewSortings).toEqual([sorting])
    expect(st.viewFilterLogic).toBe('OR')
  })

  it('setViewOptionsDraft / setSearchQuery / setOffset / setLimit', () => {
    const s = useGridViewStore.getState()
    s.setViewOptionsDraft({ group_field: 'status' })
    s.setSearchQuery('关键词')
    s.setOffset(100)
    s.setLimit(25)
    const st = useGridViewStore.getState()
    expect(st.viewOptionsDraft).toEqual({ group_field: 'status' })
    expect(st.searchQuery).toBe('关键词')
    expect(st.offset).toBe(100)
    expect(st.limit).toBe(25)
  })
})

describe('函数式更新', () => {
  it('updateViewFilters 基于前一值追加', () => {
    const s = useGridViewStore.getState()
    s.setViewFilters([filter])
    s.updateViewFilters((prev) => [...prev, { field_name: 'age', op: '>', value: 3 }])
    expect(useGridViewStore.getState().viewFilters).toEqual([
      filter,
      { field_name: 'age', op: '>', value: 3 },
    ])
  })

  it('updateViewSortings 基于前一值替换', () => {
    const s = useGridViewStore.getState()
    s.setViewSortings([sorting])
    s.updateViewSortings((prev) => prev.map((r) => ({ ...r, direction: 'asc' as const })))
    expect(useGridViewStore.getState().viewSortings).toEqual([
      { field_name: 'created_at', direction: 'asc' },
    ])
  })
})

describe('patch 批量更新', () => {
  it('一次设置多个字段且不影响其它字段', () => {
    useGridViewStore.getState().patch({
      mode: 'gantt',
      activeViewId: 'v-1',
      viewFilters: [filter],
      viewSortings: [sorting],
      offset: 50,
    })
    const st = useGridViewStore.getState()
    expect(st.mode).toBe('gantt')
    expect(st.activeViewId).toBe('v-1')
    expect(st.viewFilters).toEqual([filter])
    expect(st.viewSortings).toEqual([sorting])
    expect(st.offset).toBe(50)
    // 未触碰的字段保持初值
    expect(st.limit).toBe(50)
    expect(st.searchQuery).toBe('')
  })
})

describe('reset 回初值', () => {
  it('修改后 reset 恢复全部初始状态', () => {
    const s = useGridViewStore.getState()
    s.setMode('calendar')
    s.setActiveViewId(9)
    s.setViewFilters([filter])
    s.setViewSortings([sorting])
    s.setViewFilterLogic('OR')
    s.setViewOptionsDraft({ a: 1 })
    s.setSearchQuery('q')
    s.setOffset(10)
    s.setLimit(5)

    useGridViewStore.getState().reset()

    const st = useGridViewStore.getState()
    expect(st.mode).toBe('grid')
    expect(st.activeViewId).toBeNull()
    expect(st.viewFilters).toEqual([])
    expect(st.viewSortings).toEqual([])
    expect(st.viewFilterLogic).toBe('AND')
    expect(st.viewOptionsDraft).toBeNull()
    expect(st.searchQuery).toBe('')
    expect(st.offset).toBe(0)
    expect(st.limit).toBe(50)
  })
})
