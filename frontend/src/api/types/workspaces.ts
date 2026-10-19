/** 工作区、成员与工作区导出载荷. */

import type { ID, WorkspaceVisibility } from './common'

export interface Workspace {
  id: ID; name: string; description?: string; default_role?: string
  pinned?: boolean; created_at?: string; updated_at?: string
  visibility?: WorkspaceVisibility; tags?: string[]; allow_edit?: boolean
  /** 存储配额（字节），默认 100MB；由系统管理员在管理台「空间分配」调整 */
  storage_quota_bytes?: number
  current_user_role?: WorkspaceRole | null
}
export interface WorkspaceDetail extends Workspace {
  member_count?: number; table_count?: number
  view_count?: number; total_rows?: number
  /** 已用存储空间（字节）：附件 + 文档（外存文件/内联正文）+ 数据表记录 */
  storage_bytes?: number
  owner?: { id: ID; username: string; nickname?: string } | null
  current_user_role?: WorkspaceRole | null
}
export interface WorkspaceCreate {
  name: string; description?: string; default_role?: string
  visibility?: WorkspaceVisibility; tags?: string[]; allow_edit?: boolean
}
export interface WorkspaceUpdate {
  name?: string; description?: string; default_role?: string
  visibility?: WorkspaceVisibility; tags?: string[]; allow_edit?: boolean
}
/** 工作区角色 —— 三级（owner/editor/viewer），admin 已在 P1 迁移为 editor */
export type WorkspaceRole = 'owner' | 'editor' | 'viewer'

/** 成员中的用户简要信息（对齐后端 MemberUserBrief） */
export interface MemberUserBrief {
  id: ID; username: string; nickname?: string; email?: string | null
}

/** 工作区成员（对齐后端 WorkspaceMemberResponse） */
export interface WorkspaceMember {
  id: ID; workspace_id: ID; user_id: ID
  role: WorkspaceRole; pinned?: boolean; created_at?: string
  user: MemberUserBrief
}

/** 工作区级整体导出数据结构 */
export interface WorkspaceExportData {
  version: string
  exported_at: string
  workspace: {
    name: string; description: string; visibility: WorkspaceVisibility; tags: string[]; allow_edit: boolean
  }
  tables: Array<{
    name: string; description: string
    fields: Array<Record<string, unknown>>
    views: Array<Record<string, unknown>>
    rows: Array<Record<string, unknown>>
    /** 表级权限配置（缺失/为 null 表示该表未配置权限） */
    permission?: Record<string, unknown> | null
  }>
  /** 工作区级文档标签 */
  document_tags?: Array<{ id?: number; name: string; color?: string; description?: string }>
  /** 文档树（文件夹层级 + 仅最新正文） */
  documents?: Array<{
    id?: number; parent_id?: number | null; title: string
    content_type?: string; status?: string; is_folder?: boolean
    sort_order?: number; content: string; tag_ids?: number[]
  }>
}
