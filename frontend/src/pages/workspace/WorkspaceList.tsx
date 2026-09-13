/** 工作区列表页 — 卡片式布局，支持创建/编辑/删除/置顶/成员管理. */

import React, { useEffect } from 'react'
import { Card, Row, Col, Typography, Button, Modal, Form, Input, Tag, Empty, message, Space, Dropdown } from 'antd'
import { PlusOutlined, PushpinOutlined, TeamOutlined, TableOutlined, EditOutlined, DeleteOutlined, MoreOutlined } from '@ant-design/icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { workspaceApi } from '@/api'
import type { Workspace, WorkspaceUpdate } from '@/api'
import MembersModal from '@/pages/modals/MembersModal'

const { Title, Text } = Typography

export default function WorkspaceList() {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const [createOpen, setCreateOpen] = React.useState(false)
  const [editOpen, setEditOpen] = React.useState<Workspace | null>(null)
  const [membersOpen, setMembersOpen] = React.useState<Workspace | null>(null)
  const [form] = Form.useForm()
  const [editForm] = Form.useForm()

  const { data: workspaces = [], isLoading } = useQuery<Array<Workspace & { table_count?: number; member_count?: number }>>({
    queryKey: ['workspaces'],
    queryFn: () => workspaceApi.list(),
  })

  // 只有一个工作区时自动进入，避免用户多一次点击
  useEffect(() => {
    if (!isLoading && workspaces.length === 1) {
      navigate(`/w/${workspaces[0].id}/tables`, { replace: true })
    }
  }, [isLoading, workspaces, navigate])

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

  const update = useMutation({
    mutationFn: ({ id, data }: { id: number | string; data: WorkspaceUpdate }) => workspaceApi.update(id, data),
    onSuccess: () => {
      message.success('工作区已更新')
      queryClient.invalidateQueries({ queryKey: ['workspaces'] })
      setEditOpen(null)
      editForm.resetFields()
    },
  })

  const remove = useMutation({
    mutationFn: (wid: number | string) => workspaceApi.remove(wid),
    onSuccess: () => {
      message.success('工作区已删除')
      queryClient.invalidateQueries({ queryKey: ['workspaces'] })
    },
  })

  const pin = useMutation({
    mutationFn: (w: Workspace) => workspaceApi.togglePin(w.id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['workspaces'] }),
  })

  const ordered = [...workspaces].sort((a, b) => (b.pinned ? 1 : 0) - (a.pinned ? 1 : 0))

  const openEdit = (w: Workspace) => {
    editForm.setFieldsValue({ name: w.name, description: w.description })
    setEditOpen(w)
  }

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
                  <span
                    key="pin"
                    onClick={(e) => { e.stopPropagation(); pin.mutate(w) }}
                    style={{ cursor: 'pointer', color: w.pinned ? '#f59e0b' : undefined }}
                  ><PushpinOutlined /> {w.pinned ? '取消置顶' : '置顶'}</span>,
                  <span
                    key="members"
                    onClick={(e) => { e.stopPropagation(); setMembersOpen(w) }}
                    style={{ cursor: 'pointer' }}
                  ><TeamOutlined /> 成员</span>,
                  <Dropdown
                    key="more"
                    menu={{
                      items: [
                        { key: 'edit', icon: <EditOutlined />, label: '编辑工作区', onClick: () => { /* stopPropagation by dropdown */ openEdit(w) } },
                        { type: 'divider' },
                        {
                          key: 'delete',
                          icon: <DeleteOutlined />,
                          label: '删除工作区',
                          danger: true,
                          onClick: () => {
                            Modal.confirm({
                              title: `删除工作区「${w.name}」？`,
                              content: '此操作将永久删除工作区下所有数据表和记录，无法恢复。',
                              okText: '确认删除',
                              okType: 'danger',
                              cancelText: '取消',
                              onOk: () => remove.mutate(w.id),
                            })
                          },
                        },
                      ],
                    }}
                    trigger={['click']}
                  >
                    <span onClick={(e) => e.stopPropagation()} style={{ cursor: 'pointer' }}><MoreOutlined /></span>
                  </Dropdown>,
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

      {/* 新建工作区 Modal */}
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

      {/* 编辑工作区 Modal */}
      <Modal
        title="编辑工作区"
        open={!!editOpen}
        onCancel={() => { setEditOpen(null); editForm.resetFields() }}
        onOk={() => editForm.submit()}
        confirmLoading={update.isPending}
        okText="保存"
      >
        <Form
          form={editForm}
          layout="vertical"
          onFinish={(v) => {
            if (editOpen) {
              update.mutate({ id: editOpen.id, data: v })
            }
          }}
        >
          <Form.Item name="name" label="工作区名称" rules={[{ required: true, message: '请输入名称' }]}>
            <Input />
          </Form.Item>
          <Form.Item name="description" label="描述（可选）">
            <Input.TextArea rows={3} />
          </Form.Item>
        </Form>
      </Modal>

      {/* 成员管理 Modal */}
      {membersOpen && (
        <MembersModal
          open={!!membersOpen}
          wid={String(membersOpen.id)}
          onClose={() => setMembersOpen(null)}
        />
      )}

      <Space style={{ display: 'none' }} />
    </div>
  )
}
