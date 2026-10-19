/** 工作区列表页 — 卡片式布局，支持创建/设置/导入/导出/置顶/成员管理/搜索. */

import { useMemo, useState } from 'react'
import { Card, Row, Col, Typography, Button, Modal, Form, Input, Select, Switch, Tag, Empty, App as AntApp, Upload, Alert, Progress, Skeleton } from 'antd'
import {
  PlusOutlined, PushpinOutlined, TeamOutlined, TableOutlined,
  DownloadOutlined, SettingOutlined, SearchOutlined,
  GlobalOutlined, LockOutlined, SafetyCertificateOutlined,
  UploadOutlined, InboxOutlined, FileTextOutlined, FolderOpenOutlined,
} from '@ant-design/icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { useResponsive } from '@/hooks/useResponsive'
import { workspaceApi } from '@/api'
import type { Workspace, WorkspaceRole, WorkspaceType, WorkspaceVisibility } from '@/api'
import { WORKSPACE_TYPE_HINT, WORKSPACE_TYPE_LABEL, WORKSPACE_TYPE_OPTIONS, workspaceLandingSegment } from '@/utils/workspaceType'
import WorkspaceSettingsModal from '@/pages/settings/WorkspaceSettingsModal'
import WorkspaceBackupDialog from '@/pages/settings/WorkspaceBackupDialog'

const { Title, Text } = Typography

/** 公开性图标 + 颜色映射 */
const VISIBILITY_META: Record<WorkspaceVisibility, { icon: React.ReactNode; color: string; label: string }> = {
  public: { icon: <GlobalOutlined />, color: 'green', label: '公开' },
  member: { icon: <SafetyCertificateOutlined />, color: 'blue', label: '成员可见' },
  private: { icon: <LockOutlined />, color: 'default', label: '私有' },
}

const ROLE_LABEL: Record<WorkspaceRole, string> = {
  owner: '所有者', editor: '编辑者', viewer: '查看者',
}

const ROLE_BADGE_COLOR: Record<WorkspaceRole, string> = {
  owner: 'gold', editor: 'cyan', viewer: 'default',
}

/** 工作区类型徽标配色：标识功能范围（非权限），与公开性色系区分 */
const TYPE_TAG_COLOR: Record<WorkspaceType, string> = {
  data_doc: 'geekblue', data: 'purple', doc: 'orange',
}

export default function WorkspaceList() {
  const { message } = AntApp.useApp()
  const { isMobile } = useResponsive()
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const [createOpen, setCreateOpen] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState<Workspace | null>(null)
  const [backupOpen, setBackupOpen] = useState<Workspace | null>(null)
  const [importOpen, setImportOpen] = useState(false)
  const [search, setSearch] = useState('')
  const [form] = Form.useForm()
  const [importForm] = Form.useForm()

  type WSWithStats = Workspace & {
    table_count?: number; member_count?: number;
    current_user_role?: WorkspaceRole | null;
  }

  const { data: workspaces = [], isLoading } = useQuery<WSWithStats[]>({
    queryKey: ['workspaces'],
    queryFn: () => workspaceApi.list(),
  })

  const create = useMutation({
    mutationFn: (v: {
      name: string; description?: string;
      visibility?: WorkspaceVisibility; tags?: string[]; allow_edit?: boolean;
      workspace_type?: WorkspaceType;
    }) => workspaceApi.create({
      name: v.name,
      description: v.description ?? '',
      visibility: v.visibility ?? 'member',
      tags: v.tags ?? [],
      allow_edit: v.allow_edit ?? true,
      workspace_type: v.workspace_type ?? 'data_doc',
    }),
    onSuccess: (w) => {
      message.success(`已创建 "${w.name}"`)
      setCreateOpen(false)
      form.resetFields()
      queryClient.invalidateQueries({ queryKey: ['workspaces'] })
      navigate(`/w/${w.id}/${workspaceLandingSegment(w.workspace_type)}`)
    },
    onError: (err) => message.error(err instanceof Error ? err.message : '创建工作区失败，请重试'),
  })

  const pin = useMutation({
    mutationFn: (w: Workspace) => workspaceApi.togglePin(w.id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['workspaces'] }),
    onError: (err) => message.error(err instanceof Error ? err.message : '置顶失败'),
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
    <div style={{ padding: isMobile ? 12 : 16 }} data-testid="workspace-list">
      {/* 工具栏 —— 移动端纵向堆叠：标题整行、搜索框占满、按钮均分，避免固定宽度导致横向溢出 */}
      <div
        data-testid="workspace-list-toolbar"
        style={{
          display: 'flex',
          flexDirection: isMobile ? 'column' : 'row',
          justifyContent: 'space-between',
          alignItems: isMobile ? 'stretch' : 'center',
          marginBottom: 16,
          flexWrap: 'wrap',
          gap: 12,
        }}
      >
        <div>
          <Title level={3} style={{ margin: 0 }}><FolderOpenOutlined style={{ marginRight: 8 }} />我的工作区</Title>
          <Text type="secondary">选择或创建一个工作区开始协作</Text>
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
          <Input.Search
            placeholder="搜索工作区名称/标签..."
            allowClear
            prefix={<SearchOutlined />}
            style={{ width: isMobile ? '100%' : 260 }}
            value={search}
            onChange={e => setSearch(e.target.value)}
          />
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => setCreateOpen(true)}
            style={isMobile ? { flex: 1 } : undefined}
            data-testid="create-workspace-btn"
          >
            新建工作区
          </Button>
          <Button
            icon={<UploadOutlined />}
            onClick={() => { importForm.resetFields(); setImportOpen(true) }}
            style={isMobile ? { flex: 1 } : undefined}
            data-testid="import-workspace-btn"
          >
            导入工作区
          </Button>
        </div>
      </div>

      {isLoading ? (
        /* 骨架屏占位 —— sr-only 文本保留给屏幕阅读器与既有测试断言 */
        <div data-testid="workspace-list-skeleton" role="status">
          <span style={{
            position: 'absolute', width: 1, height: 1, overflow: 'hidden',
            clip: 'rect(0 0 0 0)', whiteSpace: 'nowrap',
          }}>加载中...</span>
          <Row gutter={[16, 16]}>
            {Array.from({ length: 8 }).map((_, i) => (
              <Col xs={24} sm={12} md={8} lg={6} key={i}>
                <Card styles={{ body: { padding: 16 } }}>
                  <Skeleton active title={false} paragraph={{ rows: 3 }} />
                </Card>
              </Col>
            ))}
          </Row>
        </div>
      ) : filteredWorkspaces.length === 0 ? (
        <Empty description={search ? `没有匹配「${search}」的工作区` : '还没有工作区，创建一个吧！'} />
      ) : (
        <Row gutter={isMobile ? [12, 12] : [16, 16]}>
          {filteredWorkspaces.map((w, i) => {
            const vis = VISIBILITY_META[(w.visibility ?? 'member') as WorkspaceVisibility]
              ?? VISIBILITY_META.member
            const role = w.current_user_role ?? null
            return (
              <Col xs={24} sm={12} md={8} lg={6} key={w.id}>
                <Card
                  hoverable
                  className="cn-ws-card"
                  style={{ animationDelay: `${Math.min(i, 7) * 40}ms` }}
                  data-testid={`workspace-card-${w.id}`}
                  styles={{ body: { padding: isMobile ? 12 : 16 } }}
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
                  onClick={(e) => {
                    const target = e.target as HTMLElement
                    if (target.closest('.ant-card-actions')) return
                    navigate(`/w/${w.id}/${workspaceLandingSegment(w.workspace_type)}`)
                  }}
                >
                  {/* 头部：标签 + 公开性 + 角色 */}
                  <div style={{ marginBottom: isMobile ? 4 : 8, display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                    <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', maxWidth: '70%' }}>
                      {w.pinned && <Tag color="gold" style={{ marginRight: 4 }}>📌 置顶</Tag>}
                      <Tag color={TYPE_TAG_COLOR[w.workspace_type ?? 'data_doc']} style={{ marginRight: 0 }}>
                        {WORKSPACE_TYPE_LABEL[w.workspace_type ?? 'data_doc']}
                      </Tag>
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
                  <Text strong style={{ fontSize: 16, display: 'block', marginBottom: 2 }}>{w.name}</Text>

                  {/* 描述 */}
                  <Text type="secondary" ellipsis style={{ display: 'block', height: isMobile ? 32 : 36, fontSize: 13, lineHeight: '16px' }}>
                    {w.description || '暂无描述'}
                  </Text>

                  {/* 统计 + 编辑状态（始终占位，保证卡片高度一致） */}
                  <div style={{ marginTop: isMobile ? 8 : 10, display: 'flex', gap: 16, color: '#6b7280', fontSize: 12, alignItems: 'center' }}>
                    <span><TableOutlined /> {w.table_count ?? 0} 表</span>
                    <span><TeamOutlined /> {w.member_count ?? 1} 成员</span>
                    <span
                      style={{
                        marginLeft: 'auto',
                        color: '#f59e0b',
                        opacity: w.allow_edit !== undefined && !w.allow_edit ? 1 : 0,
                        transition: 'opacity 0.15s',
                      }}
                    ><LockOutlined /> 编辑已关闭</span>
                  </div>
                </Card>
              </Col>
            )
          })}
        </Row>
      )}

      {/* 新建工作区 Modal — 扩展字段；条件渲染避免 Form.useForm 在未挂载时触发 warning */}
      {createOpen && (
        <Modal
          title="新建工作区"
          open={createOpen}
          onCancel={() => { form.resetFields(); setCreateOpen(false) }}
          onOk={() => form.submit()}
          confirmLoading={create.isPending}
          okText="创建"
          data-testid="create-workspace-modal"
          width={isMobile ? 'calc(100vw - 32px)' : 520}
        >
          <Form
            form={form}
            layout="vertical"
            initialValues={{ visibility: 'member', allow_edit: true, workspace_type: 'data_doc' }}
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
            <Form.Item
              name="workspace_type"
              label="工作区类型"
              extra={WORKSPACE_TYPE_HINT[(form.getFieldValue('workspace_type') as WorkspaceType) ?? 'data_doc']}
            >
              <Select options={WORKSPACE_TYPE_OPTIONS} />
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
      )}

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
        />
      )}

      {/* 导入工作区 Modal — 从备份 JSON 创建全新工作区 */}
      {importOpen && <ImportWorkspaceModal
        open={importOpen}
        form={importForm}
        onCancel={() => setImportOpen(false)}
        onSuccess={(w) => {
          setImportOpen(false)
          queryClient.invalidateQueries({ queryKey: ['workspaces'] })
          message.success(`已导入工作区「${w.name}」`)
          navigate(`/w/${w.id}/${workspaceLandingSegment(w.workspace_type)}`)
        }}
        onError={(err) => message.error(err instanceof Error ? err.message : '导入失败')}
      />}
    </div>
  )
}

/** 允许导入的文件扩展名 */
const ACCEPTED_BACKUP_EXT = ['.json']

interface ImportWorkspaceModalProps {
  open: boolean
  form: ReturnType<typeof Form.useForm>[0]
  onCancel: () => void
  onSuccess: (w: Workspace) => void
  onError: (err: unknown) => void
}

function ImportWorkspaceModal({ open, form, onCancel, onSuccess, onError }: ImportWorkspaceModalProps) {
  const { isMobile } = useResponsive()
  const [importing, setImporting] = useState(false)
  const [importResult, setImportResult] = useState<{ tables: number; rows: number; views: number; documents: number } | null>(null)
  const [pendingJson, setPendingJson] = useState<Record<string, unknown> | null>(null)

  const reset = () => {
    setImportResult(null)
    setPendingJson(null)
    form.resetFields()
  }

  const beforeUpload = async (file: File) => {
    const name = file.name.toLowerCase()
    if (!ACCEPTED_BACKUP_EXT.some(ext => name.endsWith(ext))) {
      onError(new Error('仅支持 JSON 备份文件'))
      return false
    }
    try {
      const text = await file.text()
      const json = JSON.parse(text)
      setPendingJson(json)
      setImportResult(null)
      // 自动从备份文件里的 workspace.name 填充工作区名称
      const wsMeta = (json as Record<string, any>).workspace
      if (wsMeta?.name) {
        form.setFieldsValue({ name: wsMeta.name })
      }
    } catch {
      onError(new Error('文件内容不是有效的 JSON'))
    }
    // 返回 false 阻止 Upload 组件自动上传，手动在 onOk 里提交
    return false
  }

  const handleSubmit = async () => {
    if (!pendingJson) {
      onError(new Error('请先选择备份文件'))
      return
    }
    const raw: unknown = await form.validateFields().catch(() => null)
    if (!raw) return
    const values = raw as { name?: string }

    try {
      setImporting(true)
      const result = await workspaceApi.importFromBackup({
        name: values.name,
        json_data: pendingJson,
      })
      setImportResult({
        tables: result.imported_tables,
        rows: result.imported_rows,
        views: result.imported_views,
        documents: result.imported_documents ?? 0,
      })
      // 延迟一下让用户看到成功信息，然后跳转
      setTimeout(() => onSuccess(result.workspace), 800)
    } catch (err) {
      onError(err)
    } finally {
      setImporting(false)
    }
  }

  return (
    <Modal
      title="导入工作区"
      open={open}
      onCancel={() => { reset(); onCancel() }}
      onOk={handleSubmit}
      confirmLoading={importing}
      okText="开始导入"
      cancelText="取消"
      destroyOnHidden
      width={isMobile ? 'calc(100vw - 32px)' : 560}
    >
      <Alert
        type="info"
        showIcon
        message="从备份 JSON 创建一个全新的工作区"
        description="备份文件中的表结构、数据行和视图都会一并导入，当前用户自动成为该工作区所有者。"
        style={{ marginBottom: 16 }}
      />

      {!importResult && (
        <Form form={form} layout="vertical">
          <Form.Item name="name" label="工作区名称（可修改）">
            <Input placeholder="默认使用备份文件中的工作区名称" />
          </Form.Item>

          <div style={{ marginBottom: 16 }}>
            <Upload.Dragger
              multiple={false}
              accept={ACCEPTED_BACKUP_EXT.join(',')}
              beforeUpload={beforeUpload}
              disabled={importing}
              showUploadList={false}
            >
              <p className="ant-upload-drag-icon"><InboxOutlined /></p>
              <p className="ant-upload-text">点击或拖拽 JSON 备份文件到此处</p>
              <p className="ant-upload-hint">从其他工作区导出的 JSON 备份文件</p>
            </Upload.Dragger>
          </div>
        </Form>
      )}

      {importing && (
        <div style={{ textAlign: 'center', padding: '24px 0' }}>
          <Progress percent={100} status="active" showInfo={false} />
          <div style={{ marginTop: 8, color: '#64748b' }}>正在导入，请稍候...</div>
        </div>
      )}

      {importResult && !importing && (
        <div style={{
          padding: 16,
          background: 'color-mix(in srgb, #22c55e 10%, var(--cn-bg-container))',
          borderRadius: 8,
          textAlign: 'center',
        }}>
          <FileTextOutlined style={{ color: '#22c55e', fontSize: 20 }} />
          <span style={{ marginLeft: 8, color: '#15803d' }}>
            导入完成：{importResult.tables} 表 / {importResult.rows} 行 / {importResult.views} 视图{importResult.documents ? ` / ${importResult.documents} 文档` : ''}
          </span>
        </div>
      )}
    </Modal>
  )
}
