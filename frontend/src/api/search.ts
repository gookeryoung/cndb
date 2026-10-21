/** 工作区统一检索 API — /api/v1/workspaces/{wid}/search
 *
 * 顶栏搜索框的唯一数据源：一次请求返回「数据表」与「文档」两路结果。
 * `scope=all` 覆盖整个工作区；只有 `scope=tables` 才把 table_id / view_id
 * 用于收敛当前表与激活视图（ADR 0015）。
 */

import api from './client'

export type SearchScope = 'all' | 'documents' | 'tables'

export interface SearchDocumentHit {
  id: number
  title: string
  title_hit: string
  summary_hit: string
  status: string
  updated_at: string
}

export interface SearchTableHit {
  id: number
  name: string
  description: string
}

export interface SearchRowHit {
  table_id: number
  table_name: string
  row_id: number | null
  title: string
  snippet: string
}

/** 数据表侧的检索范围说明：有 name 表示已按该视图筛选（仅数据表范围回显） */
export interface SearchViewScope {
  id: number | null
  name: string
  table_id: number
  table_name: string
}

export interface WorkspaceSearchResult {
  query: string
  documents: SearchDocumentHit[]
  tables: SearchTableHit[]
  rows: SearchRowHit[]
  view: SearchViewScope | null
}

export interface WorkspaceSearchParams {
  q: string
  scope?: SearchScope
  table_id?: number
  view_id?: number
  limit?: number
}

export const searchApi = {
  workspace: (wid: number | string, params: WorkspaceSearchParams) =>
    api
      .get<WorkspaceSearchResult>(`/v1/workspaces/${wid}/search`, { params })
      .then(r => r.data),
}
