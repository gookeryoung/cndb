import { describe, expect, it } from 'vitest'

import {
  TEAM_ROLE_COLOR, TEAM_ROLE_LABEL, WORKSPACE_ROLE_COLOR, WORKSPACE_ROLE_LABEL,
  teamRoleLabel, workspaceRoleLabel,
} from './roleLabels'

describe('roleLabels', () => {
  it('团队角色文案与配色覆盖三档', () => {
    expect(Object.keys(TEAM_ROLE_LABEL)).toEqual(['owner', 'admin', 'member'])
    expect(Object.keys(TEAM_ROLE_COLOR)).toEqual(['owner', 'admin', 'member'])
    expect(teamRoleLabel('owner')).toBe('团队所有者')
    expect(teamRoleLabel('admin')).toBe('团队管理员')
  })

  it('工作区角色文案与配色覆盖三档', () => {
    expect(Object.keys(WORKSPACE_ROLE_LABEL)).toEqual(['owner', 'editor', 'viewer'])
    expect(Object.keys(WORKSPACE_ROLE_COLOR)).toEqual(['owner', 'editor', 'viewer'])
    expect(workspaceRoleLabel('editor')).toBe('编辑者')
    expect(workspaceRoleLabel('viewer')).toBe('查看者')
  })

  it('空值 / 未知取值有稳定兜底（不透出 undefined）', () => {
    expect(teamRoleLabel(null)).toBe('团队成员')
    expect(teamRoleLabel(undefined)).toBe('团队成员')
    expect(teamRoleLabel('guest')).toBe('guest')
    expect(workspaceRoleLabel(null)).toBe('查看者')
    expect(workspaceRoleLabel('guest')).toBe('guest')
  })
})
