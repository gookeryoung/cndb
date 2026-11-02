/** 工作区统一检索 API — /api/v1/workspaces/{wid}/search
 *
 * 顶栏搜索框的唯一数据源：一次请求返回「数据表」与「文档」两路结果。
 * `scope=all` 覆盖整个工作区；只有 `scope=tables` 才把 table_id / view_id
 * 用于收敛当前表与激活视图（ADR 0012 / 原 0015）。
 */

import api from './client'

export type SearchScope = 'all' | 'documents' | 'tables'

export interface SearchDocumentHit {
  id: number
  title: string
  title_hit: string
  summary_hit: string
  status: string
  /** 文档格式（markdown / pdf / image / …），用于结果区按格式显示图标（ADR 0025） */
  content_type: string
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

/** 跨工作区命中项：在工作区命中之上附带归属工作区（主页搜索点击跳转用，需求 0081） */
export interface WorkspaceRef {
  workspace_id: number
  workspace_name: string
}

export type GlobalDocumentHit = SearchDocumentHit & WorkspaceRef
export type GlobalTableHit = SearchTableHit & WorkspaceRef
export type GlobalRowHit = SearchRowHit & WorkspaceRef

/** 跨工作区统一检索结果（GET /api/v1/search）：无 view 收敛概念 */
export interface GlobalSearchResult {
  query: string
  documents: GlobalDocumentHit[]
  tables: GlobalTableHit[]
  rows: GlobalRowHit[]
}

export interface GlobalSearchParams {
  q: string
  limit?: number
}

export const searchApi = {
  workspace: (wid: number | string, params: WorkspaceSearchParams) =>
    api
      .get<WorkspaceSearchResult>(`/v1/workspaces/${wid}/search`, { params })
      .then(r => r.data),
  /** 跨工作区检索（主页 / 无工作区上下文的顶栏搜索，需求 0081 C3） */
  global: (params: GlobalSearchParams) =>
    api
      .get<GlobalSearchResult>('/v1/search', { params })
      .then(r => r.data),
}
