import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  Button, Card, Col, Empty, Input, Modal, Popconfirm, Row, Space, Spin,
  Tag, Typography, message,
} from 'antd'
import { DeleteOutlined, PlusOutlined, RightOutlined, ApartmentOutlined } from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { workflowApi } from '@/api'
import type { WorkflowCreate } from '@/api'

const { Text, Title } = Typography

export default function WorkflowListPage() {
  const { wid } = useParams<{ wid: string }>()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [modalOpen, setModalOpen] = useState(false)
  const [name, setName] = useState('')
  const [desc, setDesc] = useState('')

  const { data, isLoading } = useQuery({
    queryKey: ['workflows', wid],
    queryFn: () => workflowApi.list(wid!),
    enabled: !!wid,
  })

  const createMut = useMutation({
    mutationFn: (payload: WorkflowCreate) => workflowApi.create(wid!, payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['workflows', wid] })
      setModalOpen(false)
      setName(''); setDesc('')
      message.success('工作流已创建')
    },
  })

  const deleteMut = useMutation({
    mutationFn: (fwid: number | string) => workflowApi.remove(wid!, fwid),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['workflows', wid] })
      message.success('工作流已删除')
    },
  })

  if (isLoading) return <div style={{ padding: 48, textAlign: 'center' }}><Spin /></div>

  return (
    <div style={{ padding: 24 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 24 }}>
        <Space>
          <ApartmentOutlined style={{ fontSize: 24, color: '#3b82f6' }} />
          <Title level={3} style={{ margin: 0 }}>业务工作流</Title>
        </Space>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setModalOpen(true)}>
          新建工作流
        </Button>
      </div>

      {!data || data.length === 0 ? (
        <Empty
          description="还没有工作流，点击右上角新建"
          image={Empty.PRESENTED_IMAGE_SIMPLE}
        />
      ) : (
        <Row gutter={[16, 16]}>
          {data.map(wf => (
            <Col xs={24} sm={12} lg={8} key={wf.id}>
              <Card
                hoverable
                styles={{ body: { padding: 16 } }}
                onClick={() => navigate(`/w/${wid}/workflows/${wf.id}`)}
                actions={[
                  <Popconfirm
                    key="del"
                    title="删除工作流？"
                    description="删除后无法恢复"
                    okText="删除"
                    cancelText="取消"
                    okButtonProps={{ danger: true }}
                    onConfirm={(e) => { e?.stopPropagation(); deleteMut.mutate(wf.id) }}
                  >
                    <Button
                      danger type="text" size="small" icon={<DeleteOutlined />}
                      onClick={(e) => e.stopPropagation()}
                      loading={deleteMut.isPending}
                    >删除</Button>
                  </Popconfirm>,
                  <Button
                    key="enter"
                    type="link" size="small"
                    icon={<RightOutlined />}
                    onClick={(e) => { e.stopPropagation(); navigate(`/w/${wid}/workflows/${wf.id}`) }}
                  >进入编辑</Button>,
                ]}
              >
                <Space direction="vertical" size={4} style={{ width: '100%' }}>
                  <Text strong style={{ fontSize: 16 }}>{wf.name}</Text>
                  {wf.description && (
                    <Text type="secondary" style={{ fontSize: 13 }} ellipsis={{ tooltip: wf.description }}>
                      {wf.description}
                    </Text>
                  )}
                  <Space size={[4, 4]} wrap>
                    <Tag color="blue">节点 {wf.node_count}</Tag>
                    {wf.updated_at && (
                      <Tag color="default" style={{ fontSize: 11 }}>
                        更新于 {new Date(wf.updated_at).toLocaleString()}
                      </Tag>
                    )}
                  </Space>
                </Space>
              </Card>
            </Col>
          ))}
        </Row>
      )}

      <Modal
        title="新建工作流"
        open={modalOpen}
        onCancel={() => { setModalOpen(false); setName(''); setDesc('') }}
        confirmLoading={createMut.isPending}
        onOk={() => {
          if (!name.trim()) { message.warning('请输入名称'); return }
          createMut.mutate({ name: name.trim(), description: desc })
        }}
      >
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <div>
            <div style={{ marginBottom: 4 }}>名称</div>
            <Input placeholder="如：采购管理流程" value={name} onChange={e => setName(e.target.value)} />
          </div>
          <div>
            <div style={{ marginBottom: 4 }}>描述（可选）</div>
            <Input.TextArea
              rows={3}
              placeholder="描述这个业务流程的用途"
              value={desc}
              onChange={e => setDesc(e.target.value)}
            />
          </div>
        </div>
      </Modal>
    </div>
  )
}
