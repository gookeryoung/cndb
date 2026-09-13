/** 工作区列表页 — 卡片式布局，支持创建/设置/导入/导出/置顶/成员管理. */

import React, { useEffect, useState } from 'react'
import { Card, Row, Col, Typography, Button, Modal, Form, Input, Tag, Empty, message, Space, Dropdown } from 'antd'
import {
  PlusOutlined, PushpinOutlined, TeamOutlined, TableOutlined, EditOutlined, DeleteOutlined, MoreOutlined,
  DownloadOutlined, UploadOutlined, SettingOutlined, UserOutlined, ClockCircleOutlined, EyeOutlined,
  FileTextOutlined, CrownOutlined, GlobalOutlined, LockOutlined, SafetyCertificateOutlined,
} from '@ant-design/icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { workspaceApi } from '@/api'
import type { Workspace } from '@/api'
import WorkspaceSettingsModal from '@/pages/modals/WorkspaceSettingsModal'
import WorkspaceBackupDialog from '@/pages/modals/WorkspaceBackupDialog'

const { Title, Text } = Typography

/** 公开性图标 + 颜色映射 */
const VISIBILITY_META = {
  public: { icon: <GlobalOutlined />, color: 'green', label: '公开' },
  member: { icon: <SafetyCertificateOutlined />, color: 'blue', label: '成员可见' },
  private: { icon: <LockOutlined />, color: 'default', label: '私有' },
} as const

export default function WorkspaceList() {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const [createOpen, setCreateOpen] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState<Workspace | null>(null)
  const [backupOpen, setBackupOpen] = useState<Workspace | null>(null)
  const [form] = Form.useForm()

  type WSWithStats = Workspace & { table_count?: number; member_count?: number }

  const { data: workspaces = [], isLoading } = useQuery<WSWithStats[]>({
    queryKey: ['workspaces'],
    queryFn: () => workspaceApi.list(),
  })

  // 只有一个工作区时自动进入
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

  return (
    <div style={{ padding: 24 }} data-testid="workspace-list">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <div>
          <Title level={3} style={{ margin: 0 }}>我的工作区</Title>
          <Text type="secondary">选择或创建一个工作区开始协作</Text>
        </div>
        <Button
          type="primary"
          icon={<PlusOutlined />}
          onClick={() => setCreateOpen(true)}
          data-testid="create-workspace-btn"
        >
          新建工作区
        </Button>
      </div>

      {isLoading ? (
        <div style={{ textAlign: 'center', padding: 48 }}>加载中...</div>
      ) : ordered.length === 0 ? (
        <Empty description="还没有工作区，创建一个吧！" />
      ) : (
        <Row gutter={[16, 16]}>
          {ordered.map(w => {
            const vis = VISIBILITY_META[(w.visibility ?? 'member') as keyof typeof VISIBILITY_META] ?? VISIBILITY_META.member
            return (
              <Col xs={24} sm={12} md={8} lg={6} key={w.id}>
                <Card
                  hoverable
                  onClick={() => navigate(`/w/${w.id}/tables`)}
                  data-testid={`workspace-card-${w.id}`}
                  styles={{ body: { padding: 16 } }}
                  actions={[
                    <span
                      key="pin"
                      onClick={(e) => { e.stopPropagation(); pin.mutate(w) }}
                      style={{ cursor: 'pointer', color: w.pinned ? '#f59e0b' : undefined }}
                    ><PushpinOutlined /> {w.pinned ? '取消置顶' : '置顶'}</span>,
                    <span
                      key="backup"
                      onClick={(e) => { e.stopPropagation(); setBackupOpen(w) }}
                      style={{ cursor: 'pointer' }}
                      data-testid={`backup-btn-${w.id}`}
                    ><DownloadOutlined /> 备份</span>,
                    <span
                      key="settings"
                      onClick={(e) => { e.stopPropagation(); setSettingsOpen(w) }}
                      style={{ cursor: 'pointer' }}
                      data-testid={`settings-btn-${w.id}`}
                    ><SettingOutlined /> 设置</span>,
                  ]}
                >
                  {/* 头部：标签 + 公开性 */}
                  <div style={{ marginBottom: 8, display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                    <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', maxWidth: '70%' }}>
                      {w.pinned && <Tag color="gold" style={{ marginRight: 4 }}>置顶</Tag>}
                      {(w.tags ?? []).slice(0, 2).map(t => (
                        <Tag key={t} style={{ marginRight: 0 }}>{t}</Tag>
                      ))}
                    </div>
                    <Tag color={vis.color} icon={vis.icon}>{vis.label}</Tag>
                  </div>

                  {/* 标题 */}
                  <Text strong style={{ fontSize: 16, display: 'block', marginBottom: 4 }}>{w.name}</Text>

                  {/* 描述 */}
                  <Text type="secondary" ellipsis style={{ display: 'block', height: 40, fontSize: 13 }}>
                    {w.description || '暂无描述'}
                  </Text>

                  {/* 统计 + 允许编辑 */}
                  <div style={{ marginTop: 12, display: 'flex', gap: 16, color: '#6b7280', fontSize: 12 }}>
                    <span><TableOutlined /> {w.table_count ?? 0} 表</span>
                    <span><TeamOutlined /> {w.member_count ?? 1} 成员</span>
                  </div>
                  {w.allow_edit !== undefined && !w.allow_edit && (
                    <div style={{ marginTop: 4, fontSize: 12, color: '#f59e0b' }}>
                      <LockOutlined /> 编辑已关闭
                    </div>
                  )}
                </Card>
              </Col>
            )
          })}
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
        data-testid="create-workspace-modal"
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

      {/* 设置 Modal */}
      {settingsOpen && (
        <WorkspaceSettingsModal
          open={!!settingsOpen}
          wid={String(settingsOpen.id)}
          onClose={() => setSettingsOpen(null)}
          onUpdated={() => queryClient.invalidateQueries({ queryKey: ['workspaces'] })}
        />
      )}

      {/* 备份 Modal */}
      {backupOpen && (
        <WorkspaceBackupDialog
          open={!!backupOpen}
          wid={String(backupOpen.id)}
          workspaceName={backupOpen.name}
          onClose={() => setBackupOpen(null)}
          onImported={() => queryClient.invalidateQueries({ queryKey: ['workspaces'] })}
        />
      )}

      {/* 隐藏的删除按钮占位（保留旧逻辑的 fallback） */}
      <Space style={{ display: 'none' }}>
        {ordered.map(w => (
          <Dropdown
            key={`del-${w.id}`}
            menu={{
              items: [
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
            <span onClick={(e) => e.stopPropagation()} />
          </Dropdown>
        ))}
      </Space>
    </div>
  )
}
