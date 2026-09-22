/** 行记录 API — /api/v1/workspaces/{wid}/tables/{tid}/records/*（含批量操作） */

import api from './client'
import type { RowCreate, RowUpdate, RowResponse, RowListResponse, RecordListParams } from './types'

export const recordApi = {
  list: (wid: number | string, tid: number | string, params?: RecordListParams) => {
    // GET 端点：filters/sorts 用 JSON 字符串
    const qp: Record<string, unknown> = { offset: params?.offset, limit: params?.limit }
    if (params?.filters) qp.filters = typeof params.filters === 'string' ? params.filters : JSON.stringify(params.filters)
    if (params?.sorts) qp.sorts = typeof params.sorts === 'string' ? params.sorts : JSON.stringify(params.sorts)
    if (params?.filter_logic) qp.filter_logic = params.filter_logic
    return api.get<RowListResponse>(`/v1/workspaces/${wid}/tables/${tid}/records`, { params: qp }).then(r => r.data)
  },
  create: (wid: number | string, tid: number | string, data: RowCreate) =>
    api.post<RowResponse>(`/v1/workspaces/${wid}/tables/${tid}/records`, data).then(r => r.data),
  get: (wid: number | string, tid: number | string, rid: number | string) =>
    api.get<RowResponse>(`/v1/workspaces/${wid}/tables/${tid}/records/${rid}`).then(r => r.data),
  update: (wid: number | string, tid: number | string, rid: number | string, data: RowUpdate) =>
    api.patch<RowResponse>(`/v1/workspaces/${wid}/tables/${tid}/records/${rid}`, data).then(r => r.data),
  remove: (wid: number | string, tid: number | string, rid: number | string, soft = true) =>
    api.delete(`/v1/workspaces/${wid}/tables/${tid}/records/${rid}`, { params: { soft } }).then(r => r.data),
  restore: (wid: number | string, tid: number | string, rid: number | string) =>
    api.post<RowResponse>(`/v1/workspaces/${wid}/tables/${tid}/records/${rid}/restore`).then(r => r.data),
  // 批量
  bulkCreate: (wid: number | string, tid: number | string, rows: Array<Record<string, unknown>>) =>
    api.post<{ created: number; ids: number[] }>(`/v1/workspaces/${wid}/tables/${tid}/records/bulk-create`, { rows }).then(r => r.data),
  bulkDelete: (wid: number | string, tid: number | string, ids: Array<number | string>) =>
    api.post<{ deleted: number }>(`/v1/workspaces/${wid}/tables/${tid}/records/bulk-delete`, { row_ids: ids }).then(r => r.data),
  bulkUpdate: (wid: number | string, tid: number | string, ids: Array<number | string>, values: Record<string, unknown>) =>
    api.post<{ updated: number }>(`/v1/workspaces/${wid}/tables/${tid}/records/bulk-update`, { row_ids: ids, values }).then(r => r.data),
}
