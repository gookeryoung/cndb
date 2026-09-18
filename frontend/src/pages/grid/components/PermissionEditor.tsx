/** 表权限编辑器 — 嵌入在 Modal 内.
 *
 * 上半部分：Owner Card + Members Table（新增成员 / 切换 read-write / 移除成员 / 转让所有权）
 * 下半部分：原有 TablePermission 编辑 UI（隐藏字段 — 保留, 未改动）
 */

import { useState, useMemo } from 'react'
import {
  Card, Avatar, Button, Table, Select, Modal, Tag, Space, Form, message, Popconfirm, Tooltip,
} from 'antd'
import {
  SafetyOutlined, UserOutlined, SwapOutlined, PlusOutlined, DeleteOutlined,
} from '@ant-design/icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  tableMembersApi, workspaceApi,
} from '@/api'
import type {
  Field, TablePermission, TableOwnerInfo, TableMember, WorkspaceRole,
} from '@/api'
import { useAuthStore } from '@/store'

interface PermissionEditorProps {
  fields: Field[]
  data?: TablePermission
  wid: number | string
  tid: number | string
  /** 表拥有者（从 TableDetail.owner 获取） */
  owner?: TableOwnerInfo | null
}

// ───────────────────────── 隐藏字段 + 备注（原逻辑保留） ─────────────────────────

/** 把后端 hidden_fields（dict: 角色名 → 隐藏字段列表）展平成一个 Set.
 *  后端 schema: hidden_fields: dict[str, Any] = { "admin": ["name"], "editor": [...] }
 *  历史遗留：早期设计为数组，后端改为按角色分桶后前端没跟进，需要兼容两种形态.
 */
function buildHiddenSet(hidden: unknown): Set<string> {
  const set = new Set<string>()
  if (!hidden) return set
  if (Array.isArray(hidden)) {
    hidden.forEach(v => set.add(String(v)))
  } else if (typeof hidden === 'object') {
    // 角色 → 列表 的 dict，把所有角色的 hidden fields 合并
    Object.values(hidden as Record<string, unknown>).forEach(v => {
      if (Array.isArray(v)) v.forEach(x => set.add(String(x)))
      else if (v != null) set.add(String(v))
    })
  }
  return set
}

// ───────────────────────── 主组件 ─────────────────────────

export default function PermissionEditor({ fields, data, wid, tid, owner }: PermissionEditorProps) {
  const user = useAuthStore(s => s.user)
  const queryClient = useQueryClient()
  const [transferOpen, setTransferOpen] = useState(false)
  const [addOpen, setAddOpen] = useState(false)
  const hiddenSet = buildHiddenSet(data?.hidden_fields as unknown)

  // ── 表成员列表 ──
  const { data: members = [], isLoading: membersLoading } = useQuery<TableMember[]>({
    queryKey: ['table-members', wid, tid],
    queryFn: () => tableMembersApi.list(wid, tid),
  })

  // ── 工作区详情（判断当前用户角色） ──
  const { data: workspace } = useQuery({
    queryKey: ['workspaces', wid],
    queryFn: () => workspaceApi.get(wid!),
    enabled: !!wid,
  })

  // ── 工作区成员（作为用户选择候选） ──
  const { data: wsMembers = [] } = useQuery({
    queryKey: ['workspaces', wid, 'members'],
    queryFn: () => workspaceApi.members(wid!),
    enabled: !!wid,
  })

  const currentUserRole: WorkspaceRole | null | undefined = workspace?.current_user_role

  const isOwner = !!owner && !!user && String(owner.id) === String(user.id)
  const isWsAdminOrAbove = currentUserRole === 'owner' || currentUserRole === 'admin'
  const canManageMembers = isOwner || isWsAdminOrAbove

  // ── 成员操作 ──
  const addMember = useMutation({
    mutationFn: (payload: { user_id: number; role: 'read' | 'write' }) =>
      tableMembersApi.add(wid, tid, payload),
    onSuccess: () => {
      message.success('已添加成员')
      queryClient.invalidateQueries({ queryKey: ['table-members', wid, tid] })
      setAddOpen(false)
    },
    onError: () => message.error('添加成员失败'),
  })

  const updateMember = useMutation({
    mutationFn: (args: { userId: number; role: 'read' | 'write' }) =>
      tableMembersApi.update(wid, tid, args.userId, { role: args.role }),
    onSuccess: () => {
      message.success('已更新授权')
      queryClient.invalidateQueries({ queryKey: ['table-members', wid, tid] })
    },
    onError: () => message.error('更新失败'),
  })

  const removeMember = useMutation({
    mutationFn: (userId: number) => tableMembersApi.remove(wid, tid, userId),
    onSuccess: () => {
      message.success('已移除成员')
      queryClient.invalidateQueries({ queryKey: ['table-members', wid, tid] })
    },
    onError: () => message.error('移除失败'),
  })

  const transferOwner = useMutation({
    mutationFn: (userId: number) => tableMembersApi.transferOwner(wid, tid, { user_id: userId }),
    onSuccess: () => {
      message.success('所有权已转让')
      queryClient.invalidateQueries({ queryKey: ['table-settings', wid, tid] })
      queryClient.invalidateQueries({ queryKey: ['workspaces', wid, 'tables'] })
      setTransferOpen(false)
    },
    onError: () => message.error('转让失败'),
  })

  // ── 可选用户（排除当前已在成员列表里的 + 排除当前拥有者） ──
  // 注意：Select options 的 value 统一用 string，避免 Ant Design 内部类型匹配失败
  // （number vs string 类型不一致时 Select 可能把原始 value 渲染出来而不是 label）
  const candidateUsers = useMemo(() => {
    const existingIds = new Set(members.map(m => String(m.user_id)))
    const ownerIdStr = owner ? String(owner.id) : null
    return wsMembers
      .filter(m => !existingIds.has(String(m.user.id)) && String(m.user.id) !== ownerIdStr)
      .map(m => ({
        value: String(m.user.id),
        label: `${m.user.username}${m.user.nickname ? ` (${m.user.nickname})` : ''}`,
      }))
  }, [wsMembers, members, owner])

  // ── 成员表列 ──
  const memberColumns = [
    {
      title: '用户',
      dataIndex: 'username',
      key: 'username',
      render: (name: string) => (
        <Space>
          <Avatar size="small" icon={<UserOutlined />} />
          <span>{name}</span>
        </Space>
      ),
    },
    {
      title: '角色',
      dataIndex: 'role',
      key: 'role',
      width: 140,
      render: (role: 'read' | 'write', record: TableMember) => (
        <Select
          size="small"
          value={role}
          disabled={!canManageMembers}
          style={{ width: 120 }}
          onChange={(v) => updateMember.mutate({ userId: Number(record.user_id), role: v })}
          options={[
            { value: 'read', label: <Tag color="blue">read · 只读</Tag> },
            { value: 'write', label: <Tag color="green">write · 可编辑</Tag> },
          ]}
        />
      ),
    },
    {
      title: '操作',
      key: 'actions',
      width: 80,
      render: (_: unknown, record: TableMember) => (
        <Popconfirm
          title={`移除成员 "${record.username}" ？`}
          description="该用户将失去本表显式授予的成员权限。"
          okText="移除"
          okType="danger"
          okButtonProps={{ danger: true, type: 'primary' }}
          cancelText="取消"
          onConfirm={() => removeMember.mutate(Number(record.user_id))}
          disabled={!canManageMembers}
        >
          <Button size="small" type="text" danger icon={<DeleteOutlined />} disabled={!canManageMembers}>
            移除
          </Button>
        </Popconfirm>
      ),
    },
  ]

  return (
    <div style={{ marginTop: 12 }}>
      {/* ─────────────── Owner Card ─────────────── */}
      <Card
        size="small"
        title={<Space><SafetyOutlined /> 表拥有者</Space>}
        style={{ marginBottom: 12 }}
        extra={
          canManageMembers ? (
            <Button
              size="small"
              icon={<SwapOutlined />}
              onClick={() => setTransferOpen(true)}
            >
              转让所有权
            </Button>
          ) : (
            <Tooltip title="仅当前拥有者或工作区管理员可转让">
              <Button size="small" icon={<SwapOutlined />} disabled>转让所有权</Button>
            </Tooltip>
          )
        }
      >
        {owner ? (
          <Space>
            <Avatar icon={<UserOutlined />} />
            <div>
              <div style={{ fontWeight: 500 }}>{owner.username}</div>
              <div style={{ fontSize: 12, color: 'var(--cn-text-muted)' }}>
                {isOwner ? '（就是您）' : ''}拥有者对该表负全责, 可管理成员与转让所有权
              </div>
            </div>
          </Space>
        ) : (
          <div style={{ color: 'var(--cn-text-muted)' }}>
            （未指定） — 请尽快指定业务责任人
          </div>
        )}
      </Card>

      {/* ─────────────── Members Table ─────────────── */}
      <Card
        size="small"
        title={<Space><UserOutlined /> 表成员（{members.length}）</Space>}
        style={{ marginBottom: 16 }}
        extra={
          canManageMembers ? (
            <Button size="small" type="primary" icon={<PlusOutlined />} onClick={() => setAddOpen(true)}>
              添加成员
            </Button>
          ) : null
        }
      >
        <Table
          size="small"
          loading={membersLoading}
          rowKey="user_id"
          columns={memberColumns}
          dataSource={members}
          pagination={false}
          locale={{ emptyText: <span style={{ color: 'var(--cn-text-muted)' }}>暂无显式成员</span> }}
        />
      </Card>

      {/* ─────────────── 原有 TablePermission UI ─────────────── */}
      <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8, marginTop: 4 }}>
        隐藏字段（勾选后用户不可见）
      </div>
      <Form>
        {fields.filter(f => !f.hidden).map(f => (
          <Form.Item key={f.id} style={{ marginBottom: 4 }}>
            <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13 }}>
              <input
                type="checkbox"
                value={f.name}
                defaultChecked={hiddenSet.has(f.name)}
                data-perm-hidden
              />
              {f.name} <span style={{ color: '#9ca3af', fontSize: 11 }}>({f.field_type})</span>
            </label>
          </Form.Item>
        ))}
      </Form>

      {/* ─────────────── 转让所有权 Modal ─────────────── */}
      <TransferOwnerModal
        open={transferOpen}
        onClose={() => setTransferOpen(false)}
        candidates={candidateUsers}
        loading={transferOwner.isPending}
        onSubmit={(userId) => transferOwner.mutate(userId)}
      />

      {/* ─────────────── 添加成员 Modal ─────────────── */}
      <AddMemberModal
        open={addOpen}
        onClose={() => setAddOpen(false)}
        candidates={candidateUsers}
        loading={addMember.isPending}
        onSubmit={(userId, role) => addMember.mutate({ user_id: userId, role })}
      />
    </div>
  )
}

// ───────────────────────── 两个辅助 Modal ─────────────────────────

function TransferOwnerModal({
  open, onClose, candidates, loading, onSubmit,
}: {
  open: boolean
  onClose: () => void
  candidates: Array<{ value: string; label: string }>
  loading: boolean
  onSubmit: (userId: number) => void
}) {
  const [selected, setSelected] = useState<string | null>(null)
  return (
    <Modal
      title="转让所有权"
      open={open}
      onCancel={onClose}
      onOk={() => selected != null && onSubmit(Number(selected))}
      okText="确认转让"
      okType="danger"
      confirmLoading={loading}
      okButtonProps={{ disabled: selected == null }}
      destroyOnHidden
    >
      <div style={{ marginBottom: 8, color: 'var(--cn-text-secondary)', fontSize: 13 }}>
        将表的拥有权转让给下列工作区成员。转让后您将失去拥有者特权，回落到工作区角色默认权限。
      </div>
      <Select
        showSearch
        placeholder="选择接收者"
        style={{ width: '100%' }}
        value={selected}
        onChange={setSelected}
        options={candidates}
        filterOption={(input, option) =>
          (option?.label ?? '').toLowerCase().includes(input.toLowerCase())
        }
      />
    </Modal>
  )
}

function AddMemberModal({
  open, onClose, candidates, loading, onSubmit,
}: {
  open: boolean
  onClose: () => void
  candidates: Array<{ value: string; label: string }>
  loading: boolean
  onSubmit: (userId: number, role: 'read' | 'write') => void
}) {
  const [userId, setUserId] = useState<string | null>(null)
  const [role, setRole] = useState<'read' | 'write'>('read')
  return (
    <Modal
      title="添加表成员"
      open={open}
      onCancel={onClose}
      onOk={() => userId != null && onSubmit(Number(userId), role)}
      okText="添加"
      confirmLoading={loading}
      okButtonProps={{ disabled: userId == null }}
      destroyOnHidden
    >
      <div style={{ marginBottom: 12 }}>
        <div style={{ marginBottom: 6, fontSize: 13, color: 'var(--cn-text-secondary)' }}>选择用户</div>
        <Select
          showSearch
          placeholder="搜索工作区成员..."
          style={{ width: '100%' }}
          value={userId}
          onChange={setUserId}
          options={candidates}
          filterOption={(input, option) =>
            (option?.label ?? '').toLowerCase().includes(input.toLowerCase())
          }
        />
      </div>
      <div>
        <div style={{ marginBottom: 6, fontSize: 13, color: 'var(--cn-text-secondary)' }}>授权级别</div>
        <Select
          style={{ width: '100%' }}
          value={role}
          onChange={setRole}
          options={[
            { value: 'read', label: 'read · 只读' },
            { value: 'write', label: 'write · 可编辑（可编辑数据与视图, 不可改结构）' },
          ]}
        />
      </div>
    </Modal>
  )
}
