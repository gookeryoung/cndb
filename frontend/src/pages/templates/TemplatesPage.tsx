/** 工作区模板中心（需求 0094）：模板列表 / 结构化预览 / 编辑与影响预览. */

import { useMemo, useState } from 'react'
import {
  Alert, App as AntApp, Button, Collapse, Descriptions, Empty, Input, List, Popconfirm,
  Space, Table, Tabs, Tag, Timeline, Typography,
} from 'antd'
import {
  PlusOutlined, EditOutlined, DeleteOutlined, CopyOutlined, ApartmentOutlined,
  FileTextOutlined, TableOutlined, CheckCircleOutlined, ClockCircleOutlined,
} from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { workspaceTemplateApi } from '@/api'
import type { TemplateSpecForm, WorkspaceTemplate } from '@/api'
import TemplateEditorModal from './TemplateEditorModal'
import { formatDateTime } from '@/utils/datetime'

const { Title, Text, Paragraph } = Typography

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

export default function TemplatesPage() {
  const { message } = AntApp.useApp()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [search, setSearch] = useState('')
  const [editorOpen, setEditorOpen] = useState(false)
  const [editing, setEditing] = useState<WorkspaceTemplate | null>(null)
  const [seed, setSeed] = useState<WorkspaceTemplate | null>(null)

  const { data: templates = [], isLoading, error } = useQuery({
    queryKey: ['workspace-templates', search],
    queryFn: () => workspaceTemplateApi.list(search.trim() || undefined),
  })

  const grouped = useMemo(() => {
    const builtin = templates.filter(t => t.is_builtin)
    const custom = templates.filter(t => !t.is_builtin)
    return { builtin, custom }
  }, [templates])

  const remove = useMutation({
    mutationFn: (id: number) => workspaceTemplateApi.remove(id),
    onSuccess: () => {
      message.success('模板已删除')
      queryClient.invalidateQueries({ queryKey: ['workspace-templates'] })
    },
    onError: (err) => message.error(err instanceof Error ? err.message : '删除失败'),
  })

  const openCreate = () => { setEditing(null); setSeed(null); setEditorOpen(true) }
  const openEdit = (t: WorkspaceTemplate) => { setEditing(t); setSeed(null); setEditorOpen(true) }
  const openClone = (t: WorkspaceTemplate) => { setEditing(null); setSeed(t); setEditorOpen(true) }

  const renderGroup = (title: string, items: WorkspaceTemplate[]) => {
    if (!items.length) return null
    return (
      <div style={{ marginBottom: 20 }}>
        <Title level={5} style={{ marginBottom: 10 }}>{title}</Title>
        <Collapse
          accordion
          items={items.map(t => ({
            key: String(t.id),
            label: (
              <Space wrap>
                <Text strong>{t.name}</Text>
                <Tag color="blue">v{t.version}</Tag>
                {t.is_builtin && <Tag color="gold">内置</Tag>}
                {t.category && <Tag>{t.category}</Tag>}
                <Text type="secondary" style={{ fontSize: 'var(--cn-text-xs)' }}>
                  {t.counts.stage_count} 阶段 / {t.counts.form_count} 表单 / {t.counts.document_rule_count} 文档规则
                  {t.counts.flow_count ? ` / ${t.counts.flow_count} 流程` : ''}
                  · {t.workspace_count} 个工作区使用
                </Text>
              </Space>
            ),
            extra: (
              <Space onClick={e => e.stopPropagation()}>
                <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(t)}>编辑规格</Button>
                <Button size="small" icon={<CopyOutlined />} onClick={() => openClone(t)}>复制</Button>
                <Popconfirm
                  title="删除模板？"
                  description={t.workspace_count > 0 ? '仍有工作区在使用，无法删除' : '删除后不可恢复（历史版本一并删除）'}
                  disabled={t.workspace_count > 0}
                  onConfirm={() => remove.mutate(Number(t.id))}
                >
                  <Button size="small" danger disabled={t.workspace_count > 0} icon={<DeleteOutlined />}>删除</Button>
                </Popconfirm>
              </Space>
            ),
            children: (
              <div>
                <Descriptions size="small" column={2} style={{ marginBottom: 8 }}>
                  <Descriptions.Item label="说明" span={2}>{t.description || '—'}</Descriptions.Item>
                  <Descriptions.Item label="模块">
                    {t.modules.length ? t.modules.map(m => <Tag key={m}>{m}</Tag>) : '—'}
                  </Descriptions.Item>
                  <Descriptions.Item label="更新时间">{formatDateTime(t.updated_at)}</Descriptions.Item>
                </Descriptions>
                <TemplateDetail template={t} />
              </div>
            ),
          }))}
        />
      </div>
    )
  }

  return (
    <div style={{ padding: 16, maxWidth: 1180, margin: '0 auto' }} data-testid="templates-page">
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap', marginBottom: 14 }}>
        <div>
          <Title level={3} style={{ marginBottom: 2 }}>工作区模板</Title>
          <Text type="secondary">
            模板定义表单、文档规则与生命周期阶段；更新时先看 diff 与已有数据影响，再确认保存。
          </Text>
        </div>
        <Space wrap>
          <Input.Search
            placeholder="搜索模板 / 分类"
            allowClear
            value={search}
            onChange={e => setSearch(e.target.value)}
            style={{ width: 220 }}
          />
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreate} data-testid="create-template-btn">
            新建模板
          </Button>
          <Button onClick={() => navigate('/w')}>返回工作区</Button>
        </Space>
      </div>

      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 14 }}
        message="模板更新不会破坏已有数据"
        description="保存模板时只增量补齐缺失的表 / 字段 / 文档；被移出模板的表、字段、文档一律保留。字段类型切换与删除当前阶段会提示确认。"
      />

      {error ? (
        <Alert type="error" showIcon message="模板加载失败" description={error instanceof Error ? error.message : String(error)} />
      ) : isLoading ? (
        <div className="cn-state">加载中…</div>
      ) : templates.length === 0 ? (
        <Empty description="还没有模板，新建一个或用内置科研项目模板复制" />
      ) : (
        <>
          {renderGroup('内置模板', grouped.builtin)}
          {renderGroup('自定义模板', grouped.custom)}
        </>
      )}

      <TemplateEditorModal
        open={editorOpen}
        template={editing}
        seed={seed}
        onClose={() => setEditorOpen(false)}
      />
    </div>
  )
}
