/** 工作区「数据流程」二级模块（需求 0095）.
 *
 * 模板驱动：阶段 → 表单 → 可配置列表 / 搜索 / 分组表单 / 增删改；
 * 真正写操作复用 records API（权限 / 修改申请 / 行级权限口径与数据表一致）。
 */

import { useEffect, useMemo, useState } from 'react'
import {
  Alert, App as AntApp, Button, Card, Empty, Input, Modal, Popconfirm, Segmented, Space,
  Steps, Table, Tag, Typography,
} from 'antd'
import {
  ApartmentOutlined, DeleteOutlined, EditOutlined, PlusOutlined, ReloadOutlined, SearchOutlined,
} from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate, useParams } from 'react-router-dom'
import { isChangeRequestResponse, recordApi, workspaceDataFlowApi } from '@/api'
import type { DataFlowField, DataFlowForm, Field, RowResponse, RowValues, WorkspaceDataFlow } from '@/api'
import { FieldEditor } from '@/pages/grid/layout/RowDetailDrawer'
import { extractSelectOptions } from '@/pages/grid/cells/fieldOps'

const { Title, Text, Paragraph } = Typography

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

  const [stageKey, setStageKey] = useState<string | null>(null)
  const [formKey, setFormKey] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [editorOpen, setEditorOpen] = useState(false)
  const [editingRow, setEditingRow] = useState<RowResponse | null>(null)
  const [values, setValues] = useState<RowValues>({})
  const [valueError, setValueError] = useState<string | null>(null)

  useEffect(() => {
    if (!data) return
    if (!stageKey || !data.stages.some(s => s.key === stageKey)) {
      setStageKey(data.stages.find(s => s.is_current)?.key ?? data.stages[0]?.key ?? null)
    }
  }, [data, stageKey])

  const stage = data?.stages.find(s => s.key === stageKey) ?? data?.stages[0]
  const stageIndex = data ? Math.max(0, data.stages.findIndex(s => s.key === stage?.key)) : 0

  useEffect(() => {
    if (!stage) return
    if (!formKey || !stage.forms.some(f => f.key === formKey)) {
      setFormKey(stage.forms[0]?.key ?? null)
    }
  }, [stage, formKey])

  const form = stage?.forms.find(f => f.key === formKey) ?? stage?.forms[0]
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
      const payload: RowValues = {}
      for (const field of form.fields) {
        const value = values[field.name]
        if (field.field_type === 'lookup') continue
        if (!EMPTY_VALUE(value)) payload[field.name] = value
        else if (editingRow) payload[field.name] = null
      }
      const missing = form.fields
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

  if (isLoading) return <div className="cn-state">加载中…</div>

  if (error || !data) {
    const msg = error instanceof Error ? error.message : ''
    return (
      <div style={{ padding: 16 }} data-testid="data-flow-unavailable">
        <Empty description="数据流程需要工作区使用模板">
          <Paragraph type="secondary">
            {msg || '当前工作区未绑定模板。使用模板后，可在「数据流程」中按阶段填写表单、查看与维护记录。'}
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

  const stageItems = data.stages.map(s => ({
    title: s.name,
    description: (
      <span>
        {s.gate_satisfied ? <Tag color="green">门禁已通过</Tag> : <Tag color="orange">门禁未通过</Tag>}
        {s.is_current && <Tag color="blue">当前阶段</Tag>}
      </span>
    ),
    status: s.is_completed ? 'finish' as const : s.is_current ? 'process' as const : 'wait' as const,
  }))

  return (
    <div style={{ padding: 16, maxWidth: 1200, margin: '0 auto' }} data-testid="data-flow-page">
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap', marginBottom: 12 }}>
        <div>
          <Title level={3} style={{ marginBottom: 2 }}><ApartmentOutlined /> 数据流程</Title>
          <Text type="secondary">
            模板：{data.template_name} · 当前阶段 {data.stages.find(s => s.key === data.current_stage)?.name ?? '—'}
          </Text>
        </div>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={() => rowsQuery.refetch()} loading={rowsQuery.isFetching}>刷新</Button>
        </Space>
      </div>

      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 12 }}
        message="按流程录入：先选阶段，再选表单；列表可按模板配置的字段搜索与展示。"
        description="阶段推进与门禁在「工作区设置 → 生命周期」执行；本页只负责表单数据的增删查改。"
      />

      <Steps
        current={stageIndex}
        items={stageItems}
        onChange={index => setStageKey(data.stages[index]?.key ?? null)}
        style={{ marginBottom: 16, overflowX: 'auto' }}
      />

      {!stage || stage.forms.length === 0 ? (
        <Card><Empty description="该阶段没有可在数据流程中维护的表单" /></Card>
      ) : (
        <>
          <Space wrap style={{ marginBottom: 10 }}>
            {stage.forms.length > 1 && (
              <Segmented
                value={form?.key}
                onChange={value => { setFormKey(String(value)); setSearch('') }}
                options={stage.forms.map(f => ({ value: f.key, label: `${f.name}（${f.record_count}）` }))}
              />
            )}
            <Input
              allowClear
              prefix={<SearchOutlined />}
              placeholder={`搜索 ${form?.flow.search_fields.join(' / ') || '记录'}`}
              value={search}
              onChange={e => setSearch(e.target.value)}
              style={{ width: 300 }}
              data-testid="data-flow-search"
            />
            {form?.can_create && (
              <Button type="primary" icon={<PlusOutlined />} onClick={openCreate} data-testid="data-flow-create">
                新建{form?.name ?? '记录'}
              </Button>
            )}
          </Space>

          {form && (
            <Card
              size="small"
              title={<Space><span>{form.name}</span><Tag>{form.record_count} 条</Tag></Space>}
              extra={<Text type="secondary">{form.description}</Text>}
            >
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
                <Text type="secondary" style={{ fontSize: 12 }}>
                  当前仅加载前 {rows.length} 条（共 {rowsQuery.data?.total} 条），完整数据请到数据表查看。
                </Text>
              )}
            </Card>
          )}
        </>
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
                      <div style={{ marginBottom: 4, fontSize: 13 }}>
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
