/** 工作区列表页 — 卡片式布局，支持创建/设置/导入/导出/置顶/成员管理/搜索. */

import { useEffect, useMemo, useState } from 'react'
import { Card, Row, Col, Typography, Button, Modal, Form, Input, Select, Switch, Tag, Empty, message } from 'antd'
import {
  PlusOutlined, PushpinOutlined, TeamOutlined, TableOutlined,
  DownloadOutlined, SettingOutlined, SearchOutlined, FullscreenOutlined,
  GlobalOutlined, LockOutlined, SafetyCertificateOutlined,
} from '@ant-design/icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { workspaceApi } from '@/api'
import type { Workspace, WorkspaceRole, WorkspaceVisibility } from '@/api'
import WorkspaceSettingsModal from '@/pages/modals/WorkspaceSettingsModal'
import WorkspaceBackupDialog from '@/pages/modals/WorkspaceBackupDialog'

const { Title, Text } = Typography

/** 公开性图标 + 颜色映射 */
const VISIBILITY_META: Record<WorkspaceVisibility, { icon: React.ReactNode; color: string; label: string }> = {
  public: { icon: <GlobalOutlined />, color: 'green', label: '公开' },
  member: { icon: <SafetyCertificateOutlined />, color: 'blue', label: '成员可见' },
  private: { icon: <LockOutlined />, color: 'default', label: '私有' },
}

const ROLE_LABEL: Record<WorkspaceRole, string> = {
  owner: '所有者', admin: '管理员', editor: '编辑者', viewer: '查看者',
}

const ROLE_BADGE_COLOR: Record<WorkspaceRole, string> = {
  owner: 'gold', admin: 'geekblue', editor: 'cyan', viewer: 'default',
}

export default function WorkspaceList() {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const [createOpen, setCreateOpen] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState<Workspace | null>(null)
  const [backupOpen, setBackupOpen] = useState<Workspace | null>(null)
  const [search, setSearch] = useState('')
  const [form] = Form.useForm()

  type WSWithStats = Workspace & {
    table_count?: number; member_count?: number;
    current_user_role?: WorkspaceRole | null;
  }

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
    mutationFn: (v: {
      name: string; description?: string;
      visibility?: WorkspaceVisibility; tags?: string[]; allow_edit?: boolean;
    }) => workspaceApi.create({
      name: v.name,
      description: v.description ?? '',
      visibility: v.visibility ?? 'member',
      tags: v.tags ?? [],
      allow_edit: v.allow_edit ?? true,
    }),
    onSuccess: (w) => {
      message.success(`已创建 "${w.name}"`)
      queryClient.invalidateQueries({ queryKey: ['workspaces'] })
      setCreateOpen(false)
      form.resetFields()
      navigate(`/w/${w.id}/tables`)
    },
  })

  const pin = useMutation({
    mutationFn: (w: Workspace) => workspaceApi.togglePin(w.id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['workspaces'] }),
  })

  // 排序 + 搜索过滤
  const filteredWorkspaces = useMemo(() => {
    const ordered = [...workspaces].sort(
      (a, b) => (b.pinned ? 1 : 0) - (a.pinned ? 1 : 0) || Number(a.id) - Number(b.id),
    )
    const q = search.trim().toLowerCase()
    if (!q) return ordered
    return ordered.filter(w =>
      (w.name ?? '').toLowerCase().includes(q) ||
      (w.description ?? '').toLowerCase().includes(q) ||
      (w.tags ?? []).some(t => t.toLowerCase().includes(q)),
    )
  }, [workspaces, search])

  return (
    <div style={{ padding: 24 }} data-testid="workspace-list">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24, flexWrap: 'wrap', gap: 12 }}>
        <div>
          <Title level={3} style={{ margin: 0 }}>我的工作区</Title>
          <Text type="secondary">选择或创建一个工作区开始协作</Text>
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <Input.Search
            placeholder="搜索工作区名称/标签..."
            allowClear
            prefix={<SearchOutlined />}
            style={{ width: 260 }}
            value={search}
            onChange={e => setSearch(e.target.value)}
          />
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => setCreateOpen(true)}
            data-testid="create-workspace-btn"
          >
            新建工作区
          </Button>
        </div>
      </div>

      {isLoading ? (
        <div style={{ textAlign: 'center', padding: 48 }}>加载中...</div>
      ) : filteredWorkspaces.length === 0 ? (
        <Empty description={search ? `没有匹配「${search}」的工作区` : '还没有工作区，创建一个吧！'} />
      ) : (
        <Row gutter={[16, 16]}>
          {filteredWorkspaces.map(w => {
            const vis = VISIBILITY_META[(w.visibility ?? 'member') as WorkspaceVisibility]
              ?? VISIBILITY_META.member
            const role = w.current_user_role ?? null
            return (
              <Col xs={24} sm={12} md={8} lg={6} key={w.id}>
                <Card
                  hoverable
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
                    <span
                      key="full-page"
                      onClick={(e) => { e.stopPropagation(); navigate(`/w/${w.id}/settings`) }}
                      style={{ cursor: 'pointer' }}
                      data-testid={`settings-page-btn-${w.id}`}
                    ><FullscreenOutlined /> 完整页面</span>,
                  ]}
                  onClick={(e) => {
                    const target = e.target as HTMLElement
                    if (target.closest('.ant-card-actions')) return
                    navigate(`/w/${w.id}/tables`)
                  }}
                >
                  {/* 头部：标签 + 公开性 + 角色 */}
                  <div style={{ marginBottom: 8, display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                    <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', maxWidth: '70%' }}>
                      {w.pinned && <Tag color="gold" style={{ marginRight: 4 }}>📌 置顶</Tag>}
                      {(w.tags ?? []).slice(0, 2).map(t => (
                        <Tag key={t} style={{ marginRight: 0 }}>{t}</Tag>
                      ))}
                    </div>
                    <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
                      {role && (
                        <Tag color={ROLE_BADGE_COLOR[role]} style={{ marginRight: 0, fontSize: 11 }}>
                          {ROLE_LABEL[role]}
                        </Tag>
                      )}
                      <Tag color={vis.color} icon={vis.icon}>{vis.label}</Tag>
                    </div>
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

      {/* 新建工作区 Modal — 扩展字段 */}
      <Modal
        title="新建工作区"
        open={createOpen}
        onCancel={() => { setCreateOpen(false); form.resetFields() }}
        onOk={() => form.submit()}
        confirmLoading={create.isPending}
        okText="创建"
        data-testid="create-workspace-modal"
        width={520}
      >
        <Form
          form={form}
          layout="vertical"
          initialValues={{ visibility: 'member', allow_edit: true }}
          onFinish={(v) => {
            const tagsStr = (v.tags as string) || ''
            create.mutate({
              ...v,
              tags: tagsStr.split(/[,，]/).map(s => s.trim()).filter(Boolean),
            })
          }}
        >
          <Form.Item name="name" label="工作区名称" rules={[{ required: true, message: '请输入名称' }]}>
            <Input placeholder="例如：产品研发" />
          </Form.Item>
          <Form.Item name="description" label="描述（可选）">
            <Input.TextArea rows={2} placeholder="简单介绍一下这个工作区" />
          </Form.Item>
          <Form.Item name="visibility" label="公开性">
            <Select
              options={[
                { value: 'public', label: '公开（任何人可读）' },
                { value: 'member', label: '成员可见（推荐）' },
                { value: 'private', label: '私有（仅所有者/管理员）' },
              ]}
            />
          </Form.Item>
          <Form.Item name="tags" label="标签（逗号分隔，可选）">
            <Input placeholder="例如：研发, 产品, 核心业务" />
          </Form.Item>
          <Form.Item name="allow_edit" label="允许成员编辑数据" valuePropName="checked">
            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <Switch />
              <span style={{ color: '#64748b', fontSize: 13 }}>
                {form.getFieldValue('allow_edit') !== false ? '已开启' : '已关闭（仅所有者可编辑）'}
              </span>
            </div>
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
    </div>
  )
}
