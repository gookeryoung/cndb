/** 工作区表列表页 — 支持创建/重命名/复制/删除 + CSV 自动建表 + API 自动建表. */

import React, { Suspense, lazy } from 'react'
import { Button, Modal, Form, Input, Table, Typography, Empty, message, Space, Tag, Upload, Dropdown } from 'antd'
import { PlusOutlined, TableOutlined, DeleteOutlined, ClockCircleOutlined, CopyOutlined, EditOutlined, UploadOutlined, SettingOutlined, ApiOutlined } from '@ant-design/icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useParams, useNavigate } from 'react-router-dom'
import { tableApi, workspaceApi, importApi } from '@/api'
import type { TableSummary, TableUpdate } from '@/api'

const ApiImportDialog = lazy(() => import('@/pages/modals/ApiImportDialog'))

const { Title, Text } = Typography

export default function TablesList() {
  const { wid } = useParams<{ wid: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [createOpen, setCreateOpen] = React.useState(false)
  const [editOpen, setEditOpen] = React.useState<TableSummary | null>(null)
  const [apiImportOpen, setApiImportOpen] = React.useState(false)
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
    mutationFn: (tid: number | string) => tableApi.copy(wid!, tid, false),
    onSuccess: (t) => {
      message.success(`已复制为 "${t.name}"`)
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
      title: '字段',
      dataIndex: 'field_count',
      key: 'field_count',
      width: 80,
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
      width: 180,
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
      width: 200,
      render: (_: unknown, record: TableSummary) => (
        <Space size="small">
          <a onClick={() => navigate(`/w/${wid}/tables/${record.id}`)}>打开</a>
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
                  label: '复制表结构',
                  onClick: (e) => { e?.domEvent?.stopPropagation?.(); copy.mutate(record.id) },
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
            <a onClick={(e) => e.stopPropagation()}>更多…</a>
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
            {workspace?.name ? `${workspace.name} · 表` : '表列表'}
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

      {/* Table 列表 */}
      <Table
        size="middle"
        loading={isLoading}
        rowKey="id"
        columns={columns}
        dataSource={tables}
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
                  还没有表 —— 点击右侧 <Text strong>&quot;新建表&quot;</Text> 或 <Text strong>&quot;CSV 建表&quot;</Text> 开始
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
