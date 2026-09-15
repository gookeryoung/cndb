/** 表 / 字段 / 记录 / 视图接口. */
import { request } from './client'

export interface Field {
  id: number
  name: string
  field_type: string
  config?: Record<string, unknown> | null
  required?: boolean
  hidden?: boolean
}

export interface TableDetail {
  id: number
  name: string
  description: string | null
  fields: Field[]
  record_count: number
  current_user_actions?: string[]
}

export const tableApi = {
  list: (wid: number | string) =>
    request<Array<{ id: number; name: string; record_count?: number; description?: string | null }>>({
      url: `/v1/workspaces/${wid}/tables`,
    }),

  get: (wid: number | string, tid: number | string) =>
    request<TableDetail>({ url: `/v1/workspaces/${wid}/tables/${tid}` }),
}

export const viewApi = {
  list: (wid: number | string, tid: number | string) =>
    request<Array<{
      id: number
      name: string
      default?: boolean
      view_type?: string
      filters?: unknown
      sortings?: unknown
      filter_type?: string
    }>>({ url: `/v1/workspaces/${wid}/tables/${tid}/views` }),
}

export interface RecordListParams {
  offset?: number
  limit?: number
  filters?: unknown
  sorts?: unknown
  filter_logic?: string
}

export const recordApi = {
  list: (wid: number | string, tid: number | string, params?: RecordListParams) => {
    const qp: Record<string, unknown> = { offset: params?.offset, limit: params?.limit }
    if (params?.filters) {
      qp.filters = typeof params.filters === 'string' ? params.filters : JSON.stringify(params.filters)
    }
    if (params?.sorts) {
      qp.sorts = typeof params.sorts === 'string' ? params.sorts : JSON.stringify(params.sorts)
    }
    if (params?.filter_logic) qp.filter_logic = params.filter_logic
    return request<{
      items: Array<Record<string, unknown>>
      total: number
      offset: number
      limit: number
    }>({
      url: `/v1/workspaces/${wid}/tables/${tid}/records`,
      params: qp,
    })
  },

  create: (wid: number | string, tid: number | string, values: Record<string, unknown>) =>
    request<Record<string, unknown>>({
      url: `/v1/workspaces/${wid}/tables/${tid}/records`,
      method: 'POST',
      data: { values },
    }),

  get: (wid: number | string, tid: number | string, rid: number | string) =>
    request<Record<string, unknown>>({
      url: `/v1/workspaces/${wid}/tables/${tid}/records/${rid}`,
    }),

  update: (wid: number | string, tid: number | string, rid: number | string, values: Record<string, unknown>) =>
    request<Record<string, unknown>>({
      url: `/v1/workspaces/${wid}/tables/${tid}/records/${rid}`,
      method: 'PATCH',
      data: { values },
    }),

  bulkDelete: (wid: number | string, tid: number | string, ids: Array<number | string>) =>
    request<{ deleted: number }>({
      url: `/v1/workspaces/${wid}/tables/${tid}/records/bulk-delete`,
      method: 'POST',
      data: { row_ids: ids },
    }),
}
