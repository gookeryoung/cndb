/** 团队（ADR 0153）：工作区的组织层，单层扁平、不嵌套（D2 / I7） */

import type { ID, WorkspaceModule, WorkspaceVisibility } from './common'
import type { MemberUserBrief } from './workspaces'

/** 团队成员角色（只决定管理面，不派生数据面） */
export type TeamRole = 'owner' | 'admin' | 'member'

/** 团队策略：缺键由后端按默认补齐（default_workspace_role = none 保持存量行为） */
export interface TeamPolicy {
  default_workspace_role: 'none' | 'viewer' | 'editor'
  allowed_modules: WorkspaceModule[] | null
  default_storage_quota_bytes: number | null
  allow_member_invite: boolean
}

/** 团队简要信息（工作区列表 / 详情的 `team` 字段） */
export interface TeamBrief {
  id: ID
  name: string
  slug: string
}

/** 团队（对齐后端 TeamResponse） */
export interface Team extends TeamBrief {
  description: string
  policy: TeamPolicy
  created_by_id: ID | null
  created_at: string
  updated_at: string
  /** 当前用户在该团队的角色；null = 非成员（后端 404 时不会有该字段） */
  current_user_role: TeamRole | null
  workspace_count: number
  member_count: number
}

export interface TeamCreate {
  name: string
  slug?: string
  description?: string
}

export interface TeamUpdate {
  name?: string
  description?: string
  policy?: Partial<TeamPolicy>
}

export interface TeamMember {
  id: ID
  team_id: ID
  user_id: ID
  role: TeamRole
  user: MemberUserBrief
}

/** 团队下的工作区（平铺列表项，无树：C1） */
export interface TeamWorkspace {
  id: ID
  name: string
  description?: string
  visibility: WorkspaceVisibility
  modules: WorkspaceModule[]
  member_count: number
  /** 当前用户是否已是该工作区成员（自助加入按钮显隐，ADR 0153 P2） */
  is_member?: boolean
  updated_at: string
}
