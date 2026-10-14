/** 添加成员弹窗：搜索候选用户 + 配置角色.
 *
 * 从 WorkspaceSettingsContent 抽出；页面侧传入候选数据与回调，本组件不依赖 React Query。
 */

import { Modal, Select } from 'antd'

import type { MemberUserBrief, WorkspaceRole } from '@/api'

import { ROLE_HINTS, ROLE_LABEL } from './workspaceRoles'

export default function AddMemberModal({
  open,
  onCancel,
  onSubmit,
  username,
  onUsernameChange,
  role,
  onRoleChange,
  candidates,
  candidatesLoading,
  candidatesSearch,
  onSearch,
  assignableRoles,
  submitting,
}: {
  open: boolean
  onCancel: () => void
  onSubmit: () => void
  username: string | null
  onUsernameChange: (username: string) => void
  role: WorkspaceRole
  onRoleChange: (role: WorkspaceRole) => void
  candidates: MemberUserBrief[]
  candidatesLoading: boolean
  candidatesSearch: string
  onSearch: (keyword: string) => void
  assignableRoles: Array<{ value: WorkspaceRole; label: string }>
  submitting: boolean
}) {
  return (
    <Modal
      title="添加成员"
      open={open}
      onCancel={onCancel}
      onOk={onSubmit}
      okText="添加"
      confirmLoading={submitting}
      okButtonProps={{ disabled: !username }}
      destroyOnHidden
    >
      <div style={{ marginBottom: 12 }}>
        <div style={{ marginBottom: 6, fontSize: 13, color: 'var(--cn-text-secondary)' }}>选择用户（系统内已注册且未加入本工作区）</div>
        <Select
          showSearch
          filterOption={false}
          onSearch={onSearch}
          placeholder="输入关键字搜索用户名或昵称..."
          style={{ width: '100%' }}
          value={username ?? undefined}
          onChange={(v: string) => onUsernameChange(v)}
          options={candidates.map(u => ({
            value: u.username,
            label: (
              <span>
                <strong>{u.username}</strong>
                {u.nickname && <span style={{ color: 'var(--cn-text-muted)', marginLeft: 8 }}>({u.nickname})</span>}
              </span>
            ),
          }))}
          notFoundContent={
            candidatesSearch
              ? (candidatesLoading ? '搜索中...' : '未找到匹配用户')
              : '请先输入关键字搜索用户'
          }
          loading={candidatesLoading}
        />
      </div>
      <div>
        <div style={{ marginBottom: 6, fontSize: 13, color: 'var(--cn-text-secondary)' }}>配置权限角色</div>
        <Select
          style={{ width: '100%' }}
          value={role}
          onChange={(v: WorkspaceRole) => onRoleChange(v)}
          options={assignableRoles.filter(r => r.value !== 'owner')}
        />
        <div style={{ marginTop: 6, fontSize: 12, color: 'var(--cn-text-muted)' }}>
          {ROLE_LABEL[role]} — {ROLE_HINTS[role]}
        </div>
      </div>
    </Modal>
  )
}
