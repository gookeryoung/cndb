/** React Query 自定义 hooks —— 统一 queryKey / enabled / staleTime.
 *
 * 抽取 GridPage、RowDetailDrawer 等组件里重复使用的 inline useQuery/useMutation，
 * 让调用点更简洁、queryKey 更一致、staleTime 可以在 main.tsx 按 key 前缀差异化配置.
 */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { tableApi, recordApi, viewApi, userApi, commentApi, auditApi } from './index'
import type {
  TableDetail, View, RowListResponse,
  AuditLog, Comment as ApiComment, Reference,
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

  return useQuery<RowListResponse>({
    queryKey: ['table-records', tableKey, mode, offset, limit, filters, sorts, params.filter_logic],
    queryFn: () =>
      recordApi.list(wid, tid, {
        offset,
        limit,
        filters,
        sorts,
        filter_logic: params.filter_logic,
      }),
    enabled: !!wid && !!tid,
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

export function useRowComments(wid: string, tid: string, rowId: number | string | undefined, enabled = true) {
  return useQuery<ApiComment[]>({
    queryKey: ['row-comments', wid, tid, rowId],
    queryFn: () => commentApi.list(wid, tid, rowId!),
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
      if (err instanceof Error) {
        console.warn('[useUpdateRowOptimistic] optimistic rollback:', err.message)
      }
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

// ─────────────── Comments（乐观更新） ───────────────

/** 乐观更新版 deleteComment —— 立即从 row-comments cache 移除，失败时回滚. */
export function useDeleteCommentOptimistic(wid: string, tid: string, rowId: number | string | undefined) {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (commentId: number | string) => commentApi.remove(wid, tid, commentId),
    onMutate: async (commentId) => {
      await queryClient.cancelQueries({ queryKey: ['row-comments', wid, tid, rowId] })

      const previous = queryClient.getQueryData<ApiComment[]>(['row-comments', wid, tid, rowId])

      if (previous) {
        queryClient.setQueryData<ApiComment[]>(['row-comments', wid, tid, rowId], previous.filter(c => c.id !== commentId))
      }

      return { previous }
    },
    onError: (_err, _commentId, context) => {
      if (context?.previous) {
        queryClient.setQueryData(['row-comments', wid, tid, rowId], context.previous)
      }
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ['row-comments', wid, tid, rowId] })
    },
  })
}

/** 乐观更新版 createComment —— 立即在 row-comments cache 前端插入临时评论，成功后替换真实 ID，失败时移除. */
export function useCreateCommentOptimistic(wid: string, tid: string, rowId: number | string | undefined) {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (content: string) => commentApi.create(wid, tid, rowId!, content),
    onMutate: async (content) => {
      await queryClient.cancelQueries({ queryKey: ['row-comments', wid, tid, rowId] })

      const previous = queryClient.getQueryData<ApiComment[]>(['row-comments', wid, tid, rowId]) ?? []

      // 生成带标记的临时评论 —— 用 '__temp_' 前缀标识，避免和真实数字 ID 冲突
      const tempId = `__temp_${Date.now()}_${Math.random().toString(36).slice(2, 6)}` as unknown as ApiComment['id']
      const optimisticComment: ApiComment = {
        id: tempId,
        content,
        author_name: '你',
        created_at: new Date().toISOString(),
        row_id: rowId as any,
      }

      queryClient.setQueryData<ApiComment[]>(['row-comments', wid, tid, rowId], [optimisticComment, ...previous])

      return { previous, tempId }
    },
    onSuccess: (realComment, _content, context) => {
      if (!context?.tempId) return
      // 用后端返回的真实评论对象替换临时占位
      queryClient.setQueryData<ApiComment[]>(['row-comments', wid, tid, rowId], (current) => {
        if (!current) return current
        return current.map(c => (c.id === context.tempId ? realComment : c))
      })
    },
    onError: (_err, _content, context) => {
      if (context?.previous) {
        queryClient.setQueryData(['row-comments', wid, tid, rowId], context.previous)
      }
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ['row-comments', wid, tid, rowId] })
    },
  })
}
