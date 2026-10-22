/** 主页收藏视图 / 自定义顺序的查询与乐观更新（ADR 0021）.
 *
 * 两个缓存分工：
 * - `PREFERENCES_QUERY_KEY`：当前用户偏好（含 favorite_view_ids / workspace_order），
 *   收藏切换与拖拽排序的写入真相源；
 * - `FAVORITE_VIEWS_QUERY_KEY`：面板摘要（视图 + 表 + 工作区），顺序与偏好一致。
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { preferencesApi } from '@/api'
import type { FavoriteViewSummary, UserPreferences } from '@/api'

export const PREFERENCES_QUERY_KEY = ['preferences'] as const
export const FAVORITE_VIEWS_QUERY_KEY = ['preferences', 'favorite-views'] as const

/** 收藏上限（与后端 `services/preferences.py` 的 MAX_FAVORITE_VIEWS 保持一致） */
export const MAX_FAVORITE_VIEWS = 50

/** 当前用户偏好（主页工作区顺序 / 收藏视图 id） */
export function usePreferences() {
  return useQuery<UserPreferences>({
    queryKey: PREFERENCES_QUERY_KEY,
    queryFn: preferencesApi.get,
    staleTime: 30_000,
  })
}

/** 「我的视图」摘要（按收藏顺序） */
export function useFavoriteViews() {
  return useQuery<FavoriteViewSummary[]>({
    queryKey: FAVORITE_VIEWS_QUERY_KEY,
    queryFn: preferencesApi.listFavoriteViews,
    staleTime: 30_000,
  })
}

function invalidateFavoriteCaches(qc: ReturnType<typeof useQueryClient>) {
  void qc.invalidateQueries({ queryKey: PREFERENCES_QUERY_KEY })
  void qc.invalidateQueries({ queryKey: FAVORITE_VIEWS_QUERY_KEY })
}

interface ToggleFavoriteVars {
  viewId: number | string
  /** true = 收藏；false = 取消收藏 */
  favorited: boolean
}

/** 收藏 / 取消收藏当前视图：先读最新偏好，再全量替换（避免用过期列表覆盖） */
export function useToggleFavoriteView() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ viewId, favorited }: ToggleFavoriteVars) => {
      const prefs = await qc.fetchQuery({
        queryKey: PREFERENCES_QUERY_KEY,
        queryFn: preferencesApi.get,
        staleTime: 0,
      })
      const id = Number(viewId)
      const next = prefs.favorite_view_ids.map(Number).filter(item => item !== id)
      if (favorited) next.push(id)
      return preferencesApi.setFavoriteViews(next)
    },
    onMutate: async ({ viewId, favorited }) => {
      await qc.cancelQueries({ queryKey: PREFERENCES_QUERY_KEY })
      const prevPrefs = qc.getQueryData<UserPreferences>(PREFERENCES_QUERY_KEY)
      const prevViews = qc.getQueryData<FavoriteViewSummary[]>(FAVORITE_VIEWS_QUERY_KEY)
      const id = Number(viewId)
      if (prevPrefs) {
        const ids = prevPrefs.favorite_view_ids.map(Number).filter(item => item !== id)
        if (favorited) ids.push(id)
        qc.setQueryData<UserPreferences>(PREFERENCES_QUERY_KEY, { ...prevPrefs, favorite_view_ids: ids })
      }
      if (prevViews && !favorited) {
        qc.setQueryData<FavoriteViewSummary[]>(
          FAVORITE_VIEWS_QUERY_KEY,
          prevViews.filter(item => Number(item.view_id) !== id),
        )
      }
      return { prevPrefs, prevViews }
    },
    onError: (_err, _vars, ctx) => {
      if (ctx?.prevPrefs) qc.setQueryData(PREFERENCES_QUERY_KEY, ctx.prevPrefs)
      if (ctx?.prevViews) qc.setQueryData(FAVORITE_VIEWS_QUERY_KEY, ctx.prevViews)
    },
    onSettled: () => invalidateFavoriteCaches(qc),
  })
}

/** 全量替换收藏顺序（拖拽排序） */
export function useSetFavoriteViews() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (viewIds: Array<number | string>) => preferencesApi.setFavoriteViews(viewIds),
    onMutate: async (viewIds) => {
      await qc.cancelQueries({ queryKey: FAVORITE_VIEWS_QUERY_KEY })
      const prevViews = qc.getQueryData<FavoriteViewSummary[]>(FAVORITE_VIEWS_QUERY_KEY)
      const prevPrefs = qc.getQueryData<UserPreferences>(PREFERENCES_QUERY_KEY)
      const ids = viewIds.map(Number)
      if (prevViews) {
        const byId = new Map(prevViews.map(item => [Number(item.view_id), item]))
        qc.setQueryData<FavoriteViewSummary[]>(
          FAVORITE_VIEWS_QUERY_KEY,
          ids.map(id => byId.get(id)).filter((item): item is FavoriteViewSummary => item != null),
        )
      }
      if (prevPrefs) {
        qc.setQueryData<UserPreferences>(PREFERENCES_QUERY_KEY, { ...prevPrefs, favorite_view_ids: ids })
      }
      return { prevViews, prevPrefs }
    },
    onError: (_err, _vars, ctx) => {
      if (ctx?.prevViews) qc.setQueryData(FAVORITE_VIEWS_QUERY_KEY, ctx.prevViews)
      if (ctx?.prevPrefs) qc.setQueryData(PREFERENCES_QUERY_KEY, ctx.prevPrefs)
    },
    onSettled: () => invalidateFavoriteCaches(qc),
  })
}

/** 全量替换工作区自定义顺序（拖拽排序） */
export function useSetWorkspaceOrder() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (workspaceIds: Array<number | string>) => preferencesApi.setWorkspaceOrder(workspaceIds),
    onMutate: async (workspaceIds) => {
      await qc.cancelQueries({ queryKey: PREFERENCES_QUERY_KEY })
      const prevPrefs = qc.getQueryData<UserPreferences>(PREFERENCES_QUERY_KEY)
      if (prevPrefs) {
        qc.setQueryData<UserPreferences>(PREFERENCES_QUERY_KEY, {
          ...prevPrefs,
          workspace_order: workspaceIds.map(Number),
        })
      }
      return { prevPrefs }
    },
    onError: (_err, _vars, ctx) => {
      if (ctx?.prevPrefs) qc.setQueryData(PREFERENCES_QUERY_KEY, ctx.prevPrefs)
    },
    onSettled: () => invalidateFavoriteCaches(qc),
  })
}
