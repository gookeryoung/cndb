/** 进入工作区的默认落地页顺序 — 每用户偏好（需求 0161）.
 *
 * 顺序存 `accounts_user.preferences.landing_order`（三模块完整排列，零迁移），
 * 与主页收藏 / 工作区顺序共用 `PREFERENCES_QUERY_KEY` 缓存，不额外发请求。
 *
 * 作用范围（卡片 C5）：只影响「进入工作区的默认落地」——根路由 `/w/:wid`
 * 与「落在未启用模块的回落」；顶部一级导航顺序、切工作区保持当前模块、
 * 深链与「继续上次」均不受影响。
 */

import { useMemo } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { preferencesApi } from '@/api'
import type { UserPreferences } from '@/api'
import {
  DEFAULT_LANDING_ORDER,
  normalizeLandingOrder,
  type WorkspaceModule,
} from '@/utils/workspaceModules'
import { PREFERENCES_QUERY_KEY, usePreferences } from './useFavoriteViews'

/** 当前用户的落地顺序（已归一为完整排列；未设置 / 非法值 → 默认序）.
 *  返回值在偏好未变时保持同一引用，可直接进依赖数组。 */
export function useLandingOrder(): WorkspaceModule[] {
  const { data } = usePreferences()
  const raw = data?.landing_order
  return useMemo(
    () => (raw ? normalizeLandingOrder(raw) : [...DEFAULT_LANDING_ORDER]),
    [raw],
  )
}

/** 全量替换落地顺序：乐观更新偏好缓存，失败回滚. */
export function useSetLandingOrder() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (order: WorkspaceModule[]) => preferencesApi.setLandingOrder(order),
    onMutate: async (order) => {
      await qc.cancelQueries({ queryKey: PREFERENCES_QUERY_KEY })
      const prev = qc.getQueryData<UserPreferences>(PREFERENCES_QUERY_KEY)
      if (prev) {
        qc.setQueryData<UserPreferences>(PREFERENCES_QUERY_KEY, {
          ...prev,
          landing_order: normalizeLandingOrder(order),
        })
      }
      return { prev }
    },
    onError: (_err, _order, ctx) => {
      if (ctx?.prev) qc.setQueryData(PREFERENCES_QUERY_KEY, ctx.prev)
    },
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: PREFERENCES_QUERY_KEY })
    },
  })
}
