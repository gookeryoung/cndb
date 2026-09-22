/** GridPage 视图状态 store —— 替代 GridPage 内部散落的 useState.
 *
 * 涵盖：视图模式、激活视图、筛选/排序/搜索、分页、视图选项草稿。
 * UI 瞬时状态（对话框开关、选中行等）保留在 GridPage 组件内。
 *
 * 注：store 为单例，跨表导航时由 GridPage 在 wid/tid 变化时调用 reset() 清理.
 */

import { create } from 'zustand'
import type { FilterRule, SortRule } from '@/pages/grid/view-config/ViewConfigDialog'

export type ViewMode = 'grid' | 'kanban' | 'calendar' | 'gantt' | 'wbs'

interface GridViewState {
  /** 视图模式 */
  mode: ViewMode
  /** 当前激活的视图 ID（null = 默认视图） */
  activeViewId: number | string | null
  /** 当前视图的筛选条件 */
  viewFilters: FilterRule[]
  /** 当前视图的排序规则 */
  viewSortings: SortRule[]
  /** 筛选逻辑：AND / OR */
  viewFilterLogic: 'AND' | 'OR'
  /** 视图选项草稿（用于编辑中的临时状态） */
  viewOptionsDraft: Record<string, unknown> | null
  /** 搜索关键词 */
  searchQuery: string
  /** 分页偏移 */
  offset: number
  /** 每页行数 */
  limit: number

  // —— actions ——

  setMode: (mode: ViewMode) => void
  setActiveViewId: (id: number | string | null) => void
  setViewFilters: (filters: FilterRule[]) => void
  /** 支持函数式更新，同 React setState */
  updateViewFilters: (updater: (prev: FilterRule[]) => FilterRule[]) => void
  setViewSortings: (sortings: SortRule[]) => void
  /** 支持函数式更新，同 React setState */
  updateViewSortings: (updater: (prev: SortRule[]) => SortRule[]) => void
  setViewFilterLogic: (logic: 'AND' | 'OR') => void
  setViewOptionsDraft: (draft: Record<string, unknown> | null) => void
  setSearchQuery: (q: string) => void
  setOffset: (offset: number) => void
  setLimit: (limit: number) => void
  /** 批量更新部分字段 —— loadView 一次性设置 6+ 个状态时使用 */
  patch: (partial: Partial<Omit<GridViewState, 'patch' | 'reset'>>) => void
  /** 跨表导航时重置所有视图状态 */
  reset: () => void
}

const INITIAL_STATE: Pick<
  GridViewState,
  | 'mode'
  | 'activeViewId'
  | 'viewFilters'
  | 'viewSortings'
  | 'viewFilterLogic'
  | 'viewOptionsDraft'
  | 'searchQuery'
  | 'offset'
  | 'limit'
> = {
  mode: 'grid',
  activeViewId: null,
  viewFilters: [],
  viewSortings: [],
  viewFilterLogic: 'AND',
  viewOptionsDraft: null,
  searchQuery: '',
  offset: 0,
  limit: 50,
}

export const useGridViewStore = create<GridViewState>()((set) => ({
  ...INITIAL_STATE,

  setMode: (mode) => set({ mode }),
  setActiveViewId: (activeViewId) => set({ activeViewId }),
  setViewFilters: (viewFilters) => set({ viewFilters }),
  updateViewFilters: (updater) => set((state) => ({ viewFilters: updater(state.viewFilters) })),
  setViewSortings: (viewSortings) => set({ viewSortings }),
  updateViewSortings: (updater) => set((state) => ({ viewSortings: updater(state.viewSortings) })),
  setViewFilterLogic: (viewFilterLogic) => set({ viewFilterLogic }),
  setViewOptionsDraft: (viewOptionsDraft) => set({ viewOptionsDraft }),
  setSearchQuery: (searchQuery) => set({ searchQuery }),
  setOffset: (offset) => set({ offset }),
  setLimit: (limit) => set({ limit }),

  patch: (partial) => set(partial),
  reset: () => set(INITIAL_STATE),
}))
