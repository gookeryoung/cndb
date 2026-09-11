import React from 'react'
import { Card, Row, Col, Typography, Button, Modal, Form, Input, Tag, Empty, message, Space } from 'antd'
import { PlusOutlined, PushpinOutlined, TeamOutlined, TableOutlined } from '@ant-design/icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { workspaceApi } from '@/api'
import type { Workspace } from '@/api'

const { Title, Text } = Typography

export default function WorkspaceList() {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const [createOpen, setCreateOpen] = React.useState(false)
  const [form] = Form.useForm()

  const { data: workspaces = [], isLoading } = useQuery<Array<Workspace & { table_count?: number; member_count?: number }>>({
    queryKey: ['workspaces'],
    queryFn: () => workspaceApi.list(),
  })

  const create = useMutation({
    mutationFn: (v: { name: string; description?: string }) => workspaceApi.create(v),
    onSuccess: (w) => {
      message.success(`已创建 "${w.name}"`)
      queryClient.invalidateQueries({ queryKey: ['workspaces'] })
      setCreateOpen(false)
      form.resetFields()
      navigate(`/w/${w.id}/tables`)
    },
  })

  const pin = useMutation({
    mutationFn: (w: Workspace) => w.pinned ? workspaceApi.unpin(w.id) : workspaceApi.pin(w.id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['workspaces'] }),
  })

  const ordered = [...workspaces].sort((a, b) => (b.pinned ? 1 : 0) - (a.pinned ? 1 : 0))

  return (
    <div style={{ padding: 24 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <div>
          <Title level={3} style={{ margin: 0 }}>我的工作区</Title>
          <Text type="secondary">选择或创建一个工作区开始协作</Text>
        </div>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>
          新建工作区
        </Button>
      </div>

      {isLoading ? (
        <div style={{ textAlign: 'center', padding: 48 }}>加载中...</div>
      ) : ordered.length === 0 ? (
        <Empty description="还没有工作区，创建一个吧！" />
      ) : (
        <Row gutter={[16, 16]}>
          {ordered.map(w => (
            <Col xs={24} sm={12} md={8} lg={6} key={w.id}>
              <Card
                hoverable
                onClick={() => navigate(`/w/${w.id}/tables`)}
                actions={[
                  React.createElement(PushpinOutlined, {
                    key: 'pin',
                    onClick: (e: React.MouseEvent) => { e.stopPropagation(); pin.mutate(w) },
                    style: { color: w.pinned ? '#f59e0b' : undefined },
                  }),
                  React.createElement(TeamOutlined, { key: 'members' }),
                ]}
              >
                <div style={{ marginBottom: 8 }}>
                  {w.pinned && <Tag color="gold" style={{ marginRight: 8 }}>置顶</Tag>}
                  <Text strong style={{ fontSize: 16 }}>{w.name}</Text>
                </div>
                <Text type="secondary" ellipsis style={{ display: 'block', height: 40 }}>
                  {w.description || '暂无描述'}
                </Text>
                <div style={{ marginTop: 12, display: 'flex', gap: 12, color: '#6b7280', fontSize: 12 }}>
                  <span><TableOutlined /> {w.table_count ?? 0} 表</span>
                  <span><TeamOutlined /> {w.member_count ?? 1} 成员</span>
                </div>
              </Card>
            </Col>
          ))}
        </Row>
      )}

      <Modal
        title="新建工作区"
        open={createOpen}
        onCancel={() => { setCreateOpen(false); form.resetFields() }}
        onOk={() => form.submit()}
        confirmLoading={create.isPending}
        okText="创建"
      >
        <Form form={form} layout="vertical" onFinish={(v) => create.mutate(v)}>
          <Form.Item name="name" label="工作区名称" rules={[{ required: true, message: '请输入名称' }]}>
            <Input placeholder="例如：产品研发" />
          </Form.Item>
          <Form.Item name="description" label="描述（可选）">
            <Input.TextArea rows={3} placeholder="简单介绍一下这个工作区" />
          </Form.Item>
        </Form>
      </Modal>

      <Space style={{ display: 'none' }} />
    </div>
  )
}
