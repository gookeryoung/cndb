/** 报表模板页 — 模板 CRUD + 渲染下载. */

import React, { useEffect, useMemo } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { Table, Button, Space, Tag, Modal, Form, Input, Typography, message, Select, Dropdown, Empty, Row, Col } from 'antd'
import { PlusOutlined, DeleteOutlined, EditOutlined, DownloadOutlined, ArrowLeftOutlined, MoreOutlined, FileTextOutlined } from '@ant-design/icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { reportApi, tableApi } from '@/api'
import type { ReportTemplate, ReportTemplateSummary, ReportTemplateCreate, ReportTemplateUpdate, ReportParameter, TableSummary } from '@/api'

const { Title, Text } = Typography
const FORMAT_OPTIONS = [
  { value: 'docx', label: 'Word (.docx)' },
  { value: 'pdf', label: 'PDF (.pdf)' },
  { value: 'html', label: 'HTML (.html)' },
  { value: 'csv', label: 'CSV (.csv)' },
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

  // 根据模板是否定义参数，决定直接渲染还是先弹参数窗口
  const handleRenderClick = (r: ReportTemplateSummary) => {
    if (!r.parameters || r.parameters.length === 0) {
      renderReport.mutate({ tpl: r, params: {} })
      return
    }
    setRenderTarget(r)
    setRenderParamsOpen(true)
  }
  const [form] = Form.useForm()

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
    mutationFn: async (arg: { tpl: ReportTemplateSummary; params: Record<string, unknown> }) => {
      const { tpl, params } = arg
      if (!wid) throw new Error('缺少 workspace')
      const blob = await reportApi.render(tpl.id, { table_id: tpl.table_id ?? 0, params })
      // 触发浏览器下载
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

  const openCreate = () => {
    setEditing(null)
    form.setFieldsValue({
      name: '',
      description: '',
      output_format: 'docx',
      template_content: 'Hello {{ name }}! 总数 {{ total }}',
      table_id: null,
      parameters: [],
    })
    setEditorOpen(true)
  }

  const openEdit = (tpl: ReportTemplateSummary) => {
    // 获取完整模板（含 template_content）
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
          <Text type="secondary">基于 Jinja2 的轻量级报告模板，支持 Word/PDF/HTML/CSV/Excel 输出</Text>
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

      {/* 模板编辑器 */}
      <TemplateEditor
        open={editorOpen}
        editing={editing}
        tables={tables}
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
        onSubmit={(params) => {
          if (!renderTarget) return
          renderReport.mutate(
            { tpl: renderTarget, params },
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
  form: ReturnType<typeof Form.useForm>[0]
  onClose: () => void
  onSubmit: (data: ReportTemplateCreate) => void
  submitting: boolean
}

function TemplateEditor({ open, editing, tables, form, onClose, onSubmit, submitting }: EditorProps) {
  const tableOptions = useMemo(() => tables.map(t => ({ value: t.id, label: t.name })), [tables])

  return (
    <Modal
      title={editing ? `编辑模板「${editing.name}」` : '新建模板'}
      open={open}
      onCancel={onClose}
      width={760}
      onOk={() => form.submit()}
      confirmLoading={submitting}
      okText={editing ? '保存' : '创建'}
      cancelText="取消"
      destroyOnHidden
    >
      <Form form={form} layout="vertical" preserve={false} onFinish={(v) => onSubmit(v as ReportTemplateCreate)}>
        <Row gutter={12}>
          <Col span={12}>
            <Form.Item name="name" label="模板名称" rules={[{ required: true, message: '请输入名称' }]}>
              <Input placeholder="例如：月度销售汇总" />
            </Form.Item>
          </Col>
          <Col span={6}>
            <Form.Item name="output_format" label="输出格式">
              <Select options={FORMAT_OPTIONS} />
            </Form.Item>
          </Col>
          <Col span={6}>
            <Form.Item name="table_id" label="关联表">
              <Select options={tableOptions} allowClear placeholder="选填" />
            </Form.Item>
          </Col>
        </Row>
        <Form.Item name="description" label="描述（可选）">
          <Input.TextArea rows={2} placeholder="简单说明这个模板的用途" />
        </Form.Item>
        <Form.Item name="template_content" label="模板内容 (Jinja2)" rules={[{ required: true, message: '请输入模板内容' }]}
          extra={<Text type="secondary" style={{ fontSize: 12 }}>使用 {'{{ field }}'} 引用字段，{'{% for row in rows %}'} 遍历行</Text>}>
          <Input.TextArea rows={8} placeholder="{{ name }} 的值是 {{ value }}" style={{ fontFamily: 'ui-monospace, monospace' }} />
        </Form.Item>
        <Form.Item label="模板参数" tooltip="运行时传入的动态参数（可选）">
          <Form.List name="parameters">
            {(fields, { add, remove }) => (
              <>
                {fields.map(({ key, name, ...restField }) => (
                  <Space key={key} style={{ display: 'flex', marginBottom: 8 }} align="baseline">
                    <Form.Item {...restField} name={[name, 'name']} rules={[{ required: true }]}>
                      <Input placeholder="参数名" style={{ width: 140 }} />
                    </Form.Item>
                    <Form.Item {...restField} name={[name, 'type']}>
                      <Select options={PARAM_TYPES} style={{ width: 100 }} />
                    </Form.Item>
                    <Form.Item {...restField} name={[name, 'default']}>
                      <Input placeholder="默认值" style={{ width: 120 }} />
                    </Form.Item>
                    <Form.Item {...restField} name={[name, 'required']} valuePropName="checked">
                      <Select options={[{ value: true, label: '必填' }, { value: false, label: '可选' }]} style={{ width: 80 }} />
                    </Form.Item>
                    <Button type="text" danger icon={<DeleteOutlined />} onClick={() => remove(name)} />
                  </Space>
                ))}
                <Button type="dashed" onClick={() => add({ name: '', type: 'string', default: null, required: false })} block icon={<PlusOutlined />}>
                  添加参数
                </Button>
              </>
            )}
          </Form.List>
        </Form.Item>
      </Form>
    </Modal>
  )
}

// ════════════════════════════════════════════════ 渲染参数 Modal ════════════════════════════════════════════════

interface RenderParamsModalProps {
  open: boolean
  target: ReportTemplateSummary | null
  tables: TableSummary[]
  onClose: () => void
  onSubmit: (params: Record<string, unknown>) => void
  submitting: boolean
}

function RenderParamsModal({ open, target, tables, onClose, onSubmit, submitting }: RenderParamsModalProps) {
  const [form] = Form.useForm<Record<string, unknown>>()
  useEffect(() => {
    if (open && target) {
      const initial: Record<string, unknown> = {}
      target.parameters.forEach(p => { if (p.default !== undefined) initial[p.name] = p.default })
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      form.setFieldsValue(initial as any)
    }
  }, [open, target])  // eslint-disable-line react-hooks/exhaustive-deps

  const tableNameMap = useMemo(() => new Map(tables.map(t => [t.id, t.name])), [tables])

  return (
    <Modal
      title={target ? `渲染模板：${target.name}` : '渲染参数'}
      open={open}
      onCancel={() => { form.resetFields(); onClose() }}
      confirmLoading={submitting}
      okText="生成报告"
      cancelText="取消"
      onOk={async () => {
        try {
          const values = await form.validateFields()
          onSubmit(values as Record<string, unknown>)
        } catch { /* 用户取消校验 */ }
      }}
    >
      {target?.table_id ? (
        <Typography.Text type="secondary" style={{ display: 'block', marginBottom: 16 }}>
          数据源表：{tableNameMap.get(target.table_id) || `#${target.table_id}`}
        </Typography.Text>
      ) : (
        <Typography.Text type="danger" style={{ display: 'block', marginBottom: 16 }}>
          模板未关联数据表，无法渲染
        </Typography.Text>
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
      </Form>
    </Modal>
  )
}
