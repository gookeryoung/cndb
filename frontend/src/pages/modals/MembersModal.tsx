/** 工作区成员管理面板 — 邀请 / 角色变更 / 移除. */

import { useState } from 'react'
import { Modal, Table, Button, Input, Select, message, Tag, Popconfirm, Empty, Descriptions } from 'antd'
import { PlusOutlined, UserDeleteOutlined } from '@ant-design/icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { workspaceApi } from '@/api'
import type { WorkspaceMember, WorkspaceRole } from '@/api'

interface Props {
  open: boolean
  wid: string
  onClose: () => void
}

const ROLE_LABEL: Record<WorkspaceRole, string> = {
  owner: '所有者',
  admin: '管理员',
  editor: '编辑者',
  viewer: '查看者',
}

const ROLE_OPTIONS: Array<{ value: WorkspaceRole; label: string }> = (Object.keys(ROLE_LABEL) as WorkspaceRole[])
  .filter(r => r !== 'owner')
  .map(r => ({ value: r, label: ROLE_LABEL[r] }))

export default function MembersModal({ open, wid, onClose }: Props) {
  const queryClient = useQueryClient()
  const [inviteName, setInviteName] = useState('')
  const [inviteRole, setInviteRole] = useState<WorkspaceRole>('editor')

  const { data: members = [], isLoading } = useQuery<WorkspaceMember[]>({
    queryKey: ['workspace-members', wid],
    queryFn: () => workspaceApi.members(wid),
    enabled: open && !!wid,
  })

  const invite = useMutation({
    mutationFn: ({ username, role }: { username: string; role: string }) => workspaceApi.addMember(wid, username, role),
    onSuccess: () => {
      message.success('已邀请用户')
      setInviteName('')
      queryClient.invalidateQueries({ queryKey: ['workspace-members', wid] })
    },
  })

  const changeRole = useMutation({
    mutationFn: ({ memberId, role }: { memberId: number | string; role: string }) => workspaceApi.updateMemberRole(wid, memberId, role),
    onSuccess: () => {
      message.success('角色已更新')
      queryClient.invalidateQueries({ queryKey: ['workspace-members', wid] })
    },
  })

  const kick = useMutation({
    mutationFn: (memberId: number | string) => workspaceApi.removeMember(wid, memberId),
    onSuccess: () => {
      message.success('已移除成员')
      queryClient.invalidateQueries({ queryKey: ['workspace-members', wid] })
    },
  })

  return (
    <Modal
      title="工作区成员"
      open={open}
      onCancel={onClose}
      footer={[<Button key="close" onClick={onClose}>关闭</Button>]}
      width={600}
      destroyOnHidden
    >
      {/* 邀请区域 */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 16, padding: 12, background: '#f8fafc', borderRadius: 8 }}>
        <Input
          placeholder="用户名"
          value={inviteName}
          onChange={e => setInviteName(e.target.value)}
          style={{ flex: 1 }}
        />
        <Select
          value={inviteRole}
          onChange={setInviteRole}
          style={{ width: 120 }}
          options={ROLE_OPTIONS}
        />
        <Button
          type="primary"
          icon={<PlusOutlined />}
          disabled={!inviteName.trim()}
          loading={invite.isPending}
          onClick={() => invite.mutate({ username: inviteName.trim(), role: inviteRole })}
        >邀请</Button>
      </div>

      {/* 成员列表 */}
      <Table
        rowKey="id"
        size="small"
        loading={isLoading}
        dataSource={members}
        locale={{ emptyText: <Empty description="暂无成员" /> }}
        pagination={false}
        columns={[
          {
            title: '用户',
            render: (_, m) => (
              <Descriptions column={1} size="small" style={{ marginBottom: 0 }}>
                <Descriptions.Item label="用户名">{m.username}</Descriptions.Item>
                {m.email && <Descriptions.Item label="邮箱">{m.email}</Descriptions.Item>}
              </Descriptions>
            ),
          },
          {
            title: '角色', width: 180,
            render: (_, m) => {
              if (m.role === 'owner') {
                return <Tag color="gold">{ROLE_LABEL[m.role]}</Tag>
              }
              return (
                <Select
                  value={m.role}
                  onChange={(v: string) => changeRole.mutate({ memberId: m.id, role: v })}
                  size="small"
                  style={{ width: 140 }}
                  options={[...ROLE_OPTIONS, { value: 'owner', label: ROLE_LABEL.owner, disabled: true }]}
                />
              )
            },
          },
          {
            title: '操作', width: 80,
            render: (_, m) => m.role !== 'owner' ? (
              <Popconfirm
                title={`移除「${m.username}」？`}
                onConfirm={() => kick.mutate(m.id)}
              >
                <Button size="small" type="text" danger icon={<UserDeleteOutlined />} />
              </Popconfirm>
            ) : null,
          },
        ]}
      />
    </Modal>
  )
}
