/** 角色标签（团队 / 工作区）—— 展示层共用的中文文案，判定口径仍由后端能力位决定. */

import type { TeamRole, WorkspaceRole } from '@/api'

export const TEAM_ROLE_LABEL: Record<TeamRole, string> = {
  owner: '团队所有者',
  admin: '团队管理员',
  member: '团队成员',
}

export const TEAM_ROLE_COLOR: Record<TeamRole, string> = {
  owner: 'gold',
  admin: 'blue',
  member: 'default',
}

export const WORKSPACE_ROLE_LABEL: Record<WorkspaceRole, string> = {
  owner: '所有者',
  editor: '编辑者',
  viewer: '查看者',
}

export const WORKSPACE_ROLE_COLOR: Record<WorkspaceRole, string> = {
  owner: 'gold',
  editor: 'cyan',
  viewer: 'default',
}

export function teamRoleLabel(role: TeamRole | string | null | undefined): string {
  return TEAM_ROLE_LABEL[(role ?? 'member') as TeamRole] ?? String(role ?? '')
}

export function workspaceRoleLabel(role: WorkspaceRole | string | null | undefined): string {
  return WORKSPACE_ROLE_LABEL[(role ?? 'viewer') as WorkspaceRole] ?? String(role ?? '')
}
