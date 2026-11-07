/** 工作区「数据流程」二级模块（需求 0095 / 0097）.
 *
 * 模板驱动：多条端到端流程并列展示 → 流程步骤 → 绑定表单的列表 / 搜索 / 增删改；
 * 无表单步骤作为审批 / 确认节点展示。真正写操作复用 records API
 * （权限 / 修改申请 / 行级权限口径与数据表一致）。
 */

import { useEffect, useMemo, useState } from 'react'
import {
  Alert, App as AntApp, Button, Card, Empty, Input, Modal, Popconfirm, Space, Table, Tag, Typography,
} from 'antd'
import {
  ApartmentOutlined, AuditOutlined, DeleteOutlined, DownOutlined, EditOutlined, PlusOutlined,
  RightOutlined, SearchOutlined, TableOutlined, UpOutlined,
} from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate, useParams } from 'react-router-dom'
import { isChangeRequestResponse, recordApi, workspaceDataFlowApi } from '@/api'
import type {
  DataFlowField, DataFlowFlow, DataFlowForm, DataFlowStep, Field, RowResponse, RowValues,
  WorkspaceDataFlow,
} from '@/api'
import CnListMeta from '@/components/CnListMeta'
import SectionBox from '@/components/SectionBox'
import { FieldEditor } from '@/pages/grid/layout/RowDetailDrawer'
import { extractSelectOptions } from '@/pages/grid/cells/fieldOps'

const { Text, Paragraph } = Typography

const EMPTY_VALUE = (v: unknown) => v === null || v === undefined || v === '' || (Array.isArray(v) && v.length === 0)

function asField(field: DataFlowField): Field {
  return {
    id: field.name,
    name: field.name,
    field_type: field.field_type as Field['field_type'],
    required: field.required,
    config: field.config,
    order: field.order,
    hidden: field.hidden,
    default_value: field.default_value,
  }
}

function renderCell(field: DataFlowField | undefined, value: unknown) {
  if (!field) return value === null || value === undefined ? '—' : String(value)
  if (value === null || value === undefined || value === '') return <Text type="secondary">—</Text>
  const ft = field.field_type
  if (ft === 'boolean') return value ? '是' : '否'
  if (ft === 'percentage') {
    const n = Number(value)
    return Number.isFinite(n) ? `${(n * 100).toFixed(1)}%` : String(value)
  }
  if (ft === 'select') {
    const label = extractSelectOptions(field.config).find(o => o.value === String(value))?.label
    return <Tag>{label ?? String(value)}</Tag>
  }
  if (ft === 'multiselect' || ft === 'multi_select') {
    const arr = Array.isArray(value) ? value : String(value).split(',')
    return <Space size={2} wrap>{arr.map(v => <Tag key={String(v)}>{String(v)}</Tag>)}</Space>
  }
  if (ft === 'link') {
    const arr = Array.isArray(value) ? value : [value]
    return arr.map((v, i) => {
      const text = v && typeof v === 'object'
        ? String((v as { value?: unknown; id?: unknown }).value ?? (v as { id?: unknown }).id ?? '')
        : String(v)
      return <Tag key={`${text}-${i}`}>{text}</Tag>
    })
  }
  const text = String(value)
  return <span title={text}>{text.length > 60 ? `${text.slice(0, 60)}…` : text}</span>
}

function buildInitialValues(form: DataFlowForm, row?: RowResponse | null): RowValues {
  const values: RowValues = { ...form.flow.default_values }
  if (row) {
    for (const field of form.fields) values[field.name] = row[field.name]
    return values
  }
  for (const field of form.fields) {
    if (!(field.name in values) && field.default_value !== undefined && field.default_value !== null) {
      values[field.name] = field.default_value
    }
  }
  return values
}

/** 兼容旧后端：没有 flows 时按阶段派生「一阶段一流程」. */
function resolveFlows(data: WorkspaceDataFlow): DataFlowFlow[] {
  if (data.flows?.length) return data.flows
  return data.stages.map(stage => {
    const steps: DataFlowStep[] = stage.forms.length
      ? stage.forms.map(form => ({
          key: `${stage.key}-${form.key}`,
          name: form.name,
          description: form.description,
          form,
          documents: [],
        }))
      : [{
          key: `${stage.key}-steps`,
          name: stage.name,
          description: stage.description,
          form: null,
          documents: [],
        }]
    return {
      key: `stage-${stage.key}`,
      name: stage.name,
      description: stage.description,
      steps,
      form_count: stage.forms.length,
      step_count: steps.length,
      record_count: stage.forms.reduce((sum, form) => sum + form.record_count, 0),
    }
  })
}

export default function DataFlowPage() {
  const { wid } = useParams<{ wid: string }>()
  const { message } = AntApp.useApp()
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const { data, isLoading, error } = useQuery<WorkspaceDataFlow>({
    queryKey: ['workspace-data-flow', wid],
    queryFn: () => workspaceDataFlowApi.get(wid!),
    enabled: !!wid,
    retry: false,
  })

  const flows = useMemo(() => (data ? resolveFlows(data) : []), [data])
  const [flowKey, setFlowKey] = useState<string | null>(null)
  const [stepKey, setStepKey] = useState<string | null>(null)
  const [expandedKeys, setExpandedKeys] = useState<string[]>([])
  const [initialized, setInitialized] = useState(false)
  const [search, setSearch] = useState('')
  const [editorOpen, setEditorOpen] = useState(false)
  const [editingRow, setEditingRow] = useState<RowResponse | null>(null)
  const [values, setValues] = useState<RowValues>({})
  const [valueError, setValueError] = useState<string | null>(null)

  useEffect(() => {
    if (!flows.length) return
    if (!flowKey || !flows.some(f => f.key === flowKey)) setFlowKey(flows[0].key)
  }, [flows, flowKey])

  // 首次进入展开第一条流程，保证右侧内容在左侧有对应的子过程节点
  useEffect(() => {
    if (!data || initialized || !flows.length) return
    setExpandedKeys([flows[0].key])
    setInitialized(true)
  }, [data, flows, initialized])

  const flow = flows.find(f => f.key === flowKey) ?? flows[0]

  useEffect(() => {
    if (!flow) return
    if (!stepKey || !flow.steps.some(s => s.key === stepKey)) {
      setStepKey(flow.steps[0]?.key ?? null)
    }
  }, [flow, stepKey])

  const step = flow?.steps.find(s => s.key === stepKey) ?? flow?.steps[0]
  const form = step?.form ?? null
  const fieldMap = useMemo(() => new Map((form?.fields ?? []).map(f => [f.name, f])), [form])

  const rowsQuery = useQuery({
    queryKey: ['data-flow-rows', wid, form?.table_id, form?.flow.default_sort],
    queryFn: () => recordApi.list(wid!, form!.table_id!, {
      limit: 500,
      sorts: form!.flow.default_sort
        ? [{ field_name: form!.flow.default_sort.field, direction: form!.flow.default_sort.order }]
        : undefined,
    }),
    enabled: !!wid && !!form?.table_id,
  })

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['workspace-data-flow', wid] })
    queryClient.invalidateQueries({ queryKey: ['data-flow-rows', wid] })
  }

  const save = useMutation({
    mutationFn: async () => {
      if (!form?.table_id) throw new Error('表单未映射到数据表')
      // 列表响应会按角色剔除隐藏字段：响应里没有该字段的键，不能当成「用户清空」，
      // 否则编辑任一记录都会把当前用户看不到的字段静默写成 NULL（数据丢失）。
      const editableFields = editingRow
        ? form.fields.filter(f => f.name in editingRow)
        : form.fields
      const payload: RowValues = {}
      for (const field of editableFields) {
        const value = values[field.name]
        if (field.field_type === 'lookup') continue
        if (!EMPTY_VALUE(value)) payload[field.name] = value
        else if (editingRow) payload[field.name] = null
      }
      const missing = editableFields
        .filter(f => f.required && f.field_type !== 'lookup' && EMPTY_VALUE(values[f.name]))
        .map(f => f.name)
      if (missing.length) throw new Error(`请填写必填字段：${missing.join('、')}`)
      return editingRow
        ? recordApi.update(wid!, form.table_id, editingRow.id, { values: payload })
        : recordApi.create(wid!, form.table_id, { values: payload })
    },
    onSuccess: (res) => {
      if (isChangeRequestResponse(res)) message.success('已提交修改申请，审批后生效')
      else message.success(editingRow ? '记录已更新' : '记录已创建')
      setEditorOpen(false)
      setEditingRow(null)
      invalidate()
    },
    onError: (err) => setValueError(err instanceof Error ? err.message : '保存失败'),
  })

  const remove = useMutation({
    mutationFn: (row: RowResponse) => recordApi.remove(wid!, form!.table_id!, row.id),
    onSuccess: (res) => {
      if (isChangeRequestResponse(res)) message.success('已提交删除申请，审批后生效')
      else message.success('记录已删除')
      invalidate()
    },
    onError: (err) => message.error(err instanceof Error ? err.message : '删除失败'),
  })

  const selectFlow = (key: string) => {
    setFlowKey(key)
    setSearch('')
    const next = flows.find(f => f.key === key)
    if (next && !next.steps.some(s => s.key === stepKey)) {
      setStepKey(next.steps[0]?.key ?? null)
    }
  }

  const toggleFlow = (key: string) => {
    setExpandedKeys(prev => (prev.includes(key) ? prev.filter(k => k !== key) : [...prev, key]))
    selectFlow(key)
  }

  const selectStep = (nextFlowKey: string, nextStepKey: string) => {
    setFlowKey(nextFlowKey)
    setStepKey(nextStepKey)
    setSearch('')
    setExpandedKeys(prev => (prev.includes(nextFlowKey) ? prev : [...prev, nextFlowKey]))
  }

  const rows = rowsQuery.data?.items ?? []
  const q = search.trim().toLowerCase()
  const filteredRows = q && form
    ? rows.filter(row => form.flow.search_fields.some(name => {
      const value = row[name]
      const text = Array.isArray(value)
        ? value.map(v => (v && typeof v === 'object' ? ((v as { value?: unknown }).value ?? '') : v)).join(' ')
        : String(value ?? '')
      return text.toLowerCase().includes(q)
    }))
    : rows

  const openCreate = () => {
    if (!form) return
    setEditingRow(null)
    setValues(buildInitialValues(form))
    setValueError(null)
    setEditorOpen(true)
  }

  const openEdit = (row: RowResponse) => {
    if (!form) return
    setEditingRow(row)
    setValues(buildInitialValues(form, row))
    setValueError(null)
    setEditorOpen(true)
  }

  const allExpanded = flows.length > 0 && flows.every(f => expandedKeys.includes(f.key))
  const toggleAll = () => setExpandedKeys(allExpanded ? [] : flows.map(f => f.key))
  const currentStageLabel = flow?.stage_name
    ?? data?.stages.find(stage => stage.key === data.current_stage)?.name
    ?? '—' 

  if (isLoading) return <div className="cn-state">加载中…</div>

  if (error || !data) {
    const msg = error instanceof Error ? error.message : ''
    return (
      <div style={{ padding: 16 }} data-testid="data-flow-unavailable">
        <Empty description="数据流程需要工作区使用模板">
          <Paragraph type="secondary">
            {msg || '当前工作区未绑定模板。使用模板后，可在「数据流程」中按流程与步骤填写表单、查看与维护记录。'}
          </Paragraph>
          <Space>
            <Button type="primary" onClick={() => navigate(`/w/${wid}/settings`)}>去工作区设置选择模板</Button>
            <Button onClick={() => navigate('/templates')}>浏览模板</Button>
          </Space>
        </Empty>
      </div>
    )
  }

  const columns = form ? [
    ...form.flow.list_fields.map(name => ({
      title: fieldMap.get(name)?.name ?? name,
      dataIndex: name,
      key: name,
      ellipsis: true,
      render: (value: unknown) => renderCell(fieldMap.get(name), value),
    })),
    ...(form.can_edit || form.can_delete ? [{
      title: '操作',
      key: '__actions',
      width: 150,
      render: (_: unknown, row: RowResponse) => (
        <Space size={4}>
          {form.can_edit && (
            <Button size="small" type="link" icon={<EditOutlined />} onClick={() => openEdit(row)}>编辑</Button>
          )}
          {form.can_delete && (
            <Popconfirm title="删除这条记录？" okText="删除" cancelText="取消" onConfirm={() => remove.mutate(row)}>
              <Button size="small" type="link" danger icon={<DeleteOutlined />}>删除</Button>
            </Popconfirm>
          )}
        </Space>
      ),
    }] : []),
  ] : []

  return (
    <div className="cn-page cn-qc-page" data-testid="data-flow-page">
      <header className="cn-page-head">
        <div className="cn-page-head-main">
          <span className="cn-page-head-icon" aria-hidden><ApartmentOutlined /></span>
          <div className="cn-page-head-text">
            <h1 className="cn-page-head-title">数据流程</h1>
            <div className="cn-page-head-sub">
              <span className="cn-page-head-meta">
                {data.template_name} · 当前阶段 {currentStageLabel} · {flows.length} 条流程
              </span>
            </div>
          </div>
        </div>
      </header>

      {!flows.length ? (
        <SectionBox title="流程图" icon={<ApartmentOutlined />}>
          <div className="cn-qc-empty"><Empty description="模板还没有配置端到端流程" /></div>
        </SectionBox>
      ) : (
        <div className="cn-qc-split cn-flow-split" data-testid="data-flow-split">
          {/* 左栏：流程图（大过程 → 子过程的嵌套列表） */}
          <SectionBox
            title="流程图"
            icon={<ApartmentOutlined />}
            extra={(
              <Space size={4}>
                <span>共 {flows.length} 条</span>
                <Button
                  size="small"
                  icon={allExpanded ? <UpOutlined /> : <DownOutlined />}
                  aria-label={allExpanded ? '收起全部子过程' : '展开全部子过程'}
                  title={allExpanded ? '收起全部子过程' : '展开全部子过程'}
                  data-testid="data-flow-toggle-all"
                  onClick={toggleAll}
                />
              </Space>
            )}
            flush
            testId="data-flow-diagram"
            className="cn-flow-diagram-box"
          >
            {flows.map(item => {
              const open = expandedKeys.includes(item.key)
              const isActiveFlow = item.key === flow?.key
              return (
                <div key={item.key}>
                  <div
                    className={[
                      'cn-list-item',
                      'cn-qc-row',
                      'cn-qc-row--selectable',
                      'cn-flow-diagram-flow',
                      isActiveFlow ? 'cn-qc-row--active' : '',
                    ].filter(Boolean).join(' ')}
                    data-testid={`data-flow-card-${item.key}`}
                    aria-expanded={open}
                    onClick={() => toggleFlow(item.key)}
                  >
                    <div className="cn-list-item-main">
                      <CnListMeta
                        avatar={(
                          <span className="cn-flow-diagram-flow-icon" aria-hidden>
                            <ApartmentOutlined />
                          </span>
                        )}
                        title={(
                          <Space size={8} wrap>
                            <Text strong className="cn-flow-diagram-flow-name">{item.name}</Text>
                            <Tag color="default">一级</Tag>
                            {item.key === 'project_lifecycle' && <Tag color="gold">主流程</Tag>}
                          </Space>
                        )}
                        description={(
                          <Text type="secondary" className="cn-flow-diagram-flow-meta">
                            {item.step_count} 个子过程 · {item.form_count} 个表单
                          </Text>
                        )}
                      />
                    </div>
                    <div className="cn-list-item-actions">
                      <span className="cn-flow-diagram-chevron" aria-hidden>
                        {open ? <DownOutlined /> : <RightOutlined />}
                      </span>
                    </div>
                  </div>
                  {open && (
                    <div data-testid={`data-flow-steps-${item.key}`}>
                      {item.steps.map((child, stepNo) => {
                        const isActiveStep = isActiveFlow && child.key === step?.key
                        return (
                          <div
                            key={child.key}
                            className={[
                              'cn-list-item',
                              'cn-qc-row',
                              'cn-qc-row--selectable',
                              'cn-flow-diagram-step',
                              isActiveStep ? 'cn-qc-row--active' : '',
                            ].filter(Boolean).join(' ')}
                            data-testid={`data-flow-step-${child.key}`}
                            aria-current={isActiveStep ? 'step' : undefined}
                            onClick={() => selectStep(item.key, child.key)}
                          >
                            <div className="cn-list-item-main">
                              <CnListMeta
                                avatar={(
                                  <span
                                    className={`cn-flow-diagram-step-icon${child.form ? ' is-form' : ' is-approval'}`}
                                    aria-hidden
                                  >
                                    {child.form ? <TableOutlined /> : <AuditOutlined />}
                                  </span>
                                )}
                                title={<Text className="cn-flow-diagram-step-title">{child.name}</Text>}
                                description={(
                                  <Text type="secondary" className="cn-flow-diagram-step-meta">
                                    第 {stepNo + 1} 步 · {child.form ? `${child.form.name} · ${child.form.record_count} 条` : '审批 / 确认节点'}
                                  </Text>
                                )}
                              />
                            </div>
                          </div>
                        )
                      })}
                    </div>
                  )}
                </div>
              )
            })}
          </SectionBox>

          {/* 右栏：当前子过程的数据维护 */}
          <SectionBox
            title={step ? `${flow?.name ?? '—'} / ${step.name}` : '数据维护'}
            icon={form ? <TableOutlined /> : <AuditOutlined />}
            extra={form ? (
              <Space size={6} wrap>
                <Input
                  allowClear
                  prefix={<SearchOutlined />}
                  placeholder={`搜索 ${form.flow.search_fields.join(' / ') || '记录'}`}
                  value={search}
                  onChange={e => setSearch(e.target.value)}
                  style={{ width: 200 }}
                  data-testid="data-flow-search"
                />
                <Tag>{form.record_count} 条记录</Tag>
                {form.can_create && (
                  <Button type="primary" size="small" icon={<PlusOutlined />} onClick={openCreate} data-testid="data-flow-create">
                    新建
                  </Button>
                )}
              </Space>
            ) : <Tag color="orange">审批 / 确认</Tag>}
            testId="data-flow-content"
            className="cn-flow-detail-box"
          >
            {!step || !form ? (
              <div className="cn-qc-empty" data-testid="data-flow-step-info">
                <Empty description={step?.description || '该子过程为审批 / 确认节点，无表单数据'} />
              </div>
            ) : (
              <>
                {step.description && (
                  <div className="cn-flow-content-toolbar">
                    <Text type="secondary">{step.description}</Text>
                  </div>
                )}
                <Table
                  size="small"
                  rowKey="id"
                  loading={rowsQuery.isLoading}
                  dataSource={filteredRows}
                  columns={columns}
                  pagination={{ pageSize: 20, showSizeChanger: false }}
                  locale={{ emptyText: form.flow.empty_text || '还没有记录，点击右上角新建' }}
                  scroll={{ x: 'max-content' }}
                  data-testid="data-flow-table"
                />
                {(rowsQuery.data?.total ?? 0) > rows.length && (
                  <Text type="secondary" style={{ fontSize: 'var(--cn-text-xs)' }}>
                    仅显示前 {rows.length} 条（共 {rowsQuery.data?.total} 条），完整数据请到数据表查看。
                  </Text>
                )}
              </>
            )}
          </SectionBox>
        </div>
      )}

      <Modal
        title={editingRow ? `编辑${form?.name ?? '记录'}` : `新建${form?.name ?? '记录'}`}
        open={editorOpen}
        onCancel={() => setEditorOpen(false)}
        onOk={() => { setValueError(null); save.mutate() }}
        okText="保存"
        cancelText="取消"
        confirmLoading={save.isPending}
        width={720}
        destroyOnHidden
        data-testid="data-flow-editor"
      >
        {form && (
          <div>
            {valueError && <Alert type="error" showIcon message={valueError} style={{ marginBottom: 10 }} />}
            {form.flow.form_groups.map(group => (
              <Card key={group.title} size="small" title={group.title} style={{ marginBottom: 10 }}>
                {group.fields.map(name => {
                  const field = fieldMap.get(name)
                  if (!field) return null
                  return (
                    <div key={name} style={{ marginBottom: 10 }}>
                      <div style={{ marginBottom: 4, fontSize: 'var(--cn-text-sm)' }}>
                        <Text strong>{name}</Text>
                        {field.required && <Text type="danger"> *</Text>}
                        {form.flow.hints[name] && <Text type="secondary"> · {form.flow.hints[name]}</Text>}
                      </div>
                      <FieldEditor
                        field={asField(field)}
                        value={values[name]}
                        onChange={v => setValues(prev => ({ ...prev, [name]: v }))}
                        wid={wid!}
                        tableId={form.table_id ?? undefined}
                        rowId={editingRow?.id}
                      />
                    </div>
                  )
                })}
              </Card>
            ))}
          </div>
        )}
      </Modal>
    </div>
  )
}
