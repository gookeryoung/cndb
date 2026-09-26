/** 报表模板页 — 模板 CRUD + 可视化编辑器 + 渲染下载. */

import React, { useEffect, useMemo, useRef, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import dayjs from 'dayjs'
import { Table, Button, Space, Tag, Modal, Form, Input, Typography, App as AntApp, Select, Dropdown, Empty, Tooltip, Segmented, Tabs, Badge } from 'antd'
import type { FormInstance } from 'antd'
import { PlusOutlined, DeleteOutlined, EditOutlined, DownloadOutlined, ArrowLeftOutlined, MoreOutlined, FileTextOutlined } from '@ant-design/icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { reportApi, tableApi, fieldApi, recordApi, workspaceApi } from '@/api'
import type { ReportTemplate, ReportTemplateSummary, ReportTemplateCreate, ReportTemplateUpdate, ReportParameter, ReportTheme, TableSummary, Field, Workspace } from '@/api'
import { ReportTemplateEditor, PreviewPanel, SyntaxHelpPanel } from '@/components/report-editor'
import type { TemplateEditorHandle } from '@/components/report-editor'

const { Title, Text } = Typography
const FORMAT_OPTIONS = [
  { value: 'docx', label: 'Word (.docx)' },
  { value: 'pdf', label: 'PDF (.pdf)' },
  { value: 'xlsx', label: 'Excel (.xlsx)' },
  { value: 'html', label: 'HTML (.html)' },
]
const THEME_OPTIONS: Array<{ value: ReportTheme; label: string }> = [
  { value: 'minimal', label: '简约' },
  { value: 'business', label: '商务' },
  { value: 'modern', label: '现代' },
  { value: 'engineering', label: '工程' },
  { value: 'academic', label: '学术' },
]
const PARAM_TYPES = [
  { value: 'string', label: '文本' },
  { value: 'number', label: '数字' },
  { value: 'date', label: '日期' },
  { value: 'boolean', label: '布尔' },
]

export default function ReportsPage() {
  const { message } = AntApp.useApp()
  const { wid } = useParams<{ wid: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [editorOpen, setEditorOpen] = React.useState(false)
  const [editing, setEditing] = React.useState<ReportTemplate | null>(null)
  // 编辑器初始模板内容：由列表行详情显式传入，避免经 Form store 的时序间接层
  const [initialContent, setInitialContent] = React.useState('')
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
    onError: (err) => message.error(err instanceof Error ? err.message : '创建模板失败'),
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
    onError: (err) => message.error(err instanceof Error ? err.message : '更新模板失败'),
  })

  const remove = useMutation({
    mutationFn: (id: number | string) => reportApi.remove(id),
    onSuccess: () => {
      message.success('模板已删除')
      queryClient.invalidateQueries({ queryKey: ['report-templates'] })
    },
    onError: (err) => message.error(err instanceof Error ? err.message : '删除模板失败'),
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
      // 文件名带生成时间戳，与后端 Content-Disposition 语义一致，便于区分不同批次
      const ts = dayjs().format('YYYYMMDD_HHmmss')
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `${tpl.name}_${ts}.${ext}`
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)
    },
    onSuccess: () => message.success('报告已生成'),
    onError: (err) => message.error(err instanceof Error ? err.message : '生成报告失败'),
  })

  const tableNameMap = useMemo(() => new Map(tables.map(t => [t.id, t.name])), [tables])
  const [form] = Form.useForm()

  const openCreate = () => {
    setEditing(null)
    setInitialContent('Hello {{ table_name }}!\n共 {{ records | length }} 条记录\n\n{% for row in records %}- {{ row.name }}{% endfor %}')
    // Form 值统一在 TemplateEditor useEffect([open]) 内设置，避免与 destroyOnHidden + preserve=false 时序冲突
    setEditorOpen(true)
  }

  const openEdit = (tpl: ReportTemplateSummary) => {
    reportApi.get(tpl.id).then(full => {
      setEditing(full)
      // 模板内容直接驱动编辑器（不依赖 Form 回读），保证与所点行一致
      setInitialContent(full.template_content ?? '')
      // Form 值统一在 TemplateEditor useEffect([open]) 内设置
      setEditorOpen(true)
    }).catch((err: unknown) => {
      message.error(err instanceof Error ? err.message : '加载模板失败')
    })
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
            <Tooltip title="更多操作：编辑、删除模板">
              <Button size="small" icon={<MoreOutlined />} />
            </Tooltip>
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
            <Tooltip title="返回工作区数据表">
              <Button icon={<ArrowLeftOutlined />} onClick={() => navigate(`/w/${wid}`)} />
            </Tooltip>
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
        locale={{
          emptyText: (
            <div style={{ padding: '24px 0' }}>
              <Empty description="还没有报告模板" />
              <Button type="primary" size="small" icon={<PlusOutlined />} style={{ marginTop: 12 }} onClick={openCreate}>新建模板</Button>
            </div>
          ),
        }}
      />

      <TemplateEditor
        open={editorOpen}
        editing={editing}
        tables={tables}
        workspaceId={wid!}
        form={form}
        initialContent={initialContent}
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
  /** 编辑器初始模板内容（由所点行的详情显式传入） */
  initialContent: string
  onClose: () => void
  onSubmit: (data: ReportTemplateCreate) => void
  submitting: boolean
}

/** 编辑器弹窗页签 key（模板参数已整合进基本信息页签） */
type EditorTabKey = 'basic' | 'editor'

/** 表单字段 → 所属页签映射（保存校验失败时按此跳转；新增表单字段时必须同步维护此表） */
const FIELD_TAB_MAP: Record<string, EditorTabKey> = {
  name: 'basic',
  output_format: 'basic',
  theme: 'basic',
  table_id: 'basic',
  extra_table_ids: 'basic',
  description: 'basic',
  parameters: 'basic',
  template_content: 'editor',
}

function TemplateEditor({ open, editing, tables, workspaceId, form, initialContent, onClose, onSubmit, submitting }: EditorProps) {
  const tableOptions = useMemo(() => tables.map(t => ({ value: t.id, label: t.name })), [tables])

  // 编辑器 value（受控）
  const [templateValue, setTemplateValue] = useState('')
  // 当前选中的关联表 ID（从 Form 监听）
  const [selectedTableId, setSelectedTableId] = useState<number | null>(null)
  // 额外选择的表 ID 列表（本工作区 + 跨工作区）
  const [extraTableIds, setExtraTableIds] = useState<number[]>([])
  // 跨工作区表信息：tableId -> {name, wsId}（级联引入与编辑回显扫描共同填充）
  const [crossTableInfo, setCrossTableInfo] = useState<Record<number, { name: string; wsId: string }>>({})
  // 跨工作区级联选择状态
  const [importWsId, setImportWsId] = useState<string>('')
  const [importTableId, setImportTableId] = useState<number | null>(null)
  // CodeMirror 引用（供 SyntaxHelpPanel 插入代码使用）
  const editorRef = useRef<TemplateEditorHandle | null>(null)
  // 主区视图模式：编辑器保持挂载仅隐藏显示，避免切换后丢失内容与插入能力
  const [viewMode, setViewMode] = useState<'edit' | 'preview' | 'help'>('edit')
  // 弹窗页签：新建态默认基本信息，编辑态默认模板编辑
  const [activeTab, setActiveTab] = useState<EditorTabKey>('basic')
  // 校验失败涉及的页签（页签标题显示错误标记）
  const [erroredTabs, setErroredTabs] = useState<Set<EditorTabKey>>(new Set())
  // 编辑器页签是否已被访问（CodeMirror 避免在隐藏容器中初始化，首次激活后才挂载，之后保持挂载）
  const [editorVisited, setEditorVisited] = useState(false)

  // 工作区列表（跨工作区级联选择器数据源）
  const { data: workspaces = [] } = useQuery<Workspace[]>({
    queryKey: ['workspaces'],
    queryFn: () => workspaceApi.list(),
    enabled: open,
  })

  // 源工作区的表列表（级联第二步）
  const { data: importWsTables = [] } = useQuery({
    queryKey: ['workspaces', importWsId, 'tables'],
    queryFn: () => tableApi.list(importWsId!),
    enabled: open && !!importWsId && importWsId !== workspaceId,
  })

  // 编辑回显：主表或 extra_table_ids 中归属未知的表（如 seed 生成的跨工作区模板），扫描全部工作区补全信息
  const primaryTableMissing = selectedTableId !== null && !tables.some(t => t.id === selectedTableId) && !crossTableInfo[selectedTableId]
  const missingScan = open && (primaryTableMissing || extraTableIds.some(tid => !tables.some(t => t.id === tid) && !crossTableInfo[tid]))
  useEffect(() => {
    if (!missingScan) return
    let cancelled = false
    workspaceApi.list().then(async (wsList) => {
      const info: Record<number, { name: string; wsId: string }> = {}
      for (const ws of wsList) {
        if (String(ws.id) === workspaceId) continue
        const wsTables = await tableApi.list(ws.id).catch(() => [])
        for (const t of wsTables) info[Number(t.id)] = { name: t.name, wsId: String(ws.id) }
      }
      if (!cancelled) setCrossTableInfo(prev => ({ ...info, ...prev }))
    }).catch(() => { /* 扫描失败静默，字段/预览退化为本工作区行为 */ })
    return () => { cancelled = true }
  }, [missingScan, workspaceId])

  // 主表归属工作区：本区表直接用当前工作区，跨工作区表（seed 模板等）经 crossTableInfo 解析
  const primaryTableWsId = selectedTableId !== null
    ? (crossTableInfo[selectedTableId]?.wsId ?? workspaceId)
    : workspaceId

  // 关联表的字段列表
  const { data: fields = [] } = useQuery<Field[]>({
    queryKey: ['workspaces', primaryTableWsId, 'tables', selectedTableId, 'fields'],
    queryFn: () => fieldApi.list(primaryTableWsId, selectedTableId!),
    enabled: !!selectedTableId,
  })

  // 额外表归属工作区是否全部解析（跨工作区表需等扫描补全后才能按正确工作区请求）
  const extrasResolved = extraTableIds.every(tid =>
    tables.some(t => t.id === tid) || !!crossTableInfo[tid])
  // 额外表归属工作区签名（进入 query key，解析结果变化时触发重新请求）
  const extraWsKey = extraTableIds.map(tid => crossTableInfo[tid]?.wsId ?? 'local').join(',')

  // 额外表的字段列表（批量加载；跨工作区表按其归属工作区请求）
  const { data: extraFieldsMap = {} } = useQuery<Record<number, Field[]>>({
    queryKey: ['workspaces', workspaceId, 'extra-fields', extraTableIds, extraWsKey],
    queryFn: async () => {
      const result: Record<number, Field[]> = {}
      await Promise.all(extraTableIds.map(async (tid) => {
        const wid = crossTableInfo[tid]?.wsId ?? workspaceId
        result[tid] = await fieldApi.list(wid, tid)
      }))
      return result
    },
    enabled: extraTableIds.length > 0 && extrasResolved,
  })

  // 关联表的前 10 行真实数据（用于预览；跨工作区主表按其归属工作区请求）
  const { data: previewRows = [], isLoading: previewLoading } = useQuery({
    queryKey: ['workspaces', primaryTableWsId, 'tables', selectedTableId, 'records', 'preview'],
    queryFn: async () => {
      const resp = await recordApi.list(primaryTableWsId, selectedTableId!, { limit: 10 })
      return resp.items.map(r => {
        const { id: _id, created_at: _ca, updated_at: _ua, created_by: _cb, updated_by: _ub, ...rest } = r as any
        return rest
      }) as Array<Record<string, unknown>>
    },
    enabled: !!selectedTableId && !!workspaceId,
  })

  // 额外表的预览数据（用于 PreviewPanel records_by_table；跨工作区表按其归属工作区请求）
  const { data: extraPreviewMap = {} } = useQuery<Record<number, Array<Record<string, unknown>>>>({
    queryKey: ['workspaces', workspaceId, 'extra-preview', extraTableIds, extraWsKey],
    queryFn: async () => {
      const result: Record<number, Array<Record<string, unknown>>> = {}
      await Promise.all(extraTableIds.map(async (tid) => {
        const wid = crossTableInfo[tid]?.wsId ?? workspaceId
        const resp = await recordApi.list(wid, tid, { limit: 5 })
        result[tid] = resp.items.map(r => {
          const { id: _id, created_at: _ca, updated_at: _ua, created_by: _cb, updated_by: _ub, ...rest } = r as any
          return rest
        })
      }))
      return result
    },
    enabled: extraTableIds.length > 0 && extrasResolved,
  })

  // Modal 打开时统一初始化所有表单值（在 Form.Items mount 之后，避免 destroyOnHidden 时序错乱）
  useEffect(() => {
    if (!open) return
    // 编辑态：从 editing 详情对象取；新建态：默认值
    if (editing) {
      form.setFieldsValue({
        name: editing.name,
        description: editing.description,
        output_format: editing.output_format ?? 'docx',
        template_content: editing.template_content,
        table_id: editing.table_id,
        parameters: (editing.parameters as ReportParameter[]).map(p => ({
          ...p,
          // options 数组转逗号分隔文本，供编辑器 Input 展示
          optionsText: (p.options ?? []).join(','),
        })) as ReportParameter[],
        theme: editing.theme ?? 'minimal',
        extra_table_ids: editing.extra_table_ids ?? [],
      })
      setExtraTableIds(editing.extra_table_ids ?? [])
    } else {
      form.setFieldsValue({
        name: '',
        description: '',
        output_format: 'docx',
        template_content: initialContent,
        table_id: null,
        parameters: [],
        theme: 'minimal',
        extra_table_ids: [],
      })
      setExtraTableIds([])
    }
    // 模板内容使用外部显式传入的 initialContent（与所点行绑定）
    setTemplateValue(initialContent)
    const tplId: number | null = form.getFieldValue('table_id') ?? null
    const extras: number[] = form.getFieldValue('extra_table_ids') || []
    setSelectedTableId(tplId)
    // 额外表多选框 value 同步 state（让 Form.List 的 select 有受控值）
    setExtraTableIds(extras)
    setImportWsId('')
    setImportTableId(null)
    // 每次打开弹窗回到编辑模式，避免上次停留在预览/帮助视图
    setViewMode('edit')
    // 新建态默认落在基本信息页签，编辑态默认落在模板编辑页签；清空错误标记
    setActiveTab(editing ? 'editor' : 'basic')
    setErroredTabs(new Set())
    setEditorVisited(Boolean(editing))
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

  // 页签切换（首次进入模板编辑页签时挂载编辑器，之后保持挂载）
  const handleTabChange = (key: string) => {
    if (key === 'editor') setEditorVisited(true)
    setActiveTab(key as EditorTabKey)
  }

  // 保存校验：失败时按字段→页签映射跳转并显示错误标记，成功后提交并清空标记
  const handleSave = () => {
    form.validateFields().then((v) => {
      setErroredTabs(new Set())
      handleFormFinish(v as Parameters<typeof handleFormFinish>[0])
    }).catch((err: { errorFields?: Array<{ name?: Array<string | number> }> }) => {
      const tabs = new Set<EditorTabKey>()
      for (const f of err.errorFields ?? []) {
        const tab = FIELD_TAB_MAP[String(f.name?.[0])]
        if (tab) tabs.add(tab)
      }
      setErroredTabs(tabs)
      // 跳到第一个含错误的页签
      const order: EditorTabKey[] = ['basic', 'editor']
      const first = order.find(t => tabs.has(t))
      if (first) {
        if (first === 'editor') setEditorVisited(true)
        setActiveTab(first)
      }
    })
  }

  // 保存校验（extra_table_ids 随模板持久化，含跨工作区表；输出格式/主题兜底默认值）
  // 表单参数额外携带 optionsText（编辑用），提交前转换为 options 数组
  const handleFormFinish = (v: Omit<ReportTemplateCreate, 'parameters'> & { parameters?: Array<ReportParameter & { optionsText?: string }> }) => {
    onSubmit({
      ...v,
      output_format: v.output_format ?? 'docx',
      theme: v.theme ?? 'minimal',
      template_content: templateValue,
      extra_table_ids: extraTableIds,
      // optionsText（逗号分隔字符串）→ options（字符串数组），与后端 ParameterDef 对齐
      parameters: (v.parameters ?? []).map(p => ({
        ...p,
        options: typeof p.optionsText === 'string' && p.optionsText.trim()
          ? p.optionsText.split(/[，,]/).map(s => s.trim()).filter(Boolean)
          : [],
      })),
    })
  }

  // 跨工作区表名解析：本区 tables 优先，其次 crossTableInfo（级联引入 + 回显扫描）
  const resolveTableName = (tid: number): string | undefined =>
    tables.find(t => t.id === tid)?.name ?? crossTableInfo[tid]?.name

  // 跨工作区引入：将级联选中的表加入额外引用表
  const handleImportCrossTable = () => {
    if (importTableId === null) return
    const t = importWsTables.find(x => x.id === importTableId)
    if (!t) return
    setCrossTableInfo(prev => ({ ...prev, [importTableId]: { name: t.name, wsId: importWsId } }))
    setExtraTableIds(prev => (prev.includes(importTableId) ? prev : [...prev, importTableId]))
    setImportTableId(null)
  }

  // 跨工作区级联选项（排除当前工作区——本区表直接在额外引用表里选）
  const importWsOptions = useMemo<Array<{ value: string; label: string }>>(
    () => workspaces.filter((w: Workspace) => String(w.id) !== workspaceId).map((w: Workspace) => ({ value: String(w.id), label: w.name })),
    [workspaces, workspaceId],
  )
  const importTableOptions = useMemo<Array<{ value: number; label: string }>>(
    () => importWsTables.filter(t => t.id !== selectedTableId).map(t => ({ value: Number(t.id), label: t.name })),
    [importWsTables, selectedTableId],
  )

  // 主表名解析：本区表优先，其次 crossTableInfo（跨工作区主表，如 seed 模板的关联表）
  const selectedTableName = selectedTableId !== null ? resolveTableName(selectedTableId) : undefined

  // 关联表下拉选项：本区表 + 跨工作区主表（避免编辑 seed 模板时仅显示 "#id"）
  const tableSelectOptions = useMemo(() => {
    if (selectedTableId === null) return tableOptions
    const existing = tableOptions.some(o => o.value === selectedTableId)
    if (existing) return tableOptions
    const name = resolveTableName(selectedTableId)
    if (name === undefined) return tableOptions
    return [{ value: selectedTableId, label: name }, ...tableOptions]
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tableOptions, selectedTableId, crossTableInfo, tables])

  // 构建多表字段分组
  const tableGroups = useMemo(() => {
    const groups: Array<{ tableId: number; tableName: string; fields: Field[]; isPrimary: boolean }> = []
    if (selectedTableId !== null && selectedTableName) {
      groups.push({ tableId: selectedTableId, tableName: selectedTableName, fields, isPrimary: true })
    }
    for (const eid of extraTableIds) {
      const tname = resolveTableName(eid)
      const efields = extraFieldsMap[eid] || []
      if (tname) {
        groups.push({ tableId: eid, tableName: tname, fields: efields, isPrimary: false })
      }
    }
    return groups
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedTableId, selectedTableName, fields, extraTableIds, extraFieldsMap, tables, crossTableInfo])

  // 构建 recordsByTable
  const recordsByTable = useMemo(() => {
    const result: Record<string, Array<Record<string, unknown>>> = {}
    for (const eid of extraTableIds) {
      const tname = resolveTableName(eid)
      if (tname && extraPreviewMap[eid]) {
        result[tname] = extraPreviewMap[eid]
      }
    }
    return result
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [extraTableIds, extraPreviewMap, tables, crossTableInfo])

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
      {/* 单一 Form：所有 Form.Items 共享一个 form 实例 + onFinish；内容按 Tabs 分两页签（页签标题在校验失败时叠加错误红点） */}
      <Form
        form={form}
        layout="vertical"
        style={{ padding: '12px 24px 0' }}
        onFinish={handleFormFinish}
      >
        <Tabs
          activeKey={activeTab}
          onChange={handleTabChange}
          items={[
            {
              key: 'basic',
              label: erroredTabs.has('basic') ? <Badge dot>基本信息</Badge> : '基本信息',
              forceRender: true,
              children: (
                <>
                  <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
                    <Form.Item name="name" label="模板名称" rules={[{ required: true, message: '请输入名称' }]} style={{ flex: '1 1 220px', marginBottom: 8 }}>
                      <Input placeholder="例如：月度销售汇总" />
                    </Form.Item>
                    <Form.Item name="output_format" label="输出格式" style={{ width: 150, marginBottom: 8 }}>
                      <Select options={FORMAT_OPTIONS} />
                    </Form.Item>
                    <Form.Item name="theme" label="主题风格" className="report-theme-row" style={{ width: 120, marginBottom: 8 }} tooltip="影响导出文档的标题/正文/表格样式">
                      {/* 选项仅 5 个，关闭虚拟滚动（jsdom 高度为 0 时虚拟列表渲染不全） */}
                      <Select options={THEME_OPTIONS} virtual={false} />
                    </Form.Item>
                    <Form.Item name="table_id" label="关联表" style={{ width: 220, marginBottom: 8 }}>
                      <Select
                        options={tableSelectOptions}
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
                  {/* 跨工作区引入：先点源工作区按钮，再从源表下拉选择，点「引入」加入额外引用表 */}
                  {importWsOptions.length > 0 && (
                    <div className="report-crossws-row" style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', marginBottom: 8 }}>
                      <Typography.Text type="secondary" style={{ fontSize: 12 }}>跨工作区引入：</Typography.Text>
                      {importWsOptions.map(o => (
                        <Button
                          key={o.value}
                          size="small"
                          type={importWsId === o.value ? 'primary' : 'default'}
                          onClick={() => { setImportWsId(o.value); setImportTableId(null) }}
                        >
                          {o.label}
                        </Button>
                      ))}
                      <Select
                        size="small"
                        style={{ minWidth: 180 }}
                        placeholder="跨工作区源表"
                        value={importTableId}
                        options={importTableOptions}
                        onChange={setImportTableId}
                        allowClear
                      />
                      <Button size="small" type="primary" disabled={importTableId === null} onClick={handleImportCrossTable}>引入</Button>
                    </div>
                  )}
                  <Form.Item name="description" label="描述（可选）" style={{ marginBottom: 8 }}>
                    <Input.TextArea rows={1} placeholder="简单说明这个模板的用途" />
                  </Form.Item>

                  {/* 模板参数定义区（整合进基本信息页签） */}
                  <Form.Item label="模板参数" tooltip="运行时传入的动态参数（可选）" style={{ marginBottom: 0 }}>
                    <Form.List name="parameters">
                      {(paramFields, { add, remove }) => (
                        <>
                          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 8 }}>
                            {paramFields.map(({ key, name, ...restField }) => (
                              /* 每行一个参数：默认值/显示名/选项用 flex 弹性宽度，长内容可完整展示 */
                              <div key={key} style={{ display: 'flex', gap: 8, alignItems: 'baseline', flexWrap: 'wrap', flexBasis: '100%' }}>
                                <Form.Item {...restField} name={[name, 'name']} rules={[{ required: true }]} style={{ width: 140, marginBottom: 4 }}>
                                  <Input placeholder="参数名" />
                                </Form.Item>
                                <Form.Item {...restField} name={[name, 'type']} style={{ width: 90, marginBottom: 4 }}>
                                  <Select options={PARAM_TYPES} />
                                </Form.Item>
                                <Form.Item {...restField} name={[name, 'default']} style={{ flex: '1 1 160px', minWidth: 160, marginBottom: 4 }}>
                                  <Input placeholder="默认值" />
                                </Form.Item>
                                <Form.Item {...restField} name={[name, 'label']} style={{ flex: '1 1 140px', minWidth: 140, marginBottom: 4 }}>
                                  <Input placeholder="显示名" />
                                </Form.Item>
                                <Form.Item {...restField} name={[name, 'optionsText']} tooltip="逗号分隔的可选值，非空时渲染时显示下拉菜单" style={{ flex: '2 1 220px', minWidth: 220, marginBottom: 4 }}>
                                  <Input placeholder="选项(逗号分隔)" />
                                </Form.Item>
                                {/* Select 用 value prop 而非 checked，移除 valuePropName="checked" */}
                                <Form.Item {...restField} name={[name, 'required']} style={{ width: 80, marginBottom: 4 }}>
                                  <Select options={[{ value: true, label: '必填' }, { value: false, label: '可选' }]} />
                                </Form.Item>
                                <Tooltip title="删除该参数">
                                  <Button type="text" danger icon={<DeleteOutlined />} onClick={() => remove(name)} />
                                </Tooltip>
                              </div>
                            ))}
                          </div>
                          <Button type="dashed" onClick={() => add({ name: '', type: 'string', default: null, label: '', required: false })} block icon={<PlusOutlined />}>
                            添加参数
                          </Button>
                        </>
                      )}
                    </Form.List>
                  </Form.Item>
                </>
              ),
            },
            {
              key: 'editor',
              label: erroredTabs.has('editor') ? <Badge dot>模板编辑</Badge> : '模板编辑',
              children: editorVisited ? (
                <>
                  {/* 编辑器主体：内部模式切换 + 字段面板/编辑器/预览单区切换 */}
                  <div className="report-editor-toolbar">
                    <Segmented
                      size="small"
                      value={viewMode}
                      onChange={(v) => setViewMode(v as 'edit' | 'preview' | 'help')}
                      options={[
                        { label: '编辑模板', value: 'edit' },
                        { label: '实时预览', value: 'preview' },
                        { label: '语法帮助', value: 'help' },
                      ]}
                    />
                  </div>
                  <div className="report-editor-body" style={{ height: 'min(56vh, 640px)' }}>
                    {/* 编辑视图：保持挂载，仅切换显示，保证内容与插入能力不丢失 */}
                    <div className="report-editor-editpane" style={{ display: viewMode === 'edit' ? undefined : 'none' }}>
                      <ReportTemplateEditor
                        fields={selectedTableId !== null ? (fields as Field[]) : undefined}
                        tableGroups={tableGroups.length > 0 ? tableGroups : undefined}
                        value={templateValue}
                        onChange={handleTemplateChange}
                        editorRef={editorRef}
                      />
                    </div>

                    {viewMode === 'preview' && (
                      <div className="report-editor-viewpane">
                        <PreviewPanel
                          template={templateValue}
                          records={previewRows as Array<Record<string, unknown>>}
                          tableName={selectedTableName}
                          loading={previewLoading}
                          recordsByTable={recordsByTable}
                        />
                      </div>
                    )}

                    {viewMode === 'help' && (
                      <div className="report-editor-viewpane">
                        <SyntaxHelpPanel
                          onInsert={(code) => {
                            window.dispatchEvent(new CustomEvent('report-editor-insert', { detail: { code } }))
                          }}
                        />
                      </div>
                    )}
                  </div>
                </>
              ) : null,
            },
          ]}
        />

        {/* 隐藏的 template_content 字段 — 实际值由 CodeMirror 控制 */}
        <Form.Item name="template_content" rules={[{ required: true, message: '请输入模板内容' }]} style={{ display: 'none' }}>
          <Input />
        </Form.Item>
      </Form>{/* 关闭单一 Form — Tabs 两页签（基本信息含模板参数 / 模板编辑） */}

      {/* 底部按钮区 */}
      <div style={{ padding: '12px 24px', borderTop: '1px solid var(--cn-border-soft)', textAlign: 'right' }}>
        <Space>
          <Button onClick={onClose}>取消</Button>
          <Button type="primary" loading={submitting} onClick={handleSave}>
            {editing ? '保存' : '创建'}
          </Button>
        </Space>
      </div>
    </Modal >
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
      // 默认带入模板已保存的额外引用表（含跨工作区表）
      setExtraTableIds(target.extra_table_ids ?? [])
    }
  }, [open, target, form])

  const tableNameMap = useMemo(() => new Map(tables.map(t => [t.id, t.name])), [tables])

  // 额外表选项（排除模板关联的主表；跨工作区表不在本区 tables，补占位选项避免选中值显示裸数字）
  const extraTableOptions = useMemo(() => {
    const base = target?.table_id ? tables.filter(t => t.id !== target.table_id) : tables
    const opts = base.map(t => ({ value: t.id, label: t.name }))
    for (const eid of target?.extra_table_ids ?? []) {
      if (!opts.some(o => o.value === eid)) opts.push({ value: eid, label: `跨工作区表 #${eid}` })
    }
    return opts
  }, [tables, target?.table_id, target?.extra_table_ids])

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
            ) : p.options && p.options.length > 0 ? (
              <Select options={p.options.map(o => ({ value: o, label: o }))} virtual={false} placeholder={`请选择 ${p.label || p.name}`} />
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
