/** 报表模板页 — 模板 CRUD + 渲染下载入口.
 *
 * 编辑器与渲染参数弹窗各自独立成模块（体积大且仅在交互时打开），
 * 编辑器内部继续懒加载 CodeMirror 相关组件。
 */

import React, { useMemo } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { Table, Button, Space, Tag, Form, Typography, App as AntApp, Dropdown, Empty, Tooltip } from 'antd'
import { PlusOutlined, DeleteOutlined, EditOutlined, DownloadOutlined, ArrowLeftOutlined, MoreOutlined, FileTextOutlined, BarChartOutlined } from '@ant-design/icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { reportApi, tableApi } from '@/api'
import type { ReportTemplate, ReportTemplateSummary, ReportTemplateCreate, ReportTemplateUpdate, ReportParameter } from '@/api'
import dayjs from 'dayjs'
import { FORMAT_OPTIONS } from './reportsConstants'
import { TemplateEditor } from './TemplateEditorModal'
import { RenderParamsModal } from './RenderParamsModal'

const { Title, Text } = Typography

export default function ReportsPage() {
  const { message, modal } = AntApp.useApp()
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
    // 按 workspace_id 过滤：仅显示当前工作区拥有的报表模板（wid 缺省时后端返回全量）
    queryKey: ['report-templates', wid],
    queryFn: () => reportApi.list(wid ? { workspace_id: Number(wid) } : undefined),
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
      // 工作区列表缓存含 report_count，新建后同步刷新 tab 徽标
      queryClient.invalidateQueries({ queryKey: ['workspaces'] })
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
      // update 可变更归属表进而影响归属工作区，同步刷新徽标
      queryClient.invalidateQueries({ queryKey: ['workspaces'] })
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
      // 工作区列表缓存含 report_count，删除后同步刷新 tab 徽标
      queryClient.invalidateQueries({ queryKey: ['workspaces'] })
    },
    onError: (err) => message.error(err instanceof Error ? err.message : '删除模板失败'),
  })

  const renderReport = useMutation({
    mutationFn: async (arg: { tpl: ReportTemplateSummary; params: Record<string, unknown>; extraTableIds?: number[]; viewId?: number | null }) => {
      const { tpl, params, extraTableIds = [], viewId } = arg
      if (!wid) throw new Error('缺少 workspace')
      const body: Record<string, unknown> = { table_id: tpl.table_id ?? 0, params }
      if (viewId != null) {
        body.view_id = viewId
      }
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
    setInitialContent('# {{ table_name }} 报告\n共 {{ records | length }} 条记录\n\n{% for row in records %}- {{ row.name }}\n{% endfor %}')
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
                    modal.confirm({
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
            <Title level={3} style={{ margin: 0 }}><BarChartOutlined style={{ marginRight: 8 }} />报表模板</Title>
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
        wid={wid}
        onClose={() => { setRenderParamsOpen(false); setRenderTarget(null) }}
        onSubmit={(params, extraTableIds, viewId) => {
          if (!renderTarget) return
          renderReport.mutate(
            { tpl: renderTarget, params, extraTableIds, viewId },
            { onSuccess: () => { setRenderParamsOpen(false); setRenderTarget(null) } },
          )
        }}
        submitting={renderReport.isPending}
      />
    </div>
  )
}
