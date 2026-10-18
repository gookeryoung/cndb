/** 文档管理 API — /api/v1/workspaces/{wid}/documents */

import api from './client'

// ── 类型 ──

/** 段落锁信息（后端 ParagraphLockInfo.as_dict） */
export interface ParagraphLockItem {
  document_id: number
  key: string
  user_id: number
  username: string
  elapsed_seconds: number
}

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
  /** 当前用户的个人置顶（非文档属性，按用户返回） */
  pinned: boolean
  /**
   * 可见性提示（后端计算）：workspace = 已发布（成员均可见）；
   * shared = 未发布但已授权协作者；private = 仅自己与工作区所有者
   */
  visibility?: 'workspace' | 'shared' | 'private'
  /** 已授权协作者人数（visibility=shared 时有意义） */
  collaborator_count?: number
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

/** 出链项：正文 [[标题#锚点|别名]] 指向的文档或断链 */
export interface OutgoingLinkItem {
  title: string
  document_id: number | null
  exists: boolean
  broken: boolean
  /** 锚点（# 之后），可为空 */
  anchor?: string
  /** 别名（| 之后），可为空 */
  alias?: string
  /** 正文中的原始写法，如 `[[标题#锚点|别名]]` */
  raw?: string
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

/** 文档导出格式：Markdown / Word / PDF */
export type DocumentExportFormat = 'md' | 'docx' | 'pdf'

// ── Obsidian 文档库（vault）导入 / 导出 ──

/** 导入冲突策略：跳过同名 / 自动改名（追加「 (2)」）/ 覆盖生成新版本 */
export type VaultConflictPolicy = 'skip' | 'rename' | 'overwrite'

export interface VaultPreviewItem {
  /** 库内相对路径，如「笔记/设计稿.md」 */
  path: string
  title: string
  folder: string
  size: number
  tags: string[]
  status: 'new' | 'conflict'
  /** 来源类型：markdown / canvas / base（后两者由 .canvas / .base 转换） */
  kind: 'markdown' | 'canvas' | 'base'
  existing_document_id: number | null
}

export interface VaultFolderItem {
  path: string
  title: string
  status: 'new'
}

export interface VaultWarning {
  code: string
  message: string
  count?: number
  samples?: string[]
}

/** analyze 结果：只读预览，不写库 */
export interface VaultAnalyzeResult {
  filename: string
  /** zip 内的顶层目录（Obsidian 压缩包通常带一层库名目录） */
  root_dir: string
  total_notes: number
  /** 其中原生 markdown 笔记数 */
  total_markdown: number
  /** 其中由 .canvas / .base 转换的文档数 */
  total_converted: number
  total_folders: number
  total_attachments: number
  total_attachment_bytes: number
  total_bytes: number
  ignored_files: number
  conflicts: number
  tags: string[]
  warnings: VaultWarning[]
  skipped: { path: string; reason: string }[]
  preview_truncated: boolean
  folders: VaultFolderItem[]
  items: VaultPreviewItem[]
}

/** import 结果：落库后的统计 */
export interface VaultImportResult {
  created: number
  updated: number
  skipped: number
  total: number
  folders_created: number
  /** 由 .canvas / .base 转换导入的文档数 */
  converted: number
  attachments: number
  attachment_bytes: number
  tags_created: string[]
  documents: { id: number; title: string; path: string; kind?: string }[]
  skipped_notes: { path: string; title: string; reason: string }[]
  warnings: VaultWarning[]
}

export interface VaultImportOptions {
  /** 导入到哪个文件夹（空 = 根目录） */
  parentId?: number | null
  conflict?: VaultConflictPolicy
  importAttachments?: boolean
  importTags?: boolean
  status?: 'draft' | 'published' | 'archived'
}

/** 文档修改申请（双轨制写入的待审载体） */
export interface DocumentChangeRequestItem {
  id: number
  workspace_id: number
  document_id: number
  document_title?: string
  document_deleted?: boolean
  title: string
  description: string
  change_summary: string
  status: 'open' | 'merged' | 'closed'
  /** 基准过期：提交后文档又前进了版本，需刷新基准才能通过 */
  stale: boolean
  base_version_number: number
  current_version_number: number
  proposed_size: number
  submitted_by_id: number | null
  reviewed_by_id: number | null
  reviewed_at: string | null
  review_comment: string
  created_at: string | null
  updated_at: string | null
  /** 详情接口附带：基准版本 → 待审正文的 unified diff */
  diff?: { diff: string; added: number; removed: number; base_size: number; proposed_size: number; base_version_number: number }
  /** 详情接口附带：待审正文全文 */
  proposed_content?: string
}

/** 保存转入修改申请时的 202 载荷 */
export interface DocumentChangeRequestDispatch {
  change_request: DocumentChangeRequestItem
  message: string
}

/** 判定保存响应是否为「转修改申请」载荷（区别于直编返回的文档详情） */
export function isChangeRequestDispatch(data: unknown): data is DocumentChangeRequestDispatch {
  return !!data && typeof data === 'object' && 'change_request' in (data as Record<string, unknown>)
}

/** 文档问题类别（取值与数据表问题清单一致） */
export type DocumentIssueCategory = 'data_error' | 'suggestion' | 'question' | 'other'

/** 文档问题清单条目 */
export interface DocumentIssueItem {
  id: number
  workspace_id: number
  document_id: number
  document_title?: string | null
  title: string
  description: string
  category: DocumentIssueCategory
  status: 'open' | 'closed'
  created_by_id: number | null
  comment_count: number
  created_at: string | null
  updated_at: string | null
}

/** 文档问题详情：本体 + 评论 + 状态事件 */
export interface DocumentIssueDetail extends DocumentIssueItem {
  comments: Array<{ id: number; content: string; created_by_id: number | null; created_at: string | null }>
  events: Array<{ id: number; action: string; actor_id: number | null; created_at: string | null }>
}

// ── API ──

const base = (wid: number | string) => `/v1/workspaces/${wid}/documents`
const crBase = (wid: number | string) => `/v1/workspaces/${wid}/document-change-requests`
const diBase = (wid: number | string) => `/v1/workspaces/${wid}/document-issues`

/** 文档级授权角色：viewer 只读；editor 可直编未发布内容 */
export type DocumentPermissionRole = 'viewer' | 'editor'

export interface DocumentPermissionItem {
  document_id: number
  user_id: number
  role: DocumentPermissionRole
  username?: string | null
  nickname?: string | null
}

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
    data: {
      content: string
      change_summary?: string
      base_updated_at?: string | null
      /** 开始编辑时的正文快照：服务端据此做段落级三方合并（不同段落可并发，同段落冲突） */
      base_content?: string
      /** 无直编资格时作为申请的内容基准版本号 */
      base_version_number?: number | null
    },
  ) =>
    api
      .put<DocumentDetail | DocumentChangeRequestDispatch>(`${base(wid)}/${docId}/content`, data)
      .then(r => r.data),

  // 文档修改申请（双轨制写入的待审载体）
  changeRequests: (wid: number | string, params?: { document_id?: number; scope?: string }) =>
    api
      .get<{ items: DocumentChangeRequestItem[]; total: number }>(crBase(wid), { params })
      .then(r => r.data),

  changeRequest: (wid: number | string, requestId: number | string) =>
    api.get<DocumentChangeRequestItem>(`${crBase(wid)}/${requestId}`).then(r => r.data),

  mergeChangeRequest: (wid: number | string, requestId: number | string, reviewComment?: string) =>
    api
      .post<{ request: DocumentChangeRequestItem; version_number: number }>(`${crBase(wid)}/${requestId}/merge`, {
        review_comment: reviewComment ?? '',
      })
      .then(r => r.data),

  closeChangeRequest: (wid: number | string, requestId: number | string, reviewComment?: string) =>
    api
      .post<DocumentChangeRequestItem>(`${crBase(wid)}/${requestId}/close`, {
        review_comment: reviewComment ?? '',
      })
      .then(r => r.data),

  updateChangeRequestBase: (wid: number | string, requestId: number | string) =>
    api
      .post<DocumentChangeRequestItem>(`${crBase(wid)}/${requestId}/update-base`, {})
      .then(r => r.data),

  deleteChangeRequest: (wid: number | string, requestId: number | string) =>
    api.delete(`${crBase(wid)}/${requestId}`).then(r => r.data),

  // 文档问题清单（文档级 Issue，与数据表问题清单同构）
  issues: (wid: number | string, params?: { document_id?: number; status?: string }) =>
    api
      .get<{ items: DocumentIssueItem[]; total: number }>(diBase(wid), { params })
      .then(r => r.data),

  issue: (wid: number | string, issueId: number | string) =>
    api.get<DocumentIssueDetail>(`${diBase(wid)}/${issueId}`).then(r => r.data),

  createIssue: (
    wid: number | string,
    data: { document_id: number; title: string; description?: string; category?: DocumentIssueCategory },
  ) => api.post<DocumentIssueDetail>(diBase(wid), data).then(r => r.data),

  addIssueComment: (wid: number | string, issueId: number | string, content: string) =>
    api
      .post<{ id: number; content: string; created_by_id: number | null; created_at: string | null }>(
        `${diBase(wid)}/${issueId}/comments`,
        { content },
      )
      .then(r => r.data),

  closeIssue: (wid: number | string, issueId: number | string) =>
    api.post<DocumentIssueDetail>(`${diBase(wid)}/${issueId}/close`).then(r => r.data),

  reopenIssue: (wid: number | string, issueId: number | string) =>
    api.post<DocumentIssueDetail>(`${diBase(wid)}/${issueId}/reopen`).then(r => r.data),

  // 导出：Markdown / Word / PDF 文件字节流（文件名由调用方拼装）
  exportFile: (wid: number | string, docId: number | string, format: DocumentExportFormat) =>
    api
      .get<Blob>(`${base(wid)}/${docId}/export`, { params: { format }, responseType: 'blob' })
      .then(r => r.data),

  // 个人置顶（仅影响当前用户的树/列表顺序）
  pinDocument: (wid: number | string, docId: number | string) =>
    api.post<{ document_id: number; pinned: boolean }>(`${base(wid)}/${docId}/pin`).then(r => r.data),

  unpinDocument: (wid: number | string, docId: number | string) =>
    api.delete(`${base(wid)}/${docId}/pin`).then(r => r.data),

  updateMeta: (wid: number | string, docId: number | string, data: Record<string, unknown>) =>
    api.patch<DocumentItem>(`${base(wid)}/${docId}`, data).then(r => r.data),

  // 文档协作者（文档级权限）：把未发布草稿开放给指定同事
  listPermissions: (wid: number | string, docId: number | string) =>
    api
      .get<{ items: DocumentPermissionItem[] }>(`${base(wid)}/${docId}/permissions`)
      .then(r => r.data.items),

  grantPermission: (
    wid: number | string,
    docId: number | string,
    data: { user_id: number; role: DocumentPermissionRole },
  ) =>
    api.post<DocumentPermissionItem>(`${base(wid)}/${docId}/permissions`, data).then(r => r.data),

  revokePermission: (wid: number | string, docId: number | string, userId: number) =>
    api.delete(`${base(wid)}/${docId}/permissions/${userId}`),

  /** 批量移动 / 删除：逐项校验，失败项在 skipped 中返回（不中断整批） */
  batch: (
    wid: number | string,
    payload: { action: 'move' | 'delete'; ids: number[]; parent_id?: number | null },
  ) =>
    api.post<{ action: string; updated: number; skipped: { id: number; reason: string }[] }>(
      `${base(wid)}/batch`,
      payload,
    ).then(r => r.data),

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
  /** 段落锁列表（谁在编辑第几段） */
  listParagraphLocks: (wid: number | string, docId: number | string) =>
    api.get<{ locks: ParagraphLockItem[] }>(`${base(wid)}/${docId}/paragraph-locks`).then(r => r.data.locks),
  /** 获取段落锁（同段互斥；被他人持有时 409，前端提示具体持锁人） */
  acquireParagraphLocks: (wid: number | string, docId: number | string, keys: string[]) =>
    api.post<{ locks: ParagraphLockItem[]; document_locks: ParagraphLockItem[] }>(
      `${base(wid)}/${docId}/paragraph-locks`, { keys },
    ).then(r => r.data),
  /** 释放段落锁（不传 keys 则释放自己在本文档的全部段落锁） */
  releaseParagraphLocks: (wid: number | string, docId: number | string, keys?: string[]) =>
    api.delete<{ released: number; document_locks: ParagraphLockItem[] }>(
      `${base(wid)}/${docId}/paragraph-locks`,
      keys ? { data: { keys } } : undefined,
    ).then(r => r.data),
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

  // ── Obsidian 文档库导入 / 导出 ──
  // 注意：实例默认头是 application/json，multipart 必须显式声明 multipart/form-data，
  // 请求拦截器会删掉它再由浏览器补 boundary（否则后端解析不了表单 → 422）。

  /** 上传 zip 解析预览（只读，不落库）：条目数 / 冲突 / 标签 / 告警 */
  vaultAnalyze: (wid: number | string, file: File, parentId?: number | null) => {
    const form = new FormData()
    form.append('file', file)
    if (parentId != null) form.append('parent_id', String(parentId))
    return api
      .post<VaultAnalyzeResult>(`${base(wid)}/import/analyze`, form, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      .then(r => r.data)
  },

  /** 按确认后的策略把库导入为文档树 */
  vaultImport: (wid: number | string, file: File, options: VaultImportOptions = {}) => {
    const form = new FormData()
    form.append('file', file)
    if (options.parentId != null) form.append('parent_id', String(options.parentId))
    form.append('conflict', options.conflict ?? 'rename')
    form.append('import_attachments', String(options.importAttachments ?? true))
    form.append('import_tags', String(options.importTags ?? true))
    form.append('status', options.status ?? 'draft')
    return api
      .post<VaultImportResult>(`${base(wid)}/import`, form, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      .then(r => r.data)
  },

  /** 导出当前工作区文档树为 Obsidian 库（zip blob） */
  vaultExport: (wid: number | string) =>
    api.get<Blob>(`${base(wid)}/export/vault`, { responseType: 'blob' }).then(r => r.data),
}
