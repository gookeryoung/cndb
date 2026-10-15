/** 成员三区布局：编辑者区 / 查看者区（含角色变更与移除）.
 *
 * 从 WorkspaceSettingsContent 的 membersTabChildren 抽出；页面侧把成员数据与三个
 * 回调传入，本组件不直接依赖 React Query。
 */

import { Button, Card, Popconfirm, Select, Space, Table, Tag, Tooltip } from 'antd'
import { PlusOutlined, UserDeleteOutlined, UserOutlined } from '@ant-design/icons'

import type { WorkspaceMember, WorkspaceRole } from '@/api'

import { ROLE_HINTS, ROLE_LABEL } from './workspaceRoles'

export default function MemberZones({
  members,
  membersLoading,
  canManageMembers,
  currentMemberId,
  assignableRoles,
  onRoleChange,
  onKick,
  onAddMember,
}: {
  members: WorkspaceMember[]
  membersLoading: boolean
  canManageMembers: boolean
  currentMemberId: number | string | null | undefined
  assignableRoles: Array<{ value: WorkspaceRole; label: string }>
  onRoleChange: (memberId: number | string, role: string) => void
  onKick: (memberId: number | string) => void
  onAddMember: (role: 'editor' | 'viewer') => void
}) {
  return (
    <>
      {(['editor', 'viewer'] as const).map(zoneRole => {
        const list = members.filter(m => m.role === zoneRole)
        return (
          <Card
            key={zoneRole}
            size="small"
            title={<Space><UserOutlined /> {ROLE_LABEL[zoneRole]}（{list.length}）</Space>}
            style={{ marginBottom: 12 }}
            extra={
              canManageMembers ? (
                <Button size="small" type="primary" icon={<PlusOutlined />} onClick={() => onAddMember(zoneRole)}>
                  添加成员
                </Button>
              ) : null
            }
          >
            {list.length === 0 ? (
              <div style={{ color: 'var(--cn-text-muted)', fontSize: 13, padding: '6px 0' }}>
                暂无{ROLE_LABEL[zoneRole]}
              </div>
            ) : (
              <Table
                rowKey="id"
                size="small"
                loading={membersLoading}
                dataSource={list}
                pagination={false}
                scroll={{ x: 'max-content' }}
                columns={[
                  {
                    title: '用户',
                    width: 220,
                    render: (_, m) => {
                      const u = m.user
                      const isMe = currentMemberId === m.id
                      return (
                        <div>
                          <div style={{ fontWeight: 500 }}>
                            {u.username}
                            {u.nickname && <span style={{ color: 'var(--cn-text-muted)', marginLeft: 8, fontSize: 13 }}>({u.nickname})</span>}
                            {isMe && <Tag color="blue" style={{ marginLeft: 8 }}>我</Tag>}
                          </div>
                          {u.email && <div style={{ color: 'var(--cn-text-muted)', fontSize: 12 }}>{u.email}</div>}
                        </div>
                      )
                    },
                  },
                  {
                    title: '角色', width: 150,
                    render: (_, m) => {
                      if (!canManageMembers) {
                        return <Tag>{ROLE_LABEL[zoneRole]}</Tag>
                      }
                      return (
                        <Select
                          value={zoneRole}
                          onChange={(v: string) => onRoleChange(m.id, v)}
                          size="small"
                          style={{ width: 120 }}
                          disabled={!canManageMembers}
                          options={assignableRoles}
                          optionRender={option => (
                            <div>
                              <div>{option.label}</div>
                              <div style={{ fontSize: 11, color: 'var(--cn-text-muted)', lineHeight: 1.5 }}>
                                {ROLE_HINTS[option.value as WorkspaceRole]}
                              </div>
                            </div>
                          )}
                        />
                      )
                    },
                  },
                  {
                    title: '操作', width: 80,
                    render: (_, m) => {
                      if (!canManageMembers) return null
                      return (
                        <Popconfirm
                          title={`移除「${m.user.username}」？`}
                          description="该成员将从工作区中移出"
                          onConfirm={() => onKick(m.id)}
                        >
                          <Tooltip title="移除成员：收回其在本工作区的访问权限">
                            <Button size="small" type="text" danger icon={<UserDeleteOutlined />} />
                          </Tooltip>
                        </Popconfirm>
                      )
                    },
                  },
                ]}
              />
            )}
          </Card>
        )
      })}
    </>
  )
}
