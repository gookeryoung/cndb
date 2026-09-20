/** React Query 自定义 hooks —— 统一 queryKey / enabled / staleTime.
 *
 * 抽取 GridPage、RowDetailDrawer 等组件里重复使用的 inline useQuery/useMutation，
 * 让调用点更简洁、queryKey 更一致、staleTime 可以在 main.tsx 按 key 前缀差异化配置.
 */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { App as AntApp } from 'antd'
import { tableApi, recordApi, viewApi, userApi, auditApi } from './index'
import type {
  TableDetail, View, RowListResponse,
  AuditLog, Reference,
} from './types'

// ─────────────── Tables ───────────────

export function useTable(wid: string, tid: string) {
  const tableKey = `${wid}/${tid}`
  return useQuery<TableDetail>({
    queryKey: ['table', tableKey],
    queryFn: () => tableApi.get(wid, tid),
    enabled: !!wid && !!tid,
  })
}

export function useTableViews(wid: string, tid: string) {
  const tableKey = `${wid}/${tid}`
  return useQuery<View[]>({
    queryKey: ['table-views', tableKey],
    queryFn: () => viewApi.list(wid, tid),
    enabled: !!wid && !!tid,
  })
}

export function useActiveViewPreference(tid: number | string) {
  return useQuery<{ table_id: number; active_view_id: number | null }>({
    queryKey: ['user-pref-active-view', tid],
    queryFn: () => userApi.getTableActiveView(tid),
    enabled: !!tid,
    staleTime: 60_000,
  })
}

// ─────────────── Records ───────────────

interface RecordsQueryParams {
  offset?: number
  limit?: number
  filters?: Array<Record<string, unknown>>
  sorts?: Array<Record<string, unknown>>
  filter_logic?: 'AND' | 'OR'
}

/** 把 filter/sort 数组序列化为稳定字符串，避免 queryKey 因引用变化而 cache miss. */
function _stableStr(value: unknown): string {
  if (!value) return ''
  try { return JSON.stringify(value) } catch { return String(value) }
}

export function useTableRecords(
  wid: string,
  tid: string,
  mode: string,
  params: RecordsQueryParams,
) {
  const tableKey = `${wid}/${tid}`
  const { offset = 0, limit = 25 } = params
  const filters = params.filters?.length ? params.filters : undefined
  const sorts = params.sorts?.length ? params.sorts : undefined

  // 用序列化字符串进 queryKey，避免数组引用每次 render 都变导致 cache miss
  const filtersKey = _stableStr(filters)
  const sortsKey = _stableStr(sorts)
  const filterLogic = params.filter_logic ?? 'AND'

  return useQuery<RowListResponse>({
    queryKey: ['table-records', tableKey, mode, offset, limit, filtersKey, sortsKey, filterLogic],
    queryFn: () =>
      recordApi.list(wid, tid, {
        offset,
        limit,
        filters,
        sorts,
        filter_logic: params.filter_logic,
      }),
    enabled: !!wid && !!tid,
    // staleTime 由 main.tsx 的 setQueryDefaults 全局配置（table-records: 10s），此处不重复覆盖
  })
}

// ─────────────── Row Detail 子查询 ───────────────

export function useRowAudit(wid: string, tid: string, rowId: number | string | undefined, enabled = true) {
  return useQuery<AuditLog[]>({
    queryKey: ['row-audit', wid, tid, rowId],
    queryFn: () => auditApi.list(wid, tid, undefined, 20, rowId),
    enabled: enabled && !!wid && !!tid && !!rowId,
  })
}

export function useRowReferences(wid: string, tid: string, rowId: number | string | undefined, enabled = true) {
  return useQuery<Reference[]>({
    queryKey: ['row-references', wid, tid, rowId],
    queryFn: () => tableApi.references(wid, tid, rowId!),
    enabled: enabled && !!wid && !!tid && !!rowId,
  })
}

// ─────────────── Mutations（集中常用的，调用点传参数即可） ───────────────

/** 乐观更新版 updateRow —— 立即修改 query cache，失败时回滚.
 *  调用点传 wid/tid，返回一个 mutation；调用 mutation.mutate({ rowId, fieldName, value }).
 */
export function useUpdateRowOptimistic(wid: string, tid: string) {
  const { message } = AntApp.useApp()
  const queryClient = useQueryClient()
  const tableKey = `${wid}/${tid}`

  return useMutation({
    mutationFn: async (args: { rowId: number | string; fieldName?: string; value?: unknown; values?: Record<string, unknown> }) => {
      const payload: Record<string, unknown> = args.values ?? (args.fieldName != null ? { [args.fieldName]: args.value } : {})
      return recordApi.update(wid, tid, args.rowId, { values: payload })
    },
    onMutate: async (args) => {
      // 1. 取消进行中的 table-records / row-audit 请求，避免覆盖乐观更新
      await queryClient.cancelQueries({ queryKey: ['table-records', tableKey] })
      await queryClient.cancelQueries({ queryKey: ['row-audit', wid, tid, args.rowId] })

      const previousRecordsQueries = queryClient.getQueriesData<RowListResponse>({
        queryKey: ['table-records', tableKey],
      })

      // 2. 直接在 cache 里改行数据 —— 支持单字段 { fieldName, value } 和多字段 { values } 两种调用方式
      const patch: Record<string, unknown> = args.values ?? (args.fieldName != null ? { [args.fieldName]: args.value } : {})
      previousRecordsQueries.forEach(([queryKey, data]) => {
        if (!data) return
        queryClient.setQueryData<RowListResponse>(queryKey, {
          ...data,
          items: data.items.map((r) =>
            r.id === args.rowId
              ? { ...r, ...patch }
              : r,
          ),
        })
      })

      return { previousRecordsQueries }
    },
    onError: (err, _args, context) => {
      // 回滚
      context?.previousRecordsQueries.forEach(([queryKey, data]) => {
        if (data) queryClient.setQueryData(queryKey, data)
      })
      const msg = err instanceof Error ? err.message : '保存失败'
      console.warn('[useUpdateRowOptimistic] optimistic rollback:', msg)
      message.error(msg)
    },
    onSettled: () => {
      // 最终仍走一次 invalidate，避免其他 query key 变体的 cache 不一致
      queryClient.invalidateQueries({ queryKey: ['table-records', tableKey] })
    },
  })
}

/** 乐观更新版 deleteRows —— 立即从 cache 移除被删行，失败时回滚. */
export function useDeleteRowsOptimistic(wid: string, tid: string) {
  const queryClient = useQueryClient()
  const tableKey = `${wid}/${tid}`

  return useMutation({
    mutationFn: (ids: Array<number | string>) =>
      recordApi.bulkDelete(wid, tid, ids),
    onMutate: async (ids) => {
      await queryClient.cancelQueries({ queryKey: ['table-records', tableKey] })

      const previousRecordsQueries = queryClient.getQueriesData<RowListResponse>({
        queryKey: ['table-records', tableKey],
      })

      const idSet = new Set(ids)
      previousRecordsQueries.forEach(([queryKey, data]) => {
        if (!data) return
        queryClient.setQueryData<RowListResponse>(queryKey, {
          ...data,
          items: data.items.filter(r => !idSet.has(r.id)),
          total: Math.max(0, data.total - ids.length),
        })
      })

      return { previousRecordsQueries }
    },
    onError: (_err, _ids, context) => {
      context?.previousRecordsQueries.forEach(([queryKey, data]) => {
        if (data) queryClient.setQueryData(queryKey, data)
      })
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ['table-records', tableKey] })
      queryClient.invalidateQueries({ queryKey: ['table', tableKey] })
    },
  })
}
