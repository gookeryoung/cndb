/** 文档管理 API — /api/v1/workspaces/{wid}/documents */

import api from './client'

// ── 类型 ──

export interface TocItem {
  level: number
  text: string
  line: number
}

export interface DocumentItem {
  id: number
  workspace_id: number
  parent_id: number | null
  title: string
  slug: string | null
  content_type: string
  author: string
  summary: string
  toc_json: TocItem[]
  status: 'draft' | 'published' | 'archived'
  is_folder: boolean
  sort_order: number
  content_size: number
  created_at: string
  updated_at: string
  created_by_id: number | null
  updated_by_id: number | null
  tag_ids: number[]
  version_count: number
}

export interface DocumentDetail extends DocumentItem {
  content: string
  version_number?: number
  edit_lock?: { user_id: number; username: string; elapsed_seconds: number } | null
}

export interface VersionItem {
  id: number
  document_id: number
  version_number: number
  content_size: number
  content_hash: string | null
  change_summary: string
  change_type: 'manual' | 'auto_import' | 'rollback'
  created_at: string
  created_by_id: number | null
}

export interface TagItem {
  id: number
  workspace_id: number
  name: string
  color: string
  description: string
  doc_count: number
}

export interface SearchHitItem {
  id: number
  title: string
  title_hit: string
  summary_hit: string
  workspace_id: number
  status: string
  updated_at: string
  rank: number
}

export interface ShareItem {
  id: number
  document_id: number
  token: string
  permission: 'viewer' | 'editor'
  has_password: boolean
  expires_at: string | null
  view_count: number
  is_active: boolean
  created_at: string
}

/** 每日笔记响应：文档元数据 + 是否本次新建（幂等标记） */
export interface DailyNoteResponse extends DocumentItem {
  created: boolean
}

/** 反向链接项：引用了当前文档的其他文档 */
export interface BacklinkItem {
  id: number
  title: string
  summary: string
  status: string
  updated_at: string
}

/** 回收站条目：文档元数据 + 删除信息 */
export interface TrashItem extends DocumentItem {
  deleted_at: string | null
  deleted_by_id: number | null
}

/** 出链项：正文 [[标题]] 指向的文档或断链 */
export interface OutgoingLinkItem {
  title: string
  document_id: number | null
  exists: boolean
  broken: boolean
}

/** 断链修复结果 */
export interface LinkRepairResult {
  document_id: number
  version_number: number
  repaired: { title: string; new_title: string; document_id: number; count: number }[]
  replaced: number
  document: DocumentItem
}

/** 彻底删除结果 */
export interface PurgeResult {
  id: number
  purged: boolean
  purged_count: number
  files_removed: number
  detached: number
}

// ── API ──

const base = (wid: number | string) => `/v1/workspaces/${wid}/documents`

export const documentsApi = {
  list: (wid: number | string, params?: Record<string, unknown>) =>
    api.get<{ items: DocumentItem[]; total: number }>(base(wid), { params }).then(r => r.data),

  tree: (wid: number | string) =>
    api.get<{ items: DocumentItem[] }>(`${base(wid)}/tree`).then(r => r.data.items),

  create: (wid: number | string, data: Partial<DocumentItem> & { content?: string }) =>
    api.post<DocumentItem>(base(wid), data).then(r => r.data),

  get: (wid: number | string, docId: number | string) =>
    api.get<DocumentItem>(`${base(wid)}/${docId}`).then(r => r.data),

  getContent: (wid: number | string, docId: number | string) =>
    api.get<DocumentDetail>(`${base(wid)}/${docId}/content`).then(r => r.data),

  updateContent: (
    wid: number | string,
    docId: number | string,
    data: { content: string; change_summary?: string; base_updated_at?: string | null },
  ) =>
    api.put<DocumentDetail>(`${base(wid)}/${docId}/content`, data).then(r => r.data),

  updateMeta: (wid: number | string, docId: number | string, data: Record<string, unknown>) =>
    api.patch<DocumentItem>(`${base(wid)}/${docId}`, data).then(r => r.data),

  remove: (wid: number | string, docId: number | string) =>
    api.delete<{ id: number; deleted: boolean }>(`${base(wid)}/${docId}`).then(r => r.data),

  // 版本
  versions: (wid: number | string, docId: number | string) =>
    api.get<{ items: VersionItem[]; total: number }>(`${base(wid)}/${docId}/versions`).then(r => r.data),

  getVersion: (wid: number | string, docId: number | string, num: number) =>
    api.get<VersionItem & { content: string }>(`${base(wid)}/${docId}/versions/${num}`).then(r => r.data),

  diff: (wid: number | string, docId: number | string, baseNum: number, headNum: number) =>
    api
      .get<{ diff: string; added: number; removed: number }>(`${base(wid)}/${docId}/diff`, {
        params: { base: baseNum, head: headNum },
      })
      .then(r => r.data),

  rollback: (wid: number | string, docId: number | string, targetVersion: number) =>
    api.post<DocumentItem>(`${base(wid)}/${docId}/rollback`, { target_version: targetVersion }).then(r => r.data),

  // 编辑锁
  acquireLock: (wid: number | string, docId: number | string) =>
    api.post(`${base(wid)}/${docId}/lock`).then(r => r.data),
  releaseLock: (wid: number | string, docId: number | string) =>
    api.delete(`${base(wid)}/${docId}/lock`).then(r => r.data),

  // 标签
  tags: (wid: number | string) =>
    api.get<{ items: TagItem[] }>(`${base(wid)}/tags`).then(r => r.data.items),
  createTag: (wid: number | string, data: { name: string; color?: string; description?: string }) =>
    api
      .post<TagItem>(`/v1/workspaces/${wid}/document-tags`, data)
      .then(r => r.data),
  deleteTag: (wid: number | string, tagId: number) =>
    api.delete(`/v1/workspaces/${wid}/document-tags/${tagId}`).then(r => r.data),
  setDocTags: (wid: number | string, docId: number | string, tagIds: number[]) =>
    api.post<DocumentItem>(`${base(wid)}/${docId}/tags`, { tag_ids: tagIds }).then(r => r.data),

  // 搜索
  search: (wid: number | string, q: string, params?: Record<string, unknown>) =>
    api
      .get<{ items: SearchHitItem[]; total: number; query: string }>(`${base(wid)}/search`, {
        params: { q, ...params },
      })
      .then(r => r.data),

  // 每日笔记（幂等：当日已存在直接返回）
  dailyNote: (wid: number | string, date?: string) =>
    api
      .post<DailyNoteResponse>(`${base(wid)}/daily-note`, date ? { date } : {})
      .then(r => r.data),

  // 反向链接：谁在正文中引用了 [[本文档标题]]
  backlinks: (wid: number | string, docId: number | string) =>
    api
      .get<{ items: BacklinkItem[]; total: number }>(`${base(wid)}/${docId}/backlinks`)
      .then(r => r.data.items),

  // 出链解析：正文 [[标题]] 的命中 / 断链清单
  links: (wid: number | string, docId: number | string) =>
    api
      .get<{ items: OutgoingLinkItem[]; total: number; broken: number }>(`${base(wid)}/${docId}/links`)
      .then(r => r.data),

  // 断链修复：把正文 [[旧标题]] 改指为现存文档（生成新版本）
  repairLinks: (
    wid: number | string,
    docId: number | string,
    repairs: { title: string; target_document_id: number }[],
  ) => api.post<LinkRepairResult>(`${base(wid)}/${docId}/links/repair`, { repairs }).then(r => r.data),

  // 回收站：软删除列表 / 恢复 / 彻底删除
  trash: (wid: number | string, params?: Record<string, unknown>) =>
    api.get<{ items: TrashItem[]; total: number }>(`${base(wid)}/trash`, { params }).then(r => r.data),

  restore: (wid: number | string, docId: number | string) =>
    api
      .post<DocumentItem & { restored_count: number; reparented_to_root: boolean }>(
        `${base(wid)}/${docId}/restore`,
      )
      .then(r => r.data),

  purge: (wid: number | string, docId: number | string) =>
    api.delete<PurgeResult>(`${base(wid)}/${docId}/purge`).then(r => r.data),

  // 分享
  shares: (wid: number | string, docId: number | string) =>
    api.get<{ items: ShareItem[] }>(`${base(wid)}/${docId}/share`).then(r => r.data.items),
  createShare: (
    wid: number | string,
    docId: number | string,
    data: { permission?: 'viewer' | 'editor'; password?: string | null; expires_at?: string | null },
  ) => api.post<ShareItem>(`${base(wid)}/${docId}/share`, data).then(r => r.data),
  revokeShare: (wid: number | string, docId: number | string, shareId: number) =>
    api.delete(`${base(wid)}/${docId}/share/${shareId}`).then(r => r.data),
}
