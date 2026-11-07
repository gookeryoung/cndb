/** 工作区模板中心（需求 0094 / 0120）：模板列表 / 结构化预览 / 编辑与影响预览.
 *
 * 布局对齐质量检查与修改申请页：cn-page 紧凑页头 + cn-qc-split 双栏。
 * 左栏为模板清单（按「内置模板 / 自定义模板」分组，选中项高亮），
 * 右栏为选中模板的元信息与结构化详情（流程阶段 / 表单 / 端到端流程 / 文档规则），
 * 编辑、复制、导出、删除等操作收敛到右栏方盒标题条，避免左栏行内按钮过密。
 */

import { useMemo, useState } from 'react'
import {
  Alert, App as AntApp, Button, Collapse, Descriptions, Empty, Input, List, Popconfirm,
  Space, Spin, Table, Tabs, Tag, Timeline, Typography,
} from 'antd'
import {
  AppstoreOutlined, PlusOutlined, EditOutlined, DeleteOutlined, CopyOutlined,
  ApartmentOutlined, FileTextOutlined, TableOutlined, CheckCircleOutlined,
  ClockCircleOutlined, ImportOutlined, ExportOutlined, UnorderedListOutlined,
} from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import SectionBox from '@/components/SectionBox'
import { workspaceTemplateApi } from '@/api'
import type { TemplateSpecForm, WorkspaceTemplate } from '@/api'
import TemplateEditorModal from './TemplateEditorModal'
import TemplateImportModal from './TemplateImportModal'
import { formatDateTime } from '@/utils/datetime'

const { Text, Paragraph } = Typography

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 0)
}

function FormDetail({ form }: { form: TemplateSpecForm }) {
  return (
    <div>
      <Paragraph type="secondary" style={{ marginBottom: 8 }}>{form.description || '—'}</Paragraph>
      <Table
        size="small"
        rowKey="name"
        pagination={false}
        dataSource={form.fields}
        columns={[
          { title: '字段', dataIndex: 'name' },
          { title: '类型', dataIndex: 'type', width: 120 },
          {
            title: '必填',
            dataIndex: 'required',
            width: 70,
            render: (v: boolean) => (v ? <Tag color="red">必填</Tag> : <Text type="secondary">否</Text>),
          },
        ]}
      />
    </div>
  )
}

function TemplateDetail({ template }: { template: WorkspaceTemplate }) {
  const spec = template.spec
  const stageNames = useMemo(() => {
    const forms = new Map(spec.forms.map(f => [f.key, f.name]))
    const docs = new Map(spec.documents.map(d => [d.key, d.title]))
    return { forms, docs }
  }, [spec])

  const stageItems = spec.stages.map(stage => ({
    color: stage.order === 1 ? 'blue' : 'gray',
    dot: stage.order === 1 ? <CheckCircleOutlined /> : <ClockCircleOutlined />,
    children: (
      <div data-testid={`template-stage-${stage.key}`}>
        <Space>
          <Text strong>阶段 {stage.order} · {stage.name}</Text>
          <Tag>{stage.forms.length} 表单</Tag>
          <Tag>{stage.documents.length} 文档规则</Tag>
        </Space>
        <div style={{ color: 'var(--cn-text-secondary)', fontSize: 'var(--cn-text-sm)', marginTop: 2 }}>{stage.description || '—'}</div>
        <div style={{ marginTop: 4, fontSize: 'var(--cn-text-sm)' }}>
          表单：{stage.forms.map(k => stageNames.forms.get(k) ?? k).join('、') || '—'}
        </div>
        <div style={{ fontSize: 'var(--cn-text-sm)' }}>
          文档：{stage.documents.map(k => stageNames.docs.get(k) ?? k).join('、') || '—'}
        </div>
      </div>
    ),
  }))

  return (
    <Tabs
      size="small"
      items={[
        {
          key: 'stages',
          label: <span><ApartmentOutlined /> 流程阶段</span>,
          children: spec.stages.length ? <Timeline items={stageItems} /> : <Empty />,
        },
        {
          key: 'forms',
          label: <span><TableOutlined /> 表单（{spec.forms.length}）</span>,
          children: spec.forms.length ? (
            <Collapse
              size="small"
              items={spec.forms.map(form => ({
                key: form.key,
                label: <span>{form.name} <Text type="secondary">· {form.fields.length} 个字段</Text></span>,
                children: <FormDetail form={form} />,
              }))}
            />
          ) : <Empty />,
        },
        {
          key: 'flows',
          label: <span><ApartmentOutlined /> 端到端流程（{spec.flows?.length ?? 0}）</span>,
          children: (spec.flows?.length ?? 0) ? (
            <Collapse
              size="small"
              items={(spec.flows ?? []).map(flow => ({
                key: flow.key,
                label: <span>{flow.name} <Text type="secondary">· {flow.steps.length} 步</Text></span>,
                children: (
                  <div>
                    <Paragraph type="secondary" style={{ marginBottom: 8 }}>{flow.description || '—'}</Paragraph>
                    <Timeline
                      items={flow.steps.map((step, index) => ({
                        color: step.form ? 'blue' : 'gray',
                        children: (
                          <div>
                            <Text strong>步骤 {index + 1} · {step.name}</Text>
                            <div style={{ fontSize: 'var(--cn-text-xs)', color: 'var(--cn-text-secondary)' }}>
                              {step.form ? `表单：${spec.forms.find(f => f.key === step.form)?.name ?? step.form}` : '审批 / 确认节点'}
                              {step.documents?.length ? ` · 文档：${step.documents.join('、')}` : ''}
                            </div>
                            {step.description && <div style={{ fontSize: 'var(--cn-text-xs)' }}>{step.description}</div>}
                          </div>
                        ),
                      }))}
                    />
                  </div>
                ),
              }))}
            />
          ) : <Empty description="未配置端到端流程（旧模板由阶段自动派生）" />,
        },
        {
          key: 'documents',
          label: <span><FileTextOutlined /> 文档规则（{spec.documents.length}）</span>,
          children: spec.documents.length ? (
            <List
              size="small"
              dataSource={spec.documents}
              renderItem={doc => (
                <List.Item>
                  <List.Item.Meta
                    title={<Space>{doc.title}{doc.required !== false ? <Tag color="red">必需</Tag> : <Tag>可选</Tag>}</Space>}
                    description={doc.naming || '未设置命名规则'}
                  />
                </List.Item>
              )}
            />
          ) : <Empty />,
        },
      ]}
    />
  )
}

/** 左栏单行：模板名 + 版本 / 分类标签 + 规模摘要（选中态由 cn-qc-row--active 绘制） */
function TemplateRow({
  template, active, onClick,
}: {
  template: WorkspaceTemplate
  active: boolean
  onClick: () => void
}) {
  const { counts } = template
  const summary = [
    `${counts.stage_count} 阶段`,
    `${counts.form_count} 表单`,
    `${counts.document_rule_count} 文档规则`,
    counts.flow_count ? `${counts.flow_count} 流程` : '',
  ].filter(Boolean).join(' / ')
  return (
    <button
      type="button"
      role="option"
      aria-selected={active}
      className={[
        'cn-cr-side-item',
        'cn-cr-group-item',
        'cn-qc-row',
        'cn-qc-row--selectable',
        active ? 'cn-qc-row--active' : '',
      ].filter(Boolean).join(' ')}
      data-testid={`template-item-${template.id}`}
      onClick={onClick}
    >
      <span className="cn-cr-side-main">
        <span className="cn-cr-side-title">
          <Text strong>{template.name}</Text>
          <Tag color="blue">v{template.version}</Tag>
          {template.category && <Tag>{template.category}</Tag>}
        </span>
        <span className="cn-cr-side-preview">{summary}</span>
      </span>
    </button>
  )
}

export default function TemplatesPage() {
  const { message } = AntApp.useApp()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [search, setSearch] = useState('')
  const [editorOpen, setEditorOpen] = useState(false)
  const [editing, setEditing] = useState<WorkspaceTemplate | null>(null)
  const [seed, setSeed] = useState<WorkspaceTemplate | null>(null)
  const [importOpen, setImportOpen] = useState(false)
  const [selectedId, setSelectedId] = useState<string | null>(null)

  const { data: templates = [], isLoading, error } = useQuery({
    queryKey: ['workspace-templates', search],
    queryFn: () => workspaceTemplateApi.list(search.trim() || undefined),
  })

  const grouped = useMemo(() => {
    const builtin = templates.filter(t => t.is_builtin)
    const custom = templates.filter(t => !t.is_builtin)
    return { builtin, custom }
  }, [templates])

  // 选中项被删除 / 搜索过滤后回落到清单第一条（内置优先，与接口顺序一致）
  const selected = useMemo(() => (
    templates.find(t => String(t.id) === selectedId) ?? templates[0] ?? null
  ), [templates, selectedId])

  const remove = useMutation({
    mutationFn: (id: number) => workspaceTemplateApi.remove(id),
    onSuccess: () => {
      message.success('模板已删除')
      setSelectedId(null)
      queryClient.invalidateQueries({ queryKey: ['workspace-templates'] })
    },
    onError: (err) => message.error(err instanceof Error ? err.message : '删除失败'),
  })

  const exportTemplate = useMutation({
    mutationFn: (t: WorkspaceTemplate) => workspaceTemplateApi.exportFile(t.id),
    onSuccess: ({ blob, filename }) => {
      downloadBlob(blob, filename)
      message.success('模板已导出')
    },
    onError: (err) => message.error(err instanceof Error ? err.message : '导出失败'),
  })

  const openCreate = () => { setEditing(null); setSeed(null); setEditorOpen(true) }
  const openEdit = (t: WorkspaceTemplate) => { setEditing(t); setSeed(null); setEditorOpen(true) }
  const openClone = (t: WorkspaceTemplate) => { setEditing(null); setSeed(t); setEditorOpen(true) }

  const renderGroup = (title: string, items: WorkspaceTemplate[]) => {
    if (!items.length) return null
    return (
      <div key={title} role="group" aria-label={title}>
        <div className="cn-tpl-group-label">{title}（{items.length}）</div>
        {items.map(t => (
          <TemplateRow
            key={t.id}
            template={t}
            active={selected != null && String(t.id) === String(selected.id)}
            onClick={() => setSelectedId(String(t.id))}
          />
        ))}
      </div>
    )
  }

  return (
    <div className="cn-page cn-qc-page cn-tpl-page" data-testid="templates-page">
      {/* ── 页头：标题 + 口径说明 + 搜索 / 导入 / 新建入口（与质量检查页同款紧凑页头） ── */}
      <header className="cn-page-head">
        <div className="cn-page-head-main">
          <span className="cn-page-head-icon" aria-hidden><AppstoreOutlined /></span>
          <div className="cn-page-head-text">
            <h1 className="cn-page-head-title">工作区模板</h1>
            <div className="cn-page-head-sub">
              <span className="cn-page-head-meta">
                左侧为内置与自定义模板清单，右侧为选中模板的结构化详情；更新时先看 diff 与已有数据影响，再确认保存。
              </span>
            </div>
          </div>
        </div>
        <div className="cn-page-head-actions">
          <Input.Search
            placeholder="搜索模板 / 分类"
            allowClear
            value={search}
            onChange={e => setSearch(e.target.value)}
            style={{ width: 200 }}
          />
          <Button icon={<ImportOutlined />} onClick={() => setImportOpen(true)} data-testid="import-template-btn">
            导入模板
          </Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreate} data-testid="create-template-btn">
            新建模板
          </Button>
          <Button onClick={() => navigate('/w')}>返回工作区</Button>
        </div>
      </header>

      <Alert
        type="info"
        showIcon
        message="模板更新不会破坏已有数据"
        description="保存模板时只增量补齐缺失的表 / 字段 / 文档；被移出模板的表、字段、文档一律保留。字段类型切换与删除当前阶段会提示确认。"
      />

      {error ? (
        <Alert type="error" showIcon message="模板加载失败" description={error instanceof Error ? error.message : String(error)} />
      ) : (
        <div className="cn-qc-split" data-testid="templates-split">
          {/* 左栏：模板清单（内置 / 自定义分组） */}
          <SectionBox
            title="模板清单"
            icon={<UnorderedListOutlined />}
            extra={<span>共 {templates.length} 条</span>}
            flush
            testId="template-list-box"
          >
            <Spin spinning={isLoading}>
              {!isLoading && templates.length === 0 ? (
                <div className="cn-qc-empty">
                  <Empty description="还没有模板，新建一个或用内置科研项目模板复制" />
                </div>
              ) : (
                <div role="listbox" aria-label="模板清单" className="cn-cr-side-list">
                  {renderGroup('内置模板', grouped.builtin)}
                  {renderGroup('自定义模板', grouped.custom)}
                </div>
              )}
            </Spin>
          </SectionBox>

          {/* 右栏：选中模板的元信息与结构化详情 + 操作 */}
          <SectionBox
            title={selected ? selected.name : '模板详情'}
            icon={<FileTextOutlined />}
            extra={selected ? (
              <Space size={8} wrap>
                <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(selected)}>
                  编辑规格
                </Button>
                <Button size="small" icon={<CopyOutlined />} onClick={() => openClone(selected)}>
                  复制
                </Button>
                <Button
                  size="small"
                  icon={<ExportOutlined />}
                  loading={exportTemplate.isPending && exportTemplate.variables?.id === selected.id}
                  onClick={() => exportTemplate.mutate(selected)}
                  data-testid={`export-template-${selected.id}`}
                >
                  导出
                </Button>
                <Popconfirm
                  title="删除模板？"
                  description={selected.workspace_count > 0 ? '仍有工作区在使用，无法删除' : '删除后不可恢复（历史版本一并删除）'}
                  disabled={selected.workspace_count > 0}
                  onConfirm={() => remove.mutate(Number(selected.id))}
                >
                  <Button size="small" danger disabled={selected.workspace_count > 0} icon={<DeleteOutlined />}>
                    删除
                  </Button>
                </Popconfirm>
              </Space>
            ) : undefined}
            testId="template-detail-box"
          >
            <Spin spinning={isLoading}>
              {!selected ? (
                <div className="cn-qc-empty">
                  <Empty description="选择左侧模板查看详情" />
                </div>
              ) : (
                <div data-testid="template-detail">
                  <Descriptions size="small" column={2} style={{ marginBottom: 8 }}>
                    <Descriptions.Item label="说明" span={2}>{selected.description || '—'}</Descriptions.Item>
                    <Descriptions.Item label="分类">{selected.category || '—'}</Descriptions.Item>
                    <Descriptions.Item label="版本">v{selected.version}</Descriptions.Item>
                    <Descriptions.Item label="模块">
                      {selected.modules.length ? selected.modules.map(m => <Tag key={m}>{m}</Tag>) : '—'}
                    </Descriptions.Item>
                    <Descriptions.Item label="使用情况">{selected.workspace_count} 个工作区使用</Descriptions.Item>
                    <Descriptions.Item label="更新时间" span={2}>{formatDateTime(selected.updated_at)}</Descriptions.Item>
                  </Descriptions>
                  <TemplateDetail template={selected} />
                </div>
              )}
            </Spin>
          </SectionBox>
        </div>
      )}

      <TemplateEditorModal
        open={editorOpen}
        template={editing}
        seed={seed}
        onClose={() => setEditorOpen(false)}
      />
      <TemplateImportModal open={importOpen} onClose={() => setImportOpen(false)} />
    </div>
  )
}
