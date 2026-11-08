/** 工作区、成员与工作区导出载荷. */

import type { ID, WorkspaceModule, WorkspaceVisibility } from './common'

export interface Workspace {
  id: ID; name: string; description?: string; default_role?: string
  pinned?: boolean; created_at?: string; updated_at?: string
  visibility?: WorkspaceVisibility; tags?: string[]; allow_edit?: boolean
  /** 启用的功能模块集合（ADR 0080；缺失时前端按全三模块兜底） */
  modules?: WorkspaceModule[]
  /** 存储配额（字节），默认 100MB；由系统管理员在管理台「空间分配」调整 */
  storage_quota_bytes?: number
  /** 工作区模板引用（需求 0094）；null/缺失 = 自由工作区 */
  template_id?: number | null
  template_version?: number | null
  template_stage?: string | null
  /** 项目上下文模式（ADR 0122）：project 时显示项目清单 / 切换器 */
  project_mode?: 'workspace' | 'project'
  current_user_role?: WorkspaceRole | null
}
export interface WorkspaceDetail extends Workspace {
  member_count?: number; table_count?: number
  view_count?: number; total_rows?: number
  /** 文档数（不含文件夹与回收站内容） */
  document_count?: number
  /** 设计文件数（不含已软删） */
  design_count?: number
  /** 已用存储空间（字节）：附件 + 文档（外存文件/内联正文）+ 数据表记录 */
  storage_bytes?: number
  owner?: { id: ID; username: string; nickname?: string } | null
  current_user_role?: WorkspaceRole | null
}
export interface WorkspaceCreate {
  name: string; description?: string; default_role?: string
  visibility?: WorkspaceVisibility; tags?: string[]; allow_edit?: boolean
  /** 功能模块集合，默认全三模块（ADR 0080 D8）；选模板时以后端模板 modules 为准 */
  modules?: WorkspaceModule[]
  /** 选用工作区模板（需求 0094），创建时按模板建立表单 / 文档占位与首阶段 */
  template_id?: number | null
}
export interface WorkspaceUpdate {
  name?: string; description?: string; default_role?: string
  visibility?: WorkspaceVisibility; tags?: string[]; allow_edit?: boolean
  modules?: WorkspaceModule[]
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

/** 工作区贡献统计行（需求 0126，按编辑者） */
export interface WorkspaceContributionItem {
  user_id: ID
  username?: string | null
  nickname?: string | null
  /** 当前角色；null = 已移出工作区的曾为编辑者 */
  role?: WorkspaceRole | null
  is_member: boolean
  /** 当前不是 owner/editor（含已移出）但存在直接写活动 */
  is_former_editor: boolean
  rows_created: number
  rows_updated: number
  documents_created: number
  documents_edited: number
  designs_created: number
  designs_edited: number
  total: number
  last_active_at?: string | null
}

/** 工作区贡献统计按天时序项（近 12 个月，仅非零日） */
export interface WorkspaceContributionDailyItem {
  /** YYYY-MM-DD（UTC 日） */
  date: string
  user_id: ID
  count: number
}

/** 工作区贡献统计响应（累计全部时间，另附近 12 个月按天时序） */
export interface WorkspaceContributions {
  generated_at: string
  timeline_start: string
  timeline_end: string
  daily: WorkspaceContributionDailyItem[]
  items: WorkspaceContributionItem[]
}

/** 归档导入预检：可覆盖恢复的既有工作区（当前用户为 owner） */
export interface WorkspaceArchiveTarget {
  id: ID; name: string; role: WorkspaceRole
}

/** 归档导入预检结果（不落库） */
export interface WorkspaceArchiveInspect {
  workspace_name: string
  backup_version: string
  created_at?: string | null
  include_secrets: boolean
  stats: Record<string, number>
  /** 同名且当前用户为 owner 的既有工作区；为空表示只能导入为新工作区 */
  existing_workspace?: WorkspaceArchiveTarget | null
}

/** 工作区级整体导出数据结构 */
export interface WorkspaceExportData {
  version: string
  exported_at: string
  workspace: {
    name: string; description: string; visibility: WorkspaceVisibility; tags: string[]; allow_edit: boolean
    /** 功能模块集合（v12 起；旧备份缺省，导入时按后端映射兜底） */
    modules?: WorkspaceModule[]
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
