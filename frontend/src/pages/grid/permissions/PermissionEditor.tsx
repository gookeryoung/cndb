/** 表权限编辑器 — 三区布局（所有者 / 编辑者 / 查看者）.
 *
 * 所有者区：Owner Card（表 owner + 转让所有权）
 * 编辑者区：write 成员列表 + 添加成员（默认 write）
 * 查看者区：read 成员列表 + 添加成员（默认 read）
 * 成员可在区间移动（行内 Select 切 read/write，复用 update）；移除/转让逻辑不变。
 * 下半部分：隐藏字段编辑 UI（保留，未改动）。
 */

import { useState, useMemo, useEffect, useRef } from 'react'
import {
  Card, Avatar, Button, Table, Select, Modal, Tag, Space, Checkbox, App as AntApp, Popconfirm, Tooltip,
  Alert, Radio,
} from 'antd'
import {
  SafetyOutlined, UserOutlined, SwapOutlined, PlusOutlined, DeleteOutlined,
  FilterOutlined, EyeOutlined, EditOutlined, TeamOutlined, NumberOutlined,
} from '@ant-design/icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  tableMembersApi, workspaceApi, rowPermissionApi,
} from '@/api'
import type {
  Field, TableOwnerInfo, TableMember, WorkspaceRole,
  RowPermissionRule, RowRuleSubject, RowSubjectType, RowActionType,
} from '@/api'
import { useAuthStore } from '@/store'
import { useResponsive } from '@/hooks/useResponsive'
import FilterConditionEditor from '@/pages/grid/view-config/FilterConditionEditor'
import type { FilterRule } from '@/pages/grid/view-config/FilterConditionEditor'
import { WEIGHT } from '@/theme/tokens'

interface PermissionEditorProps {
  fields: Field[]
  wid: number | string
  tid: number | string
  /** 表拥有者（从 TableDetail.owner 获取） */
  owner?: TableOwnerInfo | null
  /** 受控：当前勾选为隐藏的字段名集合（状态由父组件 TableSettingsPage 持有） */
  hiddenNames: string[]
  /** 受控回调：勾选变化时通知父组件 */
  onHiddenNamesChange: (names: string[]) => void
  /** 是否具备表 EDIT_SCHEMA（行级权限区配置门控；缺省视为无权限） */
  canEditSchema?: boolean
}

// ───────────────────────── 隐藏字段 + 备注（原逻辑保留） ─────────────────────────

/** 把后端 hidden_fields（dict: 角色名 → 隐藏字段列表）展平成一个 Set.
 *  后端 schema: hidden_fields: dict[str, Any] = { "editor": ["name"], "viewer": [...] }
 *  历史遗留：早期设计为数组，后端改为按角色分桶后前端没跟进，需要兼容两种形态.
 */
export function buildHiddenSet(hidden: unknown): Set<string> {
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

export default function PermissionEditor({ fields, wid, tid, owner, hiddenNames, onHiddenNamesChange, canEditSchema = false }: PermissionEditorProps) {
  const { message } = AntApp.useApp()
  const user = useAuthStore(s => s.user)
  const queryClient = useQueryClient()
  const [transferOpen, setTransferOpen] = useState(false)
  const [addOpen, setAddOpen] = useState(false)
  /** 添加成员弹窗预选授权级别（由打开入口所在分区决定） */
  const [addRole, setAddRole] = useState<'read' | 'write'>('read')
  /** 行级权限规则编辑器：null=关闭，'new'=新建，其余为待编辑规则 */
  const [ruleEditor, setRuleEditor] = useState<RowPermissionRule | 'new' | null>(null)

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
  // 管理门控：表 owner 或工作区 owner（三级角色，admin 已迁移为 editor）
  const canManageMembers = isOwner || currentUserRole === 'owner'

  // ── 成员操作 ──
  const addMember = useMutation({
    mutationFn: (payload: { user_id: number; role: 'read' | 'write' }) =>
      tableMembersApi.add(wid, tid, payload),
    onSuccess: () => {
      message.success('已添加成员')
      queryClient.invalidateQueries({ queryKey: ['table-members', wid, tid] })
      setAddOpen(false)
    },
    onError: (err) => message.error(err instanceof Error ? err.message : '添加成员失败'),
  })

  const updateMember = useMutation({
    mutationFn: (args: { userId: number; role: 'read' | 'write' }) =>
      tableMembersApi.update(wid, tid, args.userId, { role: args.role }),
    onSuccess: () => {
      message.success('已更新授权')
      queryClient.invalidateQueries({ queryKey: ['table-members', wid, tid] })
    },
    onError: (err) => message.error(err instanceof Error ? err.message : '更新失败'),
  })

  const removeMember = useMutation({
    mutationFn: (userId: number) => tableMembersApi.remove(wid, tid, userId),
    onSuccess: () => {
      message.success('已移除成员')
      queryClient.invalidateQueries({ queryKey: ['table-members', wid, tid] })
    },
    onError: (err) => message.error(err instanceof Error ? err.message : '移除失败'),
  })

  const transferOwner = useMutation({
    mutationFn: (userId: number) => tableMembersApi.transferOwner(wid, tid, { user_id: userId }),
    onSuccess: () => {
      message.success('所有权已转让')
      queryClient.invalidateQueries({ queryKey: ['table-settings', wid, tid] })
      queryClient.invalidateQueries({ queryKey: ['workspaces', wid, 'tables'] })
      setTransferOpen(false)
    },
    onError: (err) => message.error(err instanceof Error ? err.message : '转让失败'),
  })

  // ── 行级权限规则（ADR 0004）：配置属敏感信息，查询需 EDIT_SCHEMA ──
  const { data: rowRules = [], isLoading: rulesLoading } = useQuery<RowPermissionRule[]>({
    queryKey: ['row-rules', wid, tid],
    queryFn: () => rowPermissionApi.list(wid, tid),
    enabled: canEditSchema,
  })
  const { data: subjects = [] } = useQuery<RowRuleSubject[]>({
    queryKey: ['row-rule-subjects', wid, tid],
    queryFn: () => rowPermissionApi.subjects(wid, tid),
    enabled: canEditSchema,
  })

  const invalidateRules = () => {
    queryClient.invalidateQueries({ queryKey: ['row-rules', wid, tid] })
  }

  const createRule = useMutation({
    mutationFn: (payload: Parameters<typeof rowPermissionApi.create>[2]) =>
      rowPermissionApi.create(wid, tid, payload),
    onSuccess: () => {
      message.success('已创建行级权限规则')
      invalidateRules()
      setRuleEditor(null)
    },
    onError: (err) => message.error(err instanceof Error ? err.message : '创建规则失败'),
  })

  const updateRule = useMutation({
    mutationFn: (args: { ruleId: number; payload: Parameters<typeof rowPermissionApi.update>[3] }) =>
      rowPermissionApi.update(wid, tid, args.ruleId, args.payload),
    onSuccess: () => {
      message.success('已更新行级权限规则')
      invalidateRules()
      setRuleEditor(null)
    },
    onError: (err) => message.error(err instanceof Error ? err.message : '更新规则失败'),
  })

  const removeRule = useMutation({
    mutationFn: (ruleId: number) => rowPermissionApi.remove(wid, tid, ruleId),
    onSuccess: () => {
      message.success('已删除行级权限规则')
      invalidateRules()
    },
    onError: (err) => message.error(err instanceof Error ? err.message : '删除规则失败'),
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
  // 窄屏：隐藏字段三列在 390px 下每列仅约 110px，字段名会被截断
  const { isMobile } = useResponsive()

  const memberColumns = [
    {
      title: '用户',
      width: 220,
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

  // ── 行级权限规则表列 ──
  const ruleColumns = [
    {
      title: '主体',
      key: 'subject',
      render: (_: unknown, rule: RowPermissionRule) => (
        <Space size={4}>
          {rule.subject_type === 'user'
            ? <UserOutlined />
            : <TeamOutlined />}
          <span>{rule.subject_name}</span>
          <Tag color={rule.subject_type === 'user' ? 'blue' : 'geekblue'}>
            {rule.subject_type === 'user' ? '成员' : '成员档'}
          </Tag>
        </Space>
      ),
    },
    {
      title: '动作',
      dataIndex: 'action',
      key: 'action',
      width: 110,
      render: (action: RowActionType) => action === 'edit'
        ? <Tag color="green" icon={<EditOutlined />}>可编辑</Tag>
        : <Tag color="blue" icon={<EyeOutlined />}>可查看</Tag>,
    },
    {
      title: '条件',
      key: 'filters',
      render: (_: unknown, rule: RowPermissionRule) => renderRuleSummary(rule),
    },
    {
      title: '操作',
      key: 'actions',
      width: 130,
      render: (_: unknown, rule: RowPermissionRule) => (
        <Space>
          <Button size="small" type="link" disabled={!canEditSchema}
            onClick={() => setRuleEditor(rule)}>编辑</Button>
          <Popconfirm
            title="删除这条行级权限规则？"
            description="该主体将不再额外获得本条规则命中的行权限。"
            okText="删除"
            okType="danger"
            okButtonProps={{ danger: true, type: 'primary' }}
            cancelText="取消"
            onConfirm={() => removeRule.mutate(rule.id)}
            disabled={!canEditSchema}
          >
            <Button size="small" type="link" danger disabled={!canEditSchema}>删除</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  // ── 行级权限规则编辑器：新建或编辑时提交 ──
  const handleSubmitRule = (payload: {
    subject_type: RowSubjectType
    subject_id: string
    action: RowActionType
    filters: FilterRule[]
    filter_type: 'AND' | 'OR'
  }) => {
    if (ruleEditor && ruleEditor !== 'new') {
      updateRule.mutate({
        ruleId: ruleEditor.id,
        payload: { filters: payload.filters, filter_type: payload.filter_type },
      })
    } else {
      createRule.mutate({
        subject_type: payload.subject_type,
        subject_id: payload.subject_id,
        action: payload.action,
        filters: payload.filters,
        filter_type: payload.filter_type,
      })
    }
  }

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
            <Tooltip title="仅表拥有者或工作区所有者可转让">
              <Button size="small" icon={<SwapOutlined />} disabled>转让所有权</Button>
            </Tooltip>
          )
        }
      >
        {owner ? (
          <Space>
            <Avatar icon={<UserOutlined />} />
            <div>
              <div style={{ fontWeight: WEIGHT.medium }}>{owner.username}</div>
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

      {/* ─────────────── 编辑者区 / 查看者区（三区布局） ─────────────── */}
      {([
        { zoneRole: 'write', label: '编辑者' },
        { zoneRole: 'read', label: '查看者' },
      ] as const).map(({ zoneRole, label }) => {
        const list = members.filter(m => m.role === zoneRole)
        return (
          <Card
            key={zoneRole}
            size="small"
            title={<Space><UserOutlined /> {label}（{list.length}）</Space>}
            style={{ marginBottom: 16 }}
            extra={
              canManageMembers ? (
                <Button size="small" type="primary" icon={<PlusOutlined />} onClick={() => {
                  setAddRole(zoneRole)
                  setAddOpen(true)
                }}>
                  添加成员
                </Button>
              ) : null
            }
          >
            {list.length === 0 ? (
              <div style={{ color: 'var(--cn-text-muted)', fontSize: 13, padding: '6px 0' }}>暂无{label}</div>
            ) : (
              <Table
                size="small"
                loading={membersLoading}
                rowKey="user_id"
                columns={memberColumns}
                dataSource={list}
                pagination={false}
                // 窄屏不压缩列宽（用户名 / 角色 / 操作三列），改为容器横向滚动
                scroll={{ x: 'max-content' }}
              />
            )}
          </Card>
        )
      })}

      {/* ─────────────── 隐藏字段（受控 Checkbox.Group，状态由父组件持有） ─────────────── */}
      <div style={{ fontSize: 13, fontWeight: WEIGHT.semibold, marginBottom: 8, marginTop: 4 }}>
        隐藏字段（勾选后用户不可见）
      </div>
      {fields.filter(f => !f.hidden).length === 0 ? (
        <div style={{ color: 'var(--cn-text-muted)', fontSize: 12 }}>暂无可见字段</div>
      ) : (
        <Checkbox.Group
          value={hiddenNames}
          onChange={(vals) => onHiddenNamesChange(vals as string[])}
          style={{ width: '100%' }}
        >
          <div style={{
            display: 'grid',
            gridTemplateColumns: isMobile ? '1fr' : 'repeat(3, minmax(0, 1fr))',
            gap: '6px 16px',
          }}>
            {fields.filter(f => !f.hidden).map(f => (
              <Checkbox key={String(f.id)} value={f.name} style={{ marginInlineStart: 0 }}>
                <span
                  style={{
                    fontSize: 13,
                    display: 'inline-block',
                    maxWidth: '100%',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                    verticalAlign: 'bottom',
                  }}
                >
                  {f.name} <span style={{ color: 'var(--cn-text-muted)', fontSize: 11 }}>({f.field_type})</span>
                </span>
              </Checkbox>
            ))}
          </div>
        </Checkbox.Group>
      )}

      {/* ─────────────── 行级权限（ADR 0004）：按筛选条件给指定主体查看 / 编辑权 ─────────────── */}
      <Card
        size="small"
        title={<Space><FilterOutlined />{`行级权限（${rowRules.length}）`}</Space>}
        style={{ marginTop: 16 }}
        extra={
          canEditSchema ? (
            <Button size="small" type="primary" icon={<PlusOutlined />} onClick={() => setRuleEditor('new')}>
              添加规则
            </Button>
          ) : (
            <Tooltip title="需要本表的「编辑结构」权限（EDIT_SCHEMA）">
              <Button size="small" type="primary" icon={<PlusOutlined />} disabled>添加规则</Button>
            </Tooltip>
          )
        }
      >
        <div style={{ fontSize: 12, color: 'var(--cn-text-secondary)', marginBottom: 8 }}>
          每条规则 = 一组筛选条件命中的<b>数据行</b>，授予<b>指定成员</b>或<b>表级成员档</b>的「可查看 / 可编辑」权限。
          规则在表默认档（对所有非管理员的行过滤）之上<b>按主体开放</b>；拥有者与管理员不受行规则限制。
        </div>
        {!canEditSchema ? (
          <Alert
            type="info"
            showIcon
            message="无行级权限配置权限"
            description="行级权限规则属敏感配置，仅具备本表「编辑结构」权限者可查看与配置。"
          />
        ) : rulesLoading ? (
          <div style={{ color: 'var(--cn-text-muted)', fontSize: 13 }}>加载中...</div>
        ) : rowRules.length === 0 ? (
          <div style={{ color: 'var(--cn-text-muted)', fontSize: 13 }}>暂无行级权限规则</div>
        ) : (
          <Table
            size="small"
            rowKey="id"
            columns={ruleColumns}
            dataSource={rowRules}
            pagination={false}
            scroll={{ x: 'max-content' }}
          />
        )}
      </Card>

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
        defaultRole={addRole}
        onSubmit={(userId, role) => addMember.mutate({ user_id: userId, role })}
      />

      {/* ─────────────── 行级权限规则编辑器 Modal ─────────────── */}
      <RowRuleEditorModal
        open={ruleEditor !== null}
        editing={ruleEditor !== null && ruleEditor !== 'new' ? ruleEditor : null}
        fields={fields.filter(f => !f.hidden)}
        subjects={subjects}
        loading={createRule.isPending || updateRule.isPending}
        onClose={() => setRuleEditor(null)}
        onSubmit={handleSubmitRule}
        onPreview={(filters, filterType) => rowPermissionApi.preview(wid, tid, { filters, filter_type: filterType })}
      />
    </div>
  )
}

// ───────────────────────── 行级权限辅助 ─────────────────────────

/** 规则条件摘要：无条件 = 全部行；有则展示组合方式与字段清单（最多 3 个，超出折叠） */
function renderRuleSummary(rule: RowPermissionRule) {
  const filters = rule.filters ?? []
  if (filters.length === 0) {
    return <span style={{ color: 'var(--cn-text-muted)' }}>全部行</span>
  }
  const names = filters.map(f => f.field_name).filter(Boolean)
  const shown = names.slice(0, 3).join('、')
  const more = names.length > 3 ? ` 等 ${names.length} 项` : ''
  return (
    <span style={{ fontSize: 12 }}>
      <Tag>{rule.filter_type}</Tag>
      {shown}{more}
    </span>
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
  open, onClose, candidates, loading, defaultRole, onSubmit,
}: {
  open: boolean
  onClose: () => void
  candidates: Array<{ value: string; label: string }>
  loading: boolean
  /** 预选授权级别（由打开入口所在分区决定） */
  defaultRole: 'read' | 'write'
  onSubmit: (userId: number, role: 'read' | 'write') => void
}) {
  const [userId, setUserId] = useState<string | null>(null)
  const [role, setRole] = useState<'read' | 'write'>(defaultRole)
  // open 变化时同步预选角色（每次打开弹窗重置为入口分区对应级别）
  if (open && role !== defaultRole) setRole(defaultRole)
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

// ───────────────────────── 行级权限规则编辑器 ─────────────────────────

/** 主体选择项的 value 形如 `type:id`（user / member_role） */
function subjectKey(subject_type: RowSubjectType, subject_id: string): string {
  return `${subject_type}:${subject_id}`
}

function RowRuleEditorModal({
  open, editing, fields, subjects, loading, onClose, onSubmit, onPreview,
}: {
  open: boolean
  /** 待编辑规则（null 表示新建） */
  editing: RowPermissionRule | null
  fields: Field[]
  subjects: RowRuleSubject[]
  loading: boolean
  onClose: () => void
  onSubmit: (payload: {
    subject_type: RowSubjectType
    subject_id: string
    action: RowActionType
    filters: FilterRule[]
    filter_type: 'AND' | 'OR'
  }) => void
  onPreview: (filters: FilterRule[], filterType: 'AND' | 'OR') => Promise<{ matched: number }>
}) {
  const isEdit = !!editing
  const [subject, setSubject] = useState<string | null>(null)
  const [action, setAction] = useState<RowActionType>('view')
  const [filters, setFilters] = useState<FilterRule[]>([])
  const [filterType, setFilterType] = useState<'AND' | 'OR'>('AND')
  const [previewCount, setPreviewCount] = useState<number | null>(null)
  const [previewing, setPreviewing] = useState(false)

  // 仅在弹窗由关→开的瞬间重置草稿：编辑时回填目标，新建时清空为默认值
  const wasOpenRef = useRef(false)
  useEffect(() => {
    if (open && !wasOpenRef.current) {
      if (editing) {
        setSubject(subjectKey(editing.subject_type, editing.subject_id))
        setAction(editing.action)
        setFilters(editing.filters ?? [])
        setFilterType(editing.filter_type ?? 'AND')
      } else {
        setSubject(null)
        setAction('view')
        setFilters([])
        setFilterType('AND')
      }
      setPreviewCount(null)
    }
    wasOpenRef.current = open
  }, [open, editing])

  const subjectOptions = subjects.map(s => ({
    value: subjectKey(s.subject_type, s.subject_id),
    label: `${s.name}（${s.subject_type === 'user' ? '成员' : '成员级档'}）`,
  }))

  const doPreview = async () => {
    setPreviewing(true)
    try {
      const res = await onPreview(filters, filterType)
      setPreviewCount(res.matched)
    } finally {
      setPreviewing(false)
    }
  }

  const canSubmit = subject != null && (filters.length === 0 || filters.some(f => f.field_name))

  return (
    <Modal
      title={isEdit ? '编辑行级权限规则' : '新建行级权限规则'}
      open={open}
      onCancel={onClose}
      width={620}
      onOk={() => {
        if (subject == null) return
        const [subject_type, ...rest] = subject.split(':')
        onSubmit({
          subject_type: subject_type as RowSubjectType,
          subject_id: rest.join(':'),
          action,
          filters: filters.filter(f => f.field_name),
          filter_type: filterType,
        })
      }}
      okText="保存"
      confirmLoading={loading}
      okButtonProps={{ disabled: !canSubmit }}
      destroyOnHidden
    >
      <div style={{ marginBottom: 12 }}>
        <div style={{ marginBottom: 6, fontSize: 13, color: 'var(--cn-text-secondary)' }}>授权主体</div>
        <Select
          showSearch
          placeholder="选择成员或成员档"
          style={{ width: '100%' }}
          value={subject}
          onChange={setSubject}
          options={subjectOptions}
          disabled={isEdit}
          filterOption={(input, option) =>
            (option?.label ?? '').toLowerCase().includes(input.toLowerCase())
          }
        />
        {isEdit && (
          <div style={{ marginTop: 4, fontSize: 12, color: 'var(--cn-text-muted)' }}>
            主体与动作创建后不可改；如需变更请删除后重建。
          </div>
        )}
      </div>
      <div style={{ marginBottom: 12 }}>
        <div style={{ marginBottom: 6, fontSize: 13, color: 'var(--cn-text-secondary)' }}>动作</div>
        <Radio.Group value={action} onChange={(e) => setAction(e.target.value)} disabled={isEdit}>
          <Radio value="view"><EyeOutlined /> 可查看（命中行可读，不可编辑）</Radio>
          <Radio value="edit"><EditOutlined /> 可编辑（命中行可读且可直编）</Radio>
        </Radio.Group>
      </div>
      <div style={{ marginBottom: 6, fontSize: 13, color: 'var(--cn-text-secondary)' }}>命中条件（不填 = 全部行）</div>
      <FilterConditionEditor
        fields={fields}
        rules={filters}
        logic={filterType}
        onLogicChange={setFilterType}
        onChange={setFilters}
        emptyText="暂无筛选条件（规则将命中全部行）"
        addText="添加筛选条件"
      />
      <div style={{ marginTop: 12, display: 'flex', alignItems: 'center', gap: 8 }}>
        <Button size="small" icon={<NumberOutlined />} loading={previewing} onClick={doPreview}>
          预览命中行数
        </Button>
        {previewCount != null && (
          <span style={{ fontSize: 12, color: 'var(--cn-text-secondary)' }}>
            预计命中 <b>{previewCount}</b> 行（仅统计您可见的行）
          </span>
        )}
      </div>
    </Modal>
  )
}
