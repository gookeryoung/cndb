/**
 * MemberZones 测试 —— 工作区成员分区的移动端适配：
 * 窄屏下用户/角色/操作三列保留列宽并横向滚动，不再把用户名与邮箱挤成逐字换行。
 */

import { describe, expect, it, vi } from 'vitest'
import { screen } from '@testing-library/react'

import type { WorkspaceMember } from '@/api'
import { renderProviders } from '@/test/render-providers'
import MemberZones from './MemberZones'

const MEMBERS: WorkspaceMember[] = [
  {
    id: 1, workspace_id: 10, user_id: 1, role: 'editor', pinned: false,
    user: { id: 1, username: 'alice', nickname: '爱丽丝', email: 'alice@example.com' },
  },
  {
    id: 2, workspace_id: 10, user_id: 2, role: 'viewer', pinned: false,
    user: { id: 2, username: 'bob', nickname: null, email: null },
  },
] as WorkspaceMember[]

function renderZones(canManageMembers = true) {
  return renderProviders(
    <MemberZones
      members={MEMBERS}
      membersLoading={false}
      canManageMembers={canManageMembers}
      currentMemberId={1}
      assignableRoles={[
        { value: 'editor', label: '编辑者' },
        { value: 'viewer', label: '查看者' },
      ]}
      onRoleChange={vi.fn()}
      onKick={vi.fn()}
      onAddMember={vi.fn()}
    />,
    { route: '/w/10/settings' },
  )
}

describe('MemberZones 成员分区', () => {
  it('按角色分区渲染成员，并展示用户名 / 昵称 / 邮箱', async () => {
    renderZones()

    expect(await screen.findByText('alice')).toBeInTheDocument()
    expect(screen.getByText('(爱丽丝)')).toBeInTheDocument()
    expect(screen.getByText('alice@example.com')).toBeInTheDocument()
    expect(screen.getByText('bob')).toBeInTheDocument()
    // 「我」标记落在当前登录成员上
    expect(screen.getByText('我')).toBeInTheDocument()
  })

  it('表格启用横向滚动且用户列保留固定列宽（窄屏不被压缩）', async () => {
    renderZones()

    await screen.findByText('alice')
    const content = document.querySelector('.ant-table-content') as HTMLElement
    const table = content.querySelector('table') as HTMLElement

    expect(content.style.overflowX).toBe('auto')
    expect(table.style.width).toBe('max-content')
    const colWidths = [...document.querySelectorAll('.ant-table colgroup col')].map(
      c => (c as HTMLElement).style.width,
    )
    expect(colWidths).toContain('220px')
    expect(colWidths).toContain('150px')
  })

  it('无成员管理权限时不渲染角色下拉与移除按钮', async () => {
    renderZones(false)

    await screen.findByText('alice')
    expect(screen.getAllByText('编辑者').length).toBeGreaterThan(0)
    expect(screen.queryByRole('button', { name: /移除/ })).toBeNull()
  })
})
