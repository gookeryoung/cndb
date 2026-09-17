/** 报表模板页 — 模板 CRUD + 可视化编辑器 + 渲染下载. */

import React, { useEffect, useMemo, useRef, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { Table, Button, Space, Tag, Modal, Form, Input, Typography, message, Select, Dropdown, Empty, Tabs } from 'antd'
import type { FormInstance } from 'antd'
import { PlusOutlined, DeleteOutlined, EditOutlined, DownloadOutlined, ArrowLeftOutlined, MoreOutlined, FileTextOutlined } from '@ant-design/icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { reportApi, tableApi, fieldApi, recordApi } from '@/api'
import type { ReportTemplate, ReportTemplateSummary, ReportTemplateCreate, ReportTemplateUpdate, ReportParameter, TableSummary, Field } from '@/api'
import { ReportTemplateEditor, PreviewPanel, SyntaxHelpPanel } from '@/components/report-editor'
import type { TemplateEditorHandle } from '@/components/report-editor'

const { Title, Text } = Typography
const FORMAT_OPTIONS = [
  { value: 'docx', label: 'Word (.docx)' },
  { value: 'pdf', label: 'PDF (.pdf)' },
  { value: 'xlsx', label: 'Excel (.xlsx)' },
]
const PARAM_TYPES = [
  { value: 'string', label: '文本' },
  { value: 'number', label: '数字' },
  { value: 'date', label: '日期' },
  { value: 'boolean', label: '布尔' },
]

export default function ReportsPage() {
  const { wid } = useParams<{ wid: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [editorOpen, setEditorOpen] = React.useState(false)
  const [editing, setEditing] = React.useState<ReportTemplate | null>(null)
  const [renderParamsOpen, setRenderParamsOpen] = React.useState(false)
  const [renderTarget, setRenderTarget] = React.useState<ReportTemplateSummary | null>(null)

  const handleRenderClick = (r: ReportTemplateSummary) => {
    if (!r.parameters || r.parameters.length === 0) {
      renderReport.mutate({ tpl: r, params: {} })
      return
    }
    setRenderTarget(r)
    setRenderParamsOpen(true)
  }

  const { data: templates = [], isLoading } = useQuery<ReportTemplateSummary[]>({
    queryKey: ['report-templates'],
    queryFn: () => reportApi.list(),
  })

  const { data: tables = [] } = useQuery({
    queryKey: ['workspaces', wid, 'tables'],
    queryFn: () => tableApi.list(wid!),
    enabled: !!wid,
  })

  const create = useMutation({
    mutationFn: (data: ReportTemplateCreate) => reportApi.create(data),
    onSuccess: () => {
      message.success('模板已创建')
      queryClient.invalidateQueries({ queryKey: ['report-templates'] })
      setEditorOpen(false)
      form.resetFields()
    },
  })

  const update = useMutation({
    mutationFn: ({ id, data }: { id: number | string; data: ReportTemplateUpdate }) => reportApi.update(id, data),
    onSuccess: () => {
      message.success('模板已更新')
      queryClient.invalidateQueries({ queryKey: ['report-templates'] })
      setEditorOpen(false)
      setEditing(null)
      form.resetFields()
    },
  })

  const remove = useMutation({
    mutationFn: (id: number | string) => reportApi.remove(id),
    onSuccess: () => {
      message.success('模板已删除')
      queryClient.invalidateQueries({ queryKey: ['report-templates'] })
    },
  })

  const renderReport = useMutation({
    mutationFn: async (arg: { tpl: ReportTemplateSummary; params: Record<string, unknown>; extraTableIds?: number[] }) => {
      const { tpl, params, extraTableIds = [] } = arg
      if (!wid) throw new Error('缺少 workspace')
      const body: Record<string, unknown> = { table_id: tpl.table_id ?? 0, params }
      if (extraTableIds.length > 0) {
        body.extra_table_ids = extraTableIds
      }
      const blob = await reportApi.render(tpl.id, body as any)
      const ext = tpl.output_format === 'docx' ? 'docx' : tpl.output_format === 'pdf' ? 'pdf' : tpl.output_format
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `${tpl.name}.${ext}`
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)
    },
    onSuccess: () => message.success('报告已生成'),
  })

  const tableNameMap = useMemo(() => new Map(tables.map(t => [t.id, t.name])), [tables])
  const [form] = Form.useForm()

  const openCreate = () => {
    setEditing(null)
    form.setFieldsValue({
      name: '',
      description: '',
      output_format: 'docx',
      template_content: 'Hello {{ table_name }}!\n共 {{ records | length }} 条记录\n\n{% for row in records %}- {{ row.name }}{% endfor %}',
      table_id: null,
      parameters: [],
    })
    setEditorOpen(true)
  }

  const openEdit = (tpl: ReportTemplateSummary) => {
    reportApi.get(tpl.id).then(full => {
      setEditing(full)
      form.setFieldsValue({
        name: full.name,
        description: full.description,
        output_format: full.output_format,
        template_content: full.template_content,
        table_id: full.table_id,
        parameters: full.parameters as ReportParameter[],
      })
      setEditorOpen(true)
    }).catch(() => {})
  }

  const columns = [
    {
      title: '模板名称',
      dataIndex: 'name',
      key: 'name',
      render: (n: string, _r: ReportTemplateSummary) => (
        <><FileTextOutlined style={{ marginRight: 6 }} />{n}</>
      ),
    },
    {
      title: '输出格式',
      dataIndex: 'output_format',
      key: 'output_format',
      width: 110,
      render: (f: string) => {
        const opt = FORMAT_OPTIONS.find(o => o.value === f)
        return <Tag color="blue">{opt?.label || f}</Tag>
      },
    },
    {
      title: '关联表',
      dataIndex: 'table_id',
      key: 'table_id',
      width: 160,
      render: (tid: number | null) => tid ? (tableNameMap.get(tid) || <Text type="secondary">#{tid}</Text>) : <Text type="secondary" italic>未关联</Text>,
    },
    {
      title: '描述',
      dataIndex: 'description',
      key: 'description',
      ellipsis: true,
      render: (d: string) => d || <Text type="secondary" italic>—</Text>,
    },
    {
      title: '参数',
      dataIndex: 'parameters',
      key: 'parameters',
      width: 200,
      render: (params: ReportParameter[]) => params.length > 0
        ? <Space wrap size={[4, 4]}>{params.map(p => <Tag key={p.name}>{p.name}{p.required ? '*' : ''}</Tag>)}</Space>
        : <Text type="secondary" italic>无</Text>,
    },
    {
      title: '操作',
      key: 'actions',
      width: 200,
      render: (_: unknown, r: ReportTemplateSummary) => (
        <Space size="small">
          <Button size="small" icon={<DownloadOutlined />}
            loading={renderReport.isPending}
            disabled={!r.table_id}
            onClick={() => handleRenderClick(r)}>渲染下载</Button>
          <Dropdown
            menu={{
              items: [
                { key: 'edit', icon: <EditOutlined />, label: '编辑', onClick: () => openEdit(r) },
                { type: 'divider' },
                {
                  key: 'delete', icon: <DeleteOutlined />, label: '删除', danger: true,
                  onClick: () => {
                    Modal.confirm({
                      title: `删除模板「${r.name}」？`,
                      okText: '删除', okType: 'danger', cancelText: '取消',
                      onOk: () => remove.mutate(r.id),
                    })
                  },
                },
              ],
            }}
          >
            <Button size="small" icon={<MoreOutlined />} />
          </Dropdown>
        </Space>
      ),
    },
  ]

  return (
    <div style={{ padding: 24 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <div>
          <Space>
            <Button icon={<ArrowLeftOutlined />} onClick={() => navigate(`/w/${wid}`)} />
            <Title level={3} style={{ margin: 0 }}>报表模板</Title>
          </Space>
          <Text type="secondary">基于 Jinja2 的轻量级报告模板，支持字段拖拽 + 实时预览 + Word/PDF/Excel 输出</Text>
        </div>
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新建模板</Button>
      </div>

      <Table
        rowKey="id"
        size="middle"
        loading={isLoading}
        columns={columns}
        dataSource={templates}
        pagination={false}
        locale={{ emptyText: <Empty description="暂无模板，点击右上角新建一个" /> }}
      />

      <TemplateEditor
        open={editorOpen}
        editing={editing}
        tables={tables}
        workspaceId={wid!}
        form={form}
        onClose={() => { setEditorOpen(false); setEditing(null); form.resetFields() }}
        onSubmit={(v) => {
          if (editing) update.mutate({ id: editing.id, data: v })
          else create.mutate(v)
        }}
        submitting={create.isPending || update.isPending}
      />

      <RenderParamsModal
        open={renderParamsOpen}
        target={renderTarget}
        tables={tables}
        onClose={() => { setRenderParamsOpen(false); setRenderTarget(null) }}
        onSubmit={(params, extraTableIds) => {
          if (!renderTarget) return
          renderReport.mutate(
            { tpl: renderTarget, params, extraTableIds },
            { onSuccess: () => { setRenderParamsOpen(false); setRenderTarget(null) } },
          )
        }}
        submitting={renderReport.isPending}
      />
    </div>
  )
}

// ─────────────── 模板编辑器 Modal ───────────────

interface EditorProps {
  open: boolean
  editing: ReportTemplate | null
  tables: TableSummary[]
  workspaceId: string
  form: FormInstance
  onClose: () => void
  onSubmit: (data: ReportTemplateCreate) => void
  submitting: boolean
}

function TemplateEditor({ open, editing, tables, workspaceId, form, onClose, onSubmit, submitting }: EditorProps) {
  const tableOptions = useMemo(() => tables.map(t => ({ value: t.id, label: t.name })), [tables])

  // 编辑器 value（受控）
  const [templateValue, setTemplateValue] = useState('')
  // 当前选中的关联表 ID（从 Form 监听）
  const [selectedTableId, setSelectedTableId] = useState<number | null>(null)
  // 额外选择的表 ID 列表
  const [extraTableIds, setExtraTableIds] = useState<number[]>([])
  // CodeMirror 引用（供 SyntaxHelpPanel 插入代码使用）
  const editorRef = useRef<TemplateEditorHandle | null>(null)

  // 关联表的字段列表
  const { data: fields = [] } = useQuery<Field[]>({
    queryKey: ['workspaces', workspaceId, 'tables', selectedTableId, 'fields'],
    queryFn: () => fieldApi.list(workspaceId, selectedTableId!),
    enabled: !!selectedTableId && !!workspaceId,
  })

  // 额外表的字段列表（批量加载）
  const { data: extraFieldsMap = {} } = useQuery<Record<number, Field[]>>({
    queryKey: ['workspaces', workspaceId, 'extra-fields', extraTableIds],
    queryFn: async () => {
      const result: Record<number, Field[]> = {}
      await Promise.all(extraTableIds.map(async (tid) => {
        result[tid] = await fieldApi.list(workspaceId, tid)
      }))
      return result
    },
    enabled: extraTableIds.length > 0 && !!workspaceId,
  })

  // 关联表的前 10 行真实数据（用于预览）
  const { data: previewRows = [], isLoading: previewLoading } = useQuery({
    queryKey: ['workspaces', workspaceId, 'tables', selectedTableId, 'records', 'preview'],
    queryFn: async () => {
      const resp = await recordApi.list(workspaceId, selectedTableId!, { limit: 10 })
      return resp.items.map(r => {
        const { id: _id, created_at: _ca, updated_at: _ua, created_by: _cb, updated_by: _ub, ...rest } = r as any
        return rest
      }) as Array<Record<string, unknown>>
    },
    enabled: !!selectedTableId && !!workspaceId,
  })

  // 额外表的预览数据（用于 PreviewPanel records_by_table）
  const { data: extraPreviewMap = {} } = useQuery<Record<number, Array<Record<string, unknown>>>>({
    queryKey: ['workspaces', workspaceId, 'extra-preview', extraTableIds],
    queryFn: async () => {
      const result: Record<number, Array<Record<string, unknown>>> = {}
      await Promise.all(extraTableIds.map(async (tid) => {
        const resp = await recordApi.list(workspaceId, tid, { limit: 5 })
        result[tid] = resp.items.map(r => {
          const { id: _id, created_at: _ca, updated_at: _ua, created_by: _cb, updated_by: _ub, ...rest } = r as any
          return rest
        })
      }))
      return result
    },
    enabled: extraTableIds.length > 0 && !!workspaceId,
  })

  // Modal 打开时初始化值
  useEffect(() => {
    if (!open) return
    const tplContent: string = form.getFieldValue('template_content') || ''
    const tplId: number | null = form.getFieldValue('table_id') ?? null
    const extras: number[] = form.getFieldValue('extra_table_ids') || []
    setTemplateValue(tplContent)
    setSelectedTableId(tplId)
    setExtraTableIds(extras)
  }, [open]) // eslint-disable-line react-hooks/exhaustive-deps

  // 全局 insert 事件监听（SyntaxHelpPanel → ReportTemplateEditor）
  useEffect(() => {
    const handler = (e: Event) => {
      const ce = e as CustomEvent<{ code?: string; fieldName?: string }>
      if (ce.detail?.code) {
        editorRef.current?.insertText(ce.detail.code)
      } else if (ce.detail?.fieldName) {
        editorRef.current?.insertText(`{{ ${ce.detail.fieldName} }}`)
      }
    }
    window.addEventListener('report-editor-insert', handler)
    return () => window.removeEventListener('report-editor-insert', handler)
  }, [])

  // 关联表变更时更新 selectedTableId（同时从 extra 表中排除它）
  const handleTableChange = (value: number | null) => {
    setSelectedTableId(value)
    if (value !== null) {
      setExtraTableIds(prev => prev.filter(id => id !== value))
    }
  }

  // extra_table_ids 变更（排除主表本身）
  const handleExtraTablesChange = (values: number[]) => {
    const filtered = selectedTableId !== null
      ? values.filter(id => id !== selectedTableId)
      : values
    setExtraTableIds(filtered)
    form.setFieldValue('extra_table_ids', filtered)
  }

  // 模板内容变更（CodeMirror → Form 同步）
  const handleTemplateChange = (value: string) => {
    setTemplateValue(value)
    form.setFieldValue('template_content', value)
  }

  // 保存校验
  const handleFormFinish = (v: ReportTemplateCreate) => {
    onSubmit({ ...v, template_content: templateValue })
  }

  const selectedTableName = selectedTableId
    ? tables.find(t => t.id === selectedTableId)?.name
    : undefined

  // 构建多表字段分组
  const tableGroups = useMemo(() => {
    const groups: Array<{ tableId: number; tableName: string; fields: Field[]; isPrimary: boolean }> = []
    if (selectedTableId !== null && selectedTableName) {
      groups.push({ tableId: selectedTableId, tableName: selectedTableName, fields, isPrimary: true })
    }
    for (const eid of extraTableIds) {
      const tname = tables.find(t => t.id === eid)?.name
      const efields = extraFieldsMap[eid] || []
      if (tname) {
        groups.push({ tableId: eid, tableName: tname, fields: efields, isPrimary: false })
      }
    }
    return groups
  }, [selectedTableId, selectedTableName, fields, extraTableIds, extraFieldsMap, tables])

  // 构建 recordsByTable
  const recordsByTable = useMemo(() => {
    const result: Record<string, Array<Record<string, unknown>>> = {}
    for (const eid of extraTableIds) {
      const tname = tables.find(t => t.id === eid)?.name
      if (tname && extraPreviewMap[eid]) {
        result[tname] = extraPreviewMap[eid]
      }
    }
    return result
  }, [extraTableIds, extraPreviewMap, tables])

  // extra 表选项（排除已选的主表）
  const extraTableOptions = useMemo(() => {
    return tableOptions.filter(o => o.value !== selectedTableId)
  }, [tableOptions, selectedTableId])

  return (
    <Modal
      title={editing ? `编辑模板「${editing.name}」` : '新建模板'}
      open={open}
      onCancel={onClose}
      width="min(1280px, 92vw)"
      onOk={() => form.submit()}
      confirmLoading={submitting}
      okText={editing ? '保存' : '创建'}
      cancelText="取消"
      destroyOnHidden
      footer={null}
      styles={{ body: { padding: 0, maxHeight: 'calc(92vh - 110px)', overflowY: 'auto' } }}
    >
      {/* 顶部：模板元信息 */}
      <Form
        form={form}
        layout="vertical"
        preserve={false}
        style={{ padding: '16px 24px 0' }}
        onFinish={handleFormFinish}
      >
        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
          <Form.Item name="name" label="模板名称" rules={[{ required: true, message: '请输入名称' }]} style={{ flex: '1 1 220px', marginBottom: 8 }}>
            <Input placeholder="例如：月度销售汇总" />
          </Form.Item>
          <Form.Item name="output_format" label="输出格式" style={{ width: 150, marginBottom: 8 }}>
            <Select options={FORMAT_OPTIONS} />
          </Form.Item>
          <Form.Item name="table_id" label="关联表" style={{ width: 220, marginBottom: 8 }}>
            <Select
              options={tableOptions}
              allowClear
              placeholder="选填（建议关联）"
              onChange={handleTableChange}
            />
          </Form.Item>
          <Form.Item name="extra_table_ids" label="额外引用表" style={{ flex: '1 1 220px', marginBottom: 8 }} tooltip="模板中可通过 records_by_table['表名'] 引用这些表的数据">
            <Select
              mode="multiple"
              options={extraTableOptions}
              placeholder="选择额外引用的数据表（可选）"
              onChange={handleExtraTablesChange}
              value={extraTableIds}
              allowClear
              maxTagCount={3}
            />
          </Form.Item>
        </div>
        <Form.Item name="description" label="描述（可选）" style={{ marginBottom: 8 }}>
          <Input.TextArea rows={1} placeholder="简单说明这个模板的用途" />
        </Form.Item>
      </Form>

      {/* 隐藏的 template_content 字段 — 实际值由 CodeMirror 控制 */}
      <Form form={form} preserve={false} style={{ display: 'none' }}>
        <Form.Item name="template_content" rules={[{ required: true, message: '请输入模板内容' }]}>
          <Input />
        </Form.Item>
      </Form>

      {/* 编辑器主体：字段面板 + 编辑器 + 预览（统一 ReportTemplateEditor，无重复） */}
      <div style={{ padding: '12px 24px 0' }}>
        <div className="report-editor-body" style={{ height: 520 }}>
          <ReportTemplateEditor
            fields={selectedTableId !== null ? (fields as Field[]) : undefined}
            tableGroups={tableGroups.length > 0 ? tableGroups : undefined}
            value={templateValue}
            onChange={handleTemplateChange}
            editorRef={editorRef}
          />

          {/* 右侧：Tabs（预览 / 语法帮助） */}
          <div className="report-right-panel">
            <Tabs
              defaultActiveKey="preview"
              size="small"
              items={[
                {
                  key: 'preview',
                  label: '实时预览',
                  children: (
                    <PreviewPanel
                      template={templateValue}
                      records={previewRows as Array<Record<string, unknown>>}
                      tableName={selectedTableName}
                      loading={previewLoading}
                      recordsByTable={recordsByTable}
                    />
                  ),
                },
                {
                  key: 'help',
                  label: '语法帮助',
                  children: (
                    <SyntaxHelpPanel
                      onInsert={(code) => {
                        window.dispatchEvent(new CustomEvent('report-editor-insert', { detail: { code } }))
                      }}
                    />
                  ),
                },
              ]}
            />
          </div>
        </div>
      </div>

      {/* 参数定义区 */}
      <div style={{ padding: '12px 24px 0' }}>
        <Form form={form} layout="vertical" preserve={false}>
          <Form.Item label="模板参数" tooltip="运行时传入的动态参数（可选）" style={{ marginBottom: 0 }}>
            <Form.List name="parameters">
              {(paramFields, { add, remove }) => (
                <>
                  <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 8 }}>
                    {paramFields.map(({ key, name, ...restField }) => (
                      <Space key={key} style={{ display: 'flex', marginBottom: 4 }} align="baseline">
                        <Form.Item {...restField} name={[name, 'name']} rules={[{ required: true }]}>
                          <Input placeholder="参数名" style={{ width: 120 }} />
                        </Form.Item>
                        <Form.Item {...restField} name={[name, 'type']}>
                          <Select options={PARAM_TYPES} style={{ width: 90 }} />
                        </Form.Item>
                        <Form.Item {...restField} name={[name, 'default']}>
                          <Input placeholder="默认值" style={{ width: 100 }} />
                        </Form.Item>
                        <Form.Item {...restField} name={[name, 'label']}>
                          <Input placeholder="显示名" style={{ width: 100 }} />
                        </Form.Item>
                        <Form.Item {...restField} name={[name, 'required']} valuePropName="checked">
                          <Select options={[{ value: true, label: '必填' }, { value: false, label: '可选' }]} style={{ width: 80 }} />
                        </Form.Item>
                        <Button type="text" danger icon={<DeleteOutlined />} onClick={() => remove(name)} />
                      </Space>
                    ))}
                  </div>
                  <Button type="dashed" onClick={() => add({ name: '', type: 'string', default: null, label: '', required: false })} block icon={<PlusOutlined />}>
                    添加参数
                  </Button>
                </>
              )}
            </Form.List>
          </Form.Item>
        </Form>
      </div>

      {/* 底部按钮区 */}
      <div style={{ padding: '12px 24px', borderTop: '1px solid #f0f0f0', textAlign: 'right' }}>
        <Space>
          <Button onClick={onClose}>取消</Button>
          <Button
            type="primary"
            loading={submitting}
            onClick={() => {
              form.validateFields().then(handleFormFinish).catch(() => {})
            }}
          >
            {editing ? '保存' : '创建'}
          </Button>
        </Space>
      </div>
    </Modal>
  )
}

// ════════════════════════════════════════════════ 渲染参数 Modal ════════════════════════════════════════════════

interface RenderParamsModalProps {
  open: boolean
  target: ReportTemplateSummary | null
  tables: TableSummary[]
  onClose: () => void
  onSubmit: (params: Record<string, unknown>, extraTableIds?: number[]) => void
  submitting: boolean
}

function RenderParamsModal({ open, target, tables, onClose, onSubmit, submitting }: RenderParamsModalProps) {
  const [form] = Form.useForm<Record<string, unknown>>()
  const [extraTableIds, setExtraTableIds] = useState<number[]>([])

  useEffect(() => {
    if (open && target) {
      const initial: Record<string, unknown> = {}
      target.parameters.forEach(p => { if (p.default !== undefined) initial[p.name] = p.default })
      form.setFieldsValue(initial as any)
      setExtraTableIds([])
    }
  }, [open, target, form])

  const tableNameMap = useMemo(() => new Map(tables.map(t => [t.id, t.name])), [tables])

  // 额外表选项（排除模板关联的主表）
  const extraTableOptions = useMemo(() => {
    if (!target?.table_id) return tables.map(t => ({ value: t.id, label: t.name }))
    return tables.filter(t => t.id !== target.table_id).map(t => ({ value: t.id, label: t.name }))
  }, [tables, target?.table_id])

  return (
    <Modal
      title={target ? `渲染模板：${target.name}` : '渲染参数'}
      open={open}
      onCancel={() => { form.resetFields(); setExtraTableIds([]); onClose() }}
      confirmLoading={submitting}
      okText="生成报告"
      cancelText="取消"
      onOk={async () => {
        try {
          const values = await form.validateFields()
          onSubmit(values as Record<string, unknown>, extraTableIds.length > 0 ? extraTableIds : undefined)
        } catch { /* 用户取消校验 */ }
      }}
    >
      {target?.table_id ? (
        <Typography.Text type="secondary" style={{ display: 'block', marginBottom: 12 }}>
          数据源表：{tableNameMap.get(target.table_id) || `#${target.table_id}`}
        </Typography.Text>
      ) : (
        <Typography.Text type="danger" style={{ display: 'block', marginBottom: 16 }}>
          模板未关联数据表，无法渲染
        </Typography.Text>
      )}

      {/* 额外引用表选择 */}
      {target?.table_id && (
        <Form.Item label="额外引用表" tooltip="模板中可通过 records_by_table['表名'] 引用" style={{ marginBottom: 12 }}>
          <Select
            mode="multiple"
            options={extraTableOptions}
            placeholder="选择额外引用的数据表（可选）"
            value={extraTableIds}
            onChange={setExtraTableIds}
            allowClear
            maxTagCount={3}
          />
        </Form.Item>
      )}

      <Form form={form} layout="vertical" disabled={!target?.table_id}>
        {target?.parameters.map(p => (
          <Form.Item
            key={p.name}
            label={p.label || p.name}
            name={p.name}
            rules={p.required ? [{ required: true, message: `参数 ${p.name} 必填` }] : []}
          >
            {p.type === 'boolean' ? (
              <Select options={[{ value: true, label: '是' }, { value: false, label: '否' }]} />
            ) : p.type === 'number' ? (
              <Input type="number" placeholder={`请输入 ${p.name}`} />
            ) : p.type === 'date' ? (
              <Input type="date" />
            ) : (
              <Input placeholder={`请输入 ${p.name}`} />
            )}
          </Form.Item>
        ))}
        {(!target?.parameters || target.parameters.length === 0) && (
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            该模板无自定义参数，选择额外引用表后直接点击「生成报告」
          </Typography.Text>
        )}
      </Form>
    </Modal>
  )
}
