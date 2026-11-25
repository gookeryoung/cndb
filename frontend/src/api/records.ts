/** 行记录 API — /api/v1/workspaces/{wid}/tables/{tid}/records/*（含批量操作） */

import api from './client'
import type { RowCreate, RowUpdate, RowResponse, RowListResponse, RecordListParams, ChangeRequestBatchResponse, AutoIncrementPreview, MatrixUpsertPayload, MatrixUpsertResponse } from './types'

export const recordApi = {
  list: (wid: number | string, tid: number | string, params?: RecordListParams) => {
    // GET 端点：filters/sorts 用 JSON 字符串
    const qp: Record<string, unknown> = { offset: params?.offset, limit: params?.limit }
    if (params?.filters) qp.filters = typeof params.filters === 'string' ? params.filters : JSON.stringify(params.filters)
    if (params?.sorts) qp.sorts = typeof params.sorts === 'string' ? params.sorts : JSON.stringify(params.sorts)
    if (params?.filter_logic) qp.filter_logic = params.filter_logic
    // 回收站三态（ADR 0139 C2）：none（默认）/ only / include
    if (params?.trashed) qp.trashed = params.trashed
    return api.get<RowListResponse>(`/v1/workspaces/${wid}/tables/${tid}/records`, { params: qp }).then(r => r.data)
  },
  /** 新建行：直编直存（201 RowResponse）；查看者/关闭直编时提交 create 修改申请（202 ChangeRequestDispatchResponse） */
  create: (wid: number | string, tid: number | string, data: RowCreate): Promise<RowResponse | ChangeRequestBatchResponse> =>
    api.post<RowResponse | ChangeRequestBatchResponse>(`/v1/workspaces/${wid}/tables/${tid}/records`, data).then(r => r.data),
  /** 评分矩阵单元格 upsert：按（对象, 月份）新建 / 更新 / 清空（ADR 0136） */
  matrixUpsert: (wid: number | string, tid: number | string, data: MatrixUpsertPayload) =>
    api.post<MatrixUpsertResponse>(`/v1/workspaces/${wid}/tables/${tid}/records/matrix-upsert`, data).then(r => r.data),
  /** 复制行：按源行原值批量创建（后端不套用自动填充 / 默认值 / 自动编号） */
  copyRows: (wid: number | string, tid: number | string, rowIds: Array<number | string>) =>
    api
      .post<{ created: number; ids: number[] }>(`/v1/workspaces/${wid}/tables/${tid}/records/copy`, { row_ids: rowIds })
      .then(r => r.data),
  get: (wid: number | string, tid: number | string, rid: number | string) =>
    api.get<RowResponse>(`/v1/workspaces/${wid}/tables/${tid}/records/${rid}`).then(r => r.data),
  /** 自动编号预览：新增行只读展示「即将生成的编号」，按库内已有数据 max+1 推算 */
  nextIncrementPreview: (wid: number | string, tid: number | string) =>
    api.get<AutoIncrementPreview>(`/v1/workspaces/${wid}/tables/${tid}/records/auto-increment-preview`).then(r => r.data),
  /** 更新行：直编直存（200 RowResponse）；查看者/关闭直编时提交 update 修改申请（202 ChangeRequestDispatchResponse） */
  update: (
    wid: number | string,
    tid: number | string,
    rid: number | string,
    data: RowUpdate,
    options?: { ifMatch?: string },
  ): Promise<RowResponse | ChangeRequestBatchResponse> =>
    api
      .patch<RowResponse | ChangeRequestBatchResponse>(
        `/v1/workspaces/${wid}/tables/${tid}/records/${rid}`,
        data,
        options?.ifMatch ? { headers: { 'If-Match': options.ifMatch } } : undefined,
      )
      .then(r => r.data),
  /** 删除行：直删返回 204 空 body（归一化为 null）；查看者/关闭直编时提交 delete 修改申请（202 修改申请载荷） */
  remove: (wid: number | string, tid: number | string, rid: number | string, soft = true): Promise<ChangeRequestBatchResponse | null> =>
    api.delete<ChangeRequestBatchResponse>(`/v1/workspaces/${wid}/tables/${tid}/records/${rid}`, { params: { soft } })
      .then(r => (r.data && typeof r.data === 'object' ? r.data : null)),
  restore: (wid: number | string, tid: number | string, rid: number | string) =>
    api.post<RowResponse>(`/v1/workspaces/${wid}/tables/${tid}/records/${rid}/restore`).then(r => r.data),
  /** 批量恢复回收站行（ADR 0139 C3；重复恢复幂等） */
  restoreMany: (wid: number | string, tid: number | string, ids: Array<number | string>) =>
    api.post<{ restored: number }>(`/v1/workspaces/${wid}/tables/${tid}/records/restore`, { row_ids: ids }).then(r => r.data),
  /** 彻底删除单行（仅限回收站中的行，ADR 0139 C4） */
  purge: (wid: number | string, tid: number | string, rid: number | string) =>
    api.post<{ id: number; purged: boolean }>(`/v1/workspaces/${wid}/tables/${tid}/records/${rid}/purge`).then(r => r.data),
  /** 批量彻底删除（仅限回收站中的行） */
  purgeMany: (wid: number | string, tid: number | string, ids: Array<number | string>) =>
    api.post<{ purged: number }>(`/v1/workspaces/${wid}/tables/${tid}/records/purge`, { row_ids: ids }).then(r => r.data),
  // 批量
  bulkCreate: (wid: number | string, tid: number | string, rows: Array<Record<string, unknown>>) =>
    api.post<{ created: number; ids: number[] }>(`/v1/workspaces/${wid}/tables/${tid}/records/bulk-create`, { rows }).then(r => r.data),
  bulkDelete: (
    wid: number | string,
    tid: number | string,
    ids: Array<number | string>,
    options?: { selectAll?: boolean; filters?: Array<Record<string, unknown>>; filterLogic?: 'AND' | 'OR' },
  ) =>
    api
      .post<{ deleted: number }>(`/v1/workspaces/${wid}/tables/${tid}/records/bulk-delete`, {
        row_ids: ids,
        ...(options?.selectAll
          ? { select_all: true, filters: options.filters ?? [], filter_logic: options.filterLogic }
          : {}),
      })
      .then(r => r.data),
  bulkUpdate: (wid: number | string, tid: number | string, ids: Array<number | string>, values: Record<string, unknown>) =>
    api.post<{ updated: number }>(`/v1/workspaces/${wid}/tables/${tid}/records/bulk-update`, { row_ids: ids, values }).then(r => r.data),
  /** 行级历史（需求 0144）：版本倒序 */
  history: (wid: number | string, tid: number | string, rid: number | string, limit = 50) =>
    api
      .get<RowRevision[]>(`/v1/workspaces/${wid}/tables/${tid}/records/${rid}/history`, { params: { limit } })
      .then(r => r.data),
  /** 撤销到某版本之前的值（生成新版本；写权限与双轨分派由后端判定） */
  revert: (wid: number | string, tid: number | string, rid: number | string, version: number) =>
    api
      .post<RowResponse | ChangeRequestBatchResponse>(
        `/v1/workspaces/${wid}/tables/${tid}/records/${rid}/revert/${version}`,
      )
      .then(r => r.data),
  /** 服务端聚合 / 分组（需求 0147）：默认按筛选范围全表统计 */
  aggregate: (wid: number | string, tid: number | string, payload: AggregatePayload) =>
    api.post<AggregateResult>(`/v1/workspaces/${wid}/tables/${tid}/records/aggregate`, payload).then(r => r.data),
  /** 批量查找替换（需求 0149）：默认 dry_run 只预览，确认后带 dry_run=false 落库 */
  bulkReplace: (wid: number | string, tid: number | string, payload: BulkReplacePayload) =>
    api.post<BulkReplaceResult>(`/v1/workspaces/${wid}/tables/${tid}/records/bulk-replace`, payload).then(r => r.data),
}

export interface RowRevision {
  id: number
  row_id: number
  version: number
  op: string
  actor_id: number | null
  actor_name: string | null
  diff: Record<string, { old?: unknown; new?: unknown }>
  created_at: string | null
}

export interface AggregateMetricPayload {
  field?: string
  agg: 'count' | 'sum' | 'avg' | 'min' | 'max' | 'distinct'
  alias?: string
}

export interface AggregatePayload {
  group_by?: string[]
  metrics: AggregateMetricPayload[]
  filters?: Array<Record<string, unknown>>
  filter_logic?: 'AND' | 'OR'
  order_by?: { by: 'group' | 'metric'; index: number; direction: 'asc' | 'desc' }
  limit?: number
}

export interface AggregateResult {
  rows: Array<{ group: Record<string, unknown>; metrics: Record<string, number | null> }>
  total_groups: number
  matched_rows: number
  group_by: string[]
  metrics: Array<{ alias: string; agg: string; field: string | null }>
}

export interface BulkReplacePayload {
  field: string
  find: string
  replace?: string
  match?: 'contains' | 'exact' | 'regex'
  filters?: Array<Record<string, unknown>>
  filter_logic?: 'AND' | 'OR'
  dry_run?: boolean
}

export interface BulkReplaceResult {
  field: string
  match: string
  dry_run: boolean
  matched: number
  updated: number
  skipped: number
  preview: Array<{ row_id: number; old: string; new: string }>
}
