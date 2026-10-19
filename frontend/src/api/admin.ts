/** 系统管理 API — /api/v1/admin/*（系统信息/备份/恢复） */

import api from './client'

export interface AdminSystemInfo {
  app_name: string
  app_version: string
  database_url: string
  upload_dir: string
  data_dir: string
  auth_enabled: boolean
  timezone: string
}

export interface BackupManifest {
  version: string
  app_version: string
  created_at: string
  database: {
    path: string
    db_type: string
    backup_mode: string
    tables: string[]
    row_counts: Record<string, number>
    /** 备份时的 alembic schema 版本（旧版备份可能缺失） */
    schema_version?: string
    /** 内嵌兜底导出的恢复模式（native 备份内嵌 dump.json 时为 "sqlalchemy"） */
    fallback_mode?: string
  }
  uploads: {
    included: boolean
    file_count: number
    total_size: number
  }
  /** inspect 附加判定：备份 schema 版本在本地迁移链上（旧版备份无版本记录时为 true） */
  schema_known?: boolean
  /** inspect 附加判定：备份 schema 新于当前程序，native 恢复将失败 */
  backup_ahead?: boolean
  /** inspect 附加：表清单按系统表/用户表分类（用户表为 table_/trash_/link_ 前缀） */
  table_groups?: {
    system: string[]
    user: string[]
  }
}

/** 工作区空间分配条目（对齐后端 /admin/workspaces/storage） */
export interface WorkspaceStorageItem {
  workspace_id: number
  name: string
  owner_username: string | null
  used_bytes: number
  quota_bytes: number
  updated_at: string | null
}

export interface WorkspaceStorageOverview {
  /** 默认配额（字节），新建工作区未单独分配时使用 */
  default_quota_bytes: number
  items: WorkspaceStorageItem[]
}

export const adminApi = {
  /** 获取系统级信息（版本/数据库路径/数据目录等） */
  info: () => api.get<AdminSystemInfo>('/v1/admin/info').then(r => r.data),

  /** 触发系统级备份，返回可下载的 tar.gz 文件流 */
  backup: (options?: { include_uploads?: boolean; mode?: string }) => {
    return api.post('/v1/admin/backup', {
      format: 'archive',
      include_uploads: options?.include_uploads ?? true,
      mode: options?.mode ?? 'auto',
    }, { responseType: 'blob' }).then(r => r.data as Blob)
  },

  /** dry-run 检查备份文件（上传 tar.gz），返回 manifest 元信息 */
  restoreInspect: (file: File) => {
    const fd = new FormData()
    fd.append('file', file)
    return api.post<BackupManifest>('/v1/admin/restore/inspect', fd, {
      headers: { 'Content-Type': 'multipart/form-data' },
    }).then(r => r.data)
  },

  /** 执行系统级恢复（破坏性操作）。mode 覆盖恢复模式：备份 schema 新于当前程序时可传 "sqlalchemy" 降级恢复 */
  restore: (file: File, force = true, mode?: string) => {
    const fd = new FormData()
    fd.append('file', file)
    fd.append('force', String(force))
    if (mode) fd.append('mode', mode)
    return api.post<{ status: string; message: string; loss_report: { summary: string; skipped_tables: string[]; dropped_columns: Record<string, string[]> } | null }>(
      '/v1/admin/restore',
      fd,
      { headers: { 'Content-Type': 'multipart/form-data' } },
    ).then(r => r.data)
  },

  // ── 工作区空间分配（/api/v1/admin/workspaces/storage，仅系统管理员） ──
  /** 列出全部工作区的已用空间与配额 */
  workspaceStorage: () =>
    api.get<WorkspaceStorageOverview>('/v1/admin/workspaces/storage').then(r => r.data),
  /** 调整某个工作区的存储配额（字节） */
  updateWorkspaceQuota: (workspaceId: number, quotaBytes: number) =>
    api.patch<{ workspace_id: number; used_bytes: number; quota_bytes: number }>(
      `/v1/admin/workspaces/${workspaceId}/storage-quota`,
      { quota_bytes: quotaBytes },
    ).then(r => r.data),

  // ── 统一事件流（/api/v1/admin/events，超管或审计管理员可读） ──
  /** 统一事件流分页查询 */
  listEvents: (params: CoreEventQuery = {}) =>
    api.get<CoreEventPage>('/v1/admin/events', { params }).then(r => r.data),
  /** 出现过的动作与计数（供筛选下拉） */
  listEventActions: () =>
    api.get<{ items: CoreEventActionStat[] }>('/v1/admin/events/actions').then(r => r.data.items),
}

// ── 统一事件流（/api/v1/admin/events，超管或审计管理员可读） ──

export interface CoreEventItem {
  id: number
  created_at: string
  action: string
  workspace_id: number | null
  actor_id: number | null
  actor_name: string | null
  target_type: string
  target_id: string | null
  summary: string
  detail: Record<string, unknown>
  request_id: string | null
}

export interface CoreEventPage {
  items: CoreEventItem[]
  total: number
  page: number
  page_size: number
}

export interface CoreEventActionStat {
  action: string
  count: number
}

export interface CoreEventQuery {
  action?: string
  actor_id?: number
  target_type?: string
  target_id?: string
  workspace_id?: number
  request_id?: string
  keyword?: string
  since?: string
  until?: string
  page?: number
  page_size?: number
}
