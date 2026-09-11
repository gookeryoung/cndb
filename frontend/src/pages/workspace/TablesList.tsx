import React from 'react'
import { Button, Modal, Form, Input, Table, Typography, Empty, message, Space, Popconfirm, Tag } from 'antd'
import { PlusOutlined, TableOutlined, DeleteOutlined, ClockCircleOutlined } from '@ant-design/icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useParams, useNavigate } from 'react-router-dom'
import { tableApi, workspaceApi } from '@/api'
import type { TableSummary } from '@/api'

const { Title, Text } = Typography

export default function TablesList() {
  const { wid } = useParams<{ wid: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [createOpen, setCreateOpen] = React.useState(false)
  const [form] = Form.useForm()

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

  const remove = useMutation({
    mutationFn: (tid: number | string) => tableApi.remove(wid!, tid),
    onSuccess: () => {
      message.success('已删除')
      queryClient.invalidateQueries({ queryKey: ['workspaces', wid, 'tables'] })
      queryClient.invalidateQueries({ queryKey: ['workspaces', wid] })
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
      width: 120,
      render: (_: unknown, record: TableSummary) => (
        <Space size="small">
          <a onClick={() => navigate(`/w/${wid}/tables/${record.id}`)}>打开</a>
          <Popconfirm
            title="确认删除该表？"
            description="表内所有记录和字段将被永久移除"
            okText="删除"
            okButtonProps={{ danger: true }}
            cancelText="取消"
            onConfirm={() => remove.mutate(record.id)}
          >
            <a style={{ color: '#ef4444' }}><DeleteOutlined /> 删除</a>
          </Popconfirm>
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
        <Button
          type="primary"
          icon={<PlusOutlined />}
          onClick={() => setCreateOpen(true)}
          style={{ backgroundColor: '#3b82f6', borderColor: '#3b82f6' }}
        >
          新建表
        </Button>
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
                  还没有表 —— 点击右侧 <Text strong>"新建表"</Text> 开始
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
    </div>
  )
}
