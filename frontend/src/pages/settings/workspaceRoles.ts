/** 工作区角色 / 可见性的展示文案与「可分配角色」计算.
 *
 * 设置页主体、成员三区、添加成员弹窗共用，避免文案在多处重复。
 */

import type { WorkspaceRole, WorkspaceVisibility } from '@/api'

export const ROLE_LABEL: Record<WorkspaceRole, string> = {
  owner: '所有者',
  editor: '编辑者',
  viewer: '查看者',
}

export const VISIBILITY_LABEL: Record<WorkspaceVisibility, string> = {
  public: '公开（任何人可读）',
  member: '成员可见（仅工作区成员可访问）',
  private: '私有（仅所有者可见）',
}

/** 角色一句话说明（成员角色 Select 下拉展示，与帮助文档「权限与角色」主题对齐） */
export const ROLE_HINTS: Record<WorkspaceRole, string> = {
  owner: '全部权限，可转让与删除工作区',
  editor: '可查看并编辑数据，不可管理成员与设置',
  viewer: '仅可查看工作区内容与数据',
}

/** 当前用户可分配给其他人的角色选项（仅 owner 可管理，可分配 editor/viewer） */
export function getAssignableRoles(
  currentRole: WorkspaceRole | null,
): Array<{ value: WorkspaceRole; label: string }> {
  if (currentRole !== 'owner') return []
  return (['editor', 'viewer'] as WorkspaceRole[]).map(r => ({ value: r, label: ROLE_LABEL[r] }))
}
