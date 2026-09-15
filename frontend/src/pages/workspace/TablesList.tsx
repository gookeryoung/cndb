/** 工作区表列表页 — 数据资产目录视图.
 *
 * 支持创建/重命名/复制/删除 + CSV 自动建表 + API 自动建表.
 * 展示 Owner / MyAccess / MemberCount 三个权限元信息列, 并提供按访问级别筛选.
 */

import { Suspense, lazy, useMemo, useState } from 'react'
import {
  Button, Modal, Form, Input, Table, Typography, Empty, message, Space, Tag, Upload, Dropdown,
  Avatar, Segmented, Badge, Tooltip,
} from 'antd'
import {
  PlusOutlined, TableOutlined, DeleteOutlined, ClockCircleOutlined, CopyOutlined, EditOutlined,
  UploadOutlined, SettingOutlined, ApiOutlined, TeamOutlined, UserOutlined,
  LoginOutlined, MoreOutlined,
} from '@ant-design/icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useParams, useNavigate } from 'react-router-dom'
import { tableApi, workspaceApi, importApi } from '@/api'
import type { TableSummary, TableUpdate } from '@/api'
import { useAuth } from '@/auth/AuthContext'

const ApiImportDialog = lazy(() => import('@/pages/modals/ApiImportDialog'))

const { Title, Text } = Typography

type AccessFilter = 'all' | 'owner' | 'write' | 'read'

const ACCESS_TAG: Record<string, { color: string; label: string }> = {
  owner: { color: 'red', label: 'owner' },
  write: { color: 'green', label: 'write' },
  read: { color: 'blue', label: 'read' },
  none: { color: 'default', label: '默认' },
}

export default function TablesList() {
  const { wid } = useParams<{ wid: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { user } = useAuth()
  const [createOpen, setCreateOpen] = useState(false)
  const [editOpen, setEditOpen] = useState<TableSummary | null>(null)
  const [apiImportOpen, setApiImportOpen] = useState(false)
  const [filter, setFilter] = useState<AccessFilter>('all')
  const [form] = Form.useForm()
  const [editForm] = Form.useForm()

  // workspace 信息（标题展示）
  const { data: workspace } = useQuery({
    queryKey: ['workspaces', wid],
    queryFn: () => workspaceApi.get(wid!),
    enabled: !!wid,
  })

  // 表列表
  const { data: tables = [], isLoading } = useQuery<TableSummary[]>({
    queryKey: ['workspaces', wid, 'tables'],
    queryFn: () => tableApi.list(wid!),
    enabled: !!wid,
  })

  // ── 筛选后的表列表 ──
  const filteredTables = useMemo(() => {
    if (filter === 'all') return tables
    return tables.filter(t => {
      const access = t.my_access ?? 'none'
      // "我拥有的" 同时也包含显式标记为 owner 的表
      if (filter === 'owner') {
        if (access === 'owner') return true
        // 后端若没返回 my_access, 回退到比对 owner.id
        if (access === 'none' && t.owner && user) return String(t.owner.id) === String(user.id)
        return false
      }
      if (filter === 'write') return access === 'write' || access === 'owner'
      if (filter === 'read') return access === 'read' || access === 'write' || access === 'owner'
      return true
    })
  }, [tables, filter, user])

  const create = useMutation({
    mutationFn: (v: { name: string; description?: string }) => tableApi.create(wid!, v),
    onSuccess: (t) => {
      message.success(`已创建表 "${t.name}"`)
      queryClient.invalidateQueries({ queryKey: ['workspaces', wid, 'tables'] })
      queryClient.invalidateQueries({ queryKey: ['workspaces', wid] })
      setCreateOpen(false)
      form.resetFields()
      navigate(`/w/${wid}/tables/${t.id}`)
    },
  })

  const update = useMutation({
    mutationFn: ({ tid, data }: { tid: number | string; data: TableUpdate }) => tableApi.update(wid!, tid, data),
    onSuccess: () => {
      message.success('已更新')
      queryClient.invalidateQueries({ queryKey: ['workspaces', wid, 'tables'] })
      setEditOpen(null)
      editForm.resetFields()
    },
  })

  const copy = useMutation({
    mutationFn: (args: { tid: number | string; mode: 'structure' | 'all' }) =>
      tableApi.copy(wid!, args.tid, { mode: args.mode }),
    onSuccess: (t, args) => {
      const modeLabel = args.mode === 'all' ? '(含全部数据)' : '(仅结构)'
      message.success(`已复制为 "${t.name}" ${modeLabel}`)
      queryClient.invalidateQueries({ queryKey: ['workspaces', wid, 'tables'] })
    },
  })

  const remove = useMutation({
    mutationFn: (tid: number | string) => tableApi.remove(wid!, tid),
    onSuccess: () => {
      message.success('已删除')
      queryClient.invalidateQueries({ queryKey: ['workspaces', wid, 'tables'] })
      queryClient.invalidateQueries({ queryKey: ['workspaces', wid] })
    },
  })

  const csvCreate = useMutation({
    mutationFn: async (file: File) => {
      const text = await file.text()
      const tableName = file.name.replace(/\.csv$/i, '')
      return importApi.createFromCsv(wid!, tableName, text)
    },
    onSuccess: (result) => {
      message.success(`已从 CSV 创建表 "${result.table_name}" (${result.imported} 行)`)
      queryClient.invalidateQueries({ queryKey: ['workspaces', wid, 'tables'] })
      if (result.table_id) {
        navigate(`/w/${wid}/tables/${result.table_id}`)
      }
    },
  })

  const columns = [
    {
      title: '表名',
      dataIndex: 'name',
      key: 'name',
      render: (name: string, record: TableSummary) => (
        <a onClick={() => navigate(`/w/${wid}/tables/${record.id}`)} style={{ fontWeight: 500 }}>
          <TableOutlined style={{ marginRight: 8, color: '#3b82f6' }} />
          {name}
        </a>
      ),
    },
    {
      title: '描述',
      dataIndex: 'description',
      key: 'description',
      ellipsis: true,
      render: (d?: string) => d ? <Text type="secondary">{d}</Text> : <Text type="secondary" italic>—</Text>,
    },
    {
      title: '拥有者',
      dataIndex: 'owner',
      key: 'owner',
      width: 160,
      render: (owner?: { id: number | string; username: string } | null) => {
        if (!owner) {
          return <Text type="secondary">未指定</Text>
        }
        const isMe = user && String(owner.id) === String(user.id)
        return (
          <Space size={6}>
            <Avatar size="small" icon={<UserOutlined />} />
            <span>
              {owner.username}
              {isMe && <Tag color="red" style={{ marginLeft: 4, fontSize: 11, lineHeight: '16px' }}>我</Tag>}
            </span>
          </Space>
        )
      },
    },
    {
      title: '我的访问',
      dataIndex: 'my_access',
      key: 'my_access',
      width: 110,
      render: (access?: string) => {
        const key = access ?? 'none'
        const info = ACCESS_TAG[key] ?? ACCESS_TAG.none
        return <Tag color={info.color}>{info.label}</Tag>
      },
    },
    {
      title: '成员数',
      dataIndex: 'member_count',
      key: 'member_count',
      width: 90,
      align: 'right' as const,
      render: (n?: number) => (
        <Tooltip title="显式授予成员">
          <Badge
            count={n ?? 0}
            showZero
            overflowCount={99}
            color={(n ?? 0) > 0 ? 'var(--cn-brand-color)' : undefined}
          >
            <TeamOutlined style={{ fontSize: 16, color: 'var(--cn-text-muted)' }} />
          </Badge>
        </Tooltip>
      ),
    },
    {
      title: '字段',
      dataIndex: 'field_count',
      key: 'field_count',
      width: 70,
      align: 'right' as const,
      render: (n?: number) => <Tag>{n ?? 0}</Tag>,
    },
    {
      title: '记录',
      dataIndex: 'record_count',
      key: 'record_count',
      width: 80,
      align: 'right' as const,
      render: (n?: number) => <Text>{n ?? 0}</Text>,
    },
    {
      title: '更新时间',
      dataIndex: 'updated_at',
      key: 'updated_at',
      width: 170,
      render: (t?: string) => t ? (
        <Text type="secondary">
          <ClockCircleOutlined style={{ marginRight: 4 }} />
          {new Date(t).toLocaleString()}
        </Text>
      ) : <Text type="secondary">—</Text>,
    },
    {
      title: '操作',
      key: 'actions',
      width: 110,
      render: (_: unknown, record: TableSummary) => (
        <Space size="small">
          <Tooltip title="打开">
            <Button
              type="text"
              size="small"
              icon={<LoginOutlined />}
              onClick={(e) => { e.stopPropagation(); navigate(`/w/${wid}/tables/${record.id}`) }}
              data-testid={`open-table-${record.id}`}
            />
          </Tooltip>
          <Dropdown
            menu={{
              items: [
                {
                  key: 'rename',
                  icon: <EditOutlined />,
                  label: '重命名/编辑',
                  onClick: () => { setEditOpen(record); editForm.setFieldsValue({ name: record.name, description: record.description }) },
                },
                {
                  key: 'copy',
                  icon: <CopyOutlined />,
                  label: '复制表',
                  children: [
                    {
                      key: 'copy-structure',
                      label: '仅复制表结构',
                      onClick: (e) => { e?.domEvent?.stopPropagation?.(); copy.mutate({ tid: record.id, mode: 'structure' }) },
                    },
                    {
                      key: 'copy-all',
                      label: '复制表结构 + 全部数据',
                      onClick: (e) => { e?.domEvent?.stopPropagation?.(); copy.mutate({ tid: record.id, mode: 'all' }) },
                    },
                  ],
                },
                { type: 'divider' },
                {
                  key: 'delete',
                  icon: <DeleteOutlined />,
                  label: '删除表',
                  danger: true,
                  onClick: (e) => {
                    e?.domEvent?.stopPropagation?.();
                    Modal.confirm({
                      title: `删除表「${record.name}」？`,
                      content: '表内所有记录和字段将被永久移除。',
                      okText: '删除',
                      okType: 'danger',
                      cancelText: '取消',
                      onOk: () => remove.mutate(record.id),
                    })
                  },
                },
              ],
            }}
          >
            <Tooltip title="更多操作">
              <Button
                type="text"
                size="small"
                icon={<MoreOutlined />}
                onClick={(e) => e.stopPropagation()}
                data-testid={`more-table-${record.id}`}
              />
            </Tooltip>
          </Dropdown>
        </Space>
      ),
    },
  ]

  return (
    <div style={{ padding: 24 }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 24 }}>
        <div>
          <Title level={3} style={{ margin: 0 }}>
            {workspace?.name ? `${workspace.name} · 数据资产` : '数据资产目录'}
          </Title>
          <Text type="secondary">
            {workspace?.description || '管理当前工作区的所有数据表'}
          </Text>
        </div>
        <Space>
          <Button
            icon={<SettingOutlined />}
            data-testid="workspace-settings-link"
            onClick={() => navigate(`/w/${wid}/settings`)}
          >
            工作区设置
          </Button>
          <Upload
            accept=".csv"
            showUploadList={false}
            beforeUpload={(file) => { csvCreate.mutate(file as File); return false }}
          >
            <Button icon={<UploadOutlined />} loading={csvCreate.isPending}>
              CSV 建表
            </Button>
          </Upload>
          <Button
            icon={<ApiOutlined />}
            onClick={() => setApiImportOpen(true)}
            data-testid="api-import-entry"
          >
            API 建表
          </Button>
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => setCreateOpen(true)}
            style={{ backgroundColor: '#3b82f6', borderColor: '#3b82f6' }}
          >
            新建表
          </Button>
        </Space>
      </div>

      {/* Filter Segmented */}
      <div style={{ marginBottom: 12, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Space>
          <Segmented<AccessFilter>
            value={filter}
            onChange={(v) => setFilter(v as AccessFilter)}
            options={[
              { label: '全部', value: 'all' },
              { label: '我拥有的', value: 'owner' },
              { label: '我可编辑的', value: 'write' },
              { label: '我可读的', value: 'read' },
            ]}
          />
          <Text type="secondary" style={{ marginLeft: 8 }}>
            共 {filteredTables.length} / {tables.length} 张表
          </Text>
        </Space>
      </div>

      {/* Table 列表 */}
      <Table
        size="middle"
        loading={isLoading}
        rowKey="id"
        columns={columns}
        dataSource={filteredTables}
        pagination={false}
        onRow={(record) => ({
          onClick: () => navigate(`/w/${wid}/tables/${record.id}`),
          style: { cursor: 'pointer' },
        })}
        locale={{
          emptyText: (
            <Empty
              description={
                <span>
                  {filter !== 'all' ? '当前筛选条件下没有表' : (
                    <>
                      还没有表 —— 点击右侧 <Text strong>&quot;新建表&quot;</Text> 或 <Text strong>&quot;CSV 建表&quot;</Text> 开始
                    </>
                  )}
                </span>
              }
            />
          ),
        }}
      />

      {/* 创建 Modal */}
      <Modal
        title="新建表"
        open={createOpen}
        onCancel={() => { setCreateOpen(false); form.resetFields() }}
        onOk={() => form.submit()}
        confirmLoading={create.isPending}
        okText="创建"
        cancelText="取消"
      >
        <Form
          form={form}
          layout="vertical"
          preserve={false}
          onFinish={(v) => create.mutate(v)}
        >
          <Form.Item
            name="name"
            label="表名"
            rules={[
              { required: true, message: '请输入表名' },
              { max: 64, message: '表名不超过 64 字符' },
            ]}
          >
            <Input autoFocus placeholder="例如：客户信息、订单记录" maxLength={64} showCount />
          </Form.Item>
          <Form.Item name="description" label="描述（可选）">
            <Input.TextArea rows={2} placeholder="简要说明这张表的用途" maxLength={255} showCount />
          </Form.Item>
        </Form>
      </Modal>

      {/* 编辑表 Modal */}
      <Modal
        title="编辑表"
        open={!!editOpen}
        onCancel={() => { setEditOpen(null); editForm.resetFields() }}
        onOk={() => editForm.submit()}
        confirmLoading={update.isPending}
        okText="保存"
        cancelText="取消"
      >
        <Form
          form={editForm}
          layout="vertical"
          preserve={false}
          onFinish={(v) => {
            if (editOpen) {
              update.mutate({ tid: editOpen.id, data: v })
            }
          }}
        >
          <Form.Item
            name="name"
            label="表名"
            rules={[
              { required: true, message: '请输入表名' },
              { max: 64, message: '表名不超过 64 字符' },
            ]}
          >
            <Input maxLength={64} showCount />
          </Form.Item>
          <Form.Item name="description" label="描述（可选）">
            <Input.TextArea rows={2} maxLength={255} showCount />
          </Form.Item>
        </Form>
      </Modal>

      {/* API 建表 Dialog（建表模式） */}
      <Suspense fallback={null}>
        <ApiImportDialog
          open={apiImportOpen}
          wid={wid!}
          onClose={() => setApiImportOpen(false)}
          onSuccess={(res) => {
            if (res.table_id) {
              navigate(`/w/${wid}/tables/${res.table_id}`)
            }
          }}
        />
      </Suspense>
    </div>
  )
}
