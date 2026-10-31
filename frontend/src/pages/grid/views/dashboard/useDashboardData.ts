/** dashboard 服务端批量取数（ADR 0023 P2）.
 *
 * 大表（总行数 > `VIEW_FETCH_ALL_LIMIT`）不拉全量行：一次请求把画布内所有
 * 图表 / KPI / 明细 widget 交给服务端，同表只扫描一次、多 widget 共享行集。
 * 小表仍由 `DashboardView` 用已有行集在客户端装配 Dataset，两条链路同构。
 *
 * TanStack Query 以 `(视图 id, updated_at, widget 集合)` 为键，`staleTime: 60s`，
 * 同一查询的多个 widget 共享同一份响应；保存后 `updated_at` 变化自然触发刷新。
 */

import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { viewApi } from '@/api/views'
import type { View } from '@/api'
import type { Dataset, DatasetMeta } from './chart/types'

/** 参与服务端取数的 widget 类型（文本卡片无需数据） */
const DATA_WIDGET_TYPES = new Set(['chart', 'kpi', 'table'])

export interface DashboardDataState {
  /** widget_id → Dataset（已合并 meta） */
  datasets: Map<string, Dataset>
  /** widget_id → 失败文案；单卡失败不影响其它卡片 */
  errors: Map<string, string>
  meta: Map<string, DatasetMeta>
  loading: boolean
  refetch: () => void
}

interface UseDashboardDataParams {
  wid?: string | number
  tid?: string | number
  view?: View | null
  /** 仅大表路径启用；小表走客户端聚合 */
  enabled: boolean
}

/** 从落库配置中读取参与取数的 widget id（编辑态新增但未保存的组件不在其列） */
function persistedWidgetIds(view: View | null | undefined): string[] {
  const raw = view?.view_options as { widgets?: unknown } | null | undefined
  const widgets = Array.isArray(raw?.widgets) ? raw.widgets : []
  const out: string[] = []
  for (const item of widgets) {
    if (!item || typeof item !== 'object') continue
    const widget = item as { id?: unknown; type?: unknown }
    if (typeof widget.id === 'string' && typeof widget.type === 'string' && DATA_WIDGET_TYPES.has(widget.type)) {
      out.push(widget.id)
    }
  }
  return out
}

export function useDashboardData({ wid, tid, view, enabled }: UseDashboardDataParams): DashboardDataState {
  const widgetIds = useMemo(() => persistedWidgetIds(view), [view])
  const idKey = widgetIds.join(',')
  const query = useQuery({
    queryKey: ['dashboard-data', String(wid ?? ''), String(tid ?? ''), view?.id ?? 0, view?.updated_at ?? '', idKey],
    queryFn: () => viewApi.dashboardData(wid!, tid!, view!.id, { widget_ids: widgetIds }),
    enabled: enabled && !!wid && !!tid && !!view && widgetIds.length > 0,
    staleTime: 60_000,
  })

  const { datasets, errors, meta } = useMemo(() => {
    const datasets = new Map<string, Dataset>()
    const errors = new Map<string, string>()
    const meta = new Map<string, DatasetMeta>()
    for (const item of query.data?.items ?? []) {
      const ds = item.dataset as unknown as Dataset
      if (!ds || typeof ds !== 'object' || typeof ds.kind !== 'string') {
        errors.set(item.widget_id, '数据格式异常')
        continue
      }
      datasets.set(item.widget_id, { ...ds, meta: item.meta })
      meta.set(item.widget_id, item.meta)
    }
    for (const item of query.data?.errors ?? []) {
      errors.set(item.widget_id, item.detail || '取数失败')
    }
    return { datasets, errors, meta }
  }, [query.data])

  return {
    datasets,
    errors,
    meta,
    loading: query.isFetching,
    refetch: () => { void query.refetch() },
  }
}
