/** 表单运行器页 — 基于表单元数据的数据录入 / 行列表 / 行编辑 / 行删除.
 *
 * 行操作全部委托 forms rows API（后端复用 records service），
 * 行级过滤与审计行为与 records API 一致；操作按钮由 meta.can_* 驱动。
 */

import { useMemo, useState } from 'react'
import { useParams } from 'react-router-dom'
import {
  Alert, App as AntApp, Button, Drawer, Form, Space, Spin, Table, Tag, Typography,
} from 'antd'
import { ArrowLeftOutlined, AuditOutlined, DeleteOutlined, EditOutlined, PlusOutlined } from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import dayjs from 'dayjs'
import { formApi } from '@/api'
import type { FormMeta, RowResponse } from '@/api'
import { isApprovalSubmitResponse } from '@/api'
import { FormFieldControl } from './fieldRenderer'

const { Title, Text } = Typography

const PAGE_SIZE = 20

/** 行值展示格式化：空值占位、布尔转是/否、数组顿号连接、对象 JSON 化 */
function displayValue(v: unknown): string {
  if (v === null || v === undefined || v === '') return '—'
  if (Array.isArray(v)) return v.map(x => displayValue(x)).join('、')
  if (typeof v === 'boolean') return v ? '是' : '否'
  if (typeof v === 'object') return JSON.stringify(v)
  return String(v)
}

/** dayjs 值序列化：date 输出 YYYY-MM-DD，datetime 输出 ISO 字符串 */
function serializeValue(fieldType: string | undefined, v: unknown): unknown {
  if (dayjs.isDayjs(v)) {
    return fieldType === 'date' ? v.format('YYYY-MM-DD') : v.toISOString()
  }
  return v
}

/** 日期类字段初始值：ISO 字符串转 dayjs 供 DatePicker 回显 */
function toControlValue(fieldType: string | undefined, v: unknown): unknown {
  if (v && (fieldType === 'date' || fieldType === 'datetime') && typeof v === 'string') {
    return dayjs(v)
  }
  return v
}

export default function FormRunnerPage() {
  const { message, modal } = AntApp.useApp()
  const { wid, formId } = useParams<{ wid: string; formId: string }>()
  const queryClient = useQueryClient()

  const [page, setPage] = useState({ current: 1, pageSize: PAGE_SIZE })
  const [editingRow, setEditingRow] = useState<RowResponse | null>(null)
  const [creating, setCreating] = useState(false)
  const [form] = Form.useForm()

  const metaQ = useQuery<FormMeta>({
    queryKey: ['form', wid, formId, 'meta'],
    queryFn: () => formApi.meta(wid!, formId!),
    enabled: !!wid && !!formId,
  })

  const offset = (page.current - 1) * page.pageSize
  const rowsQ = useQuery({
    queryKey: ['form', wid, formId, 'rows', offset, page.pageSize],
    queryFn: () => formApi.listRows(wid!, formId!, page.pageSize, offset),
    enabled: !!wid && !!formId,
  })

  const invalidateRows = () => {
    void queryClient.invalidateQueries({ queryKey: ['form', wid, formId, 'rows'] })
  }

  const createRow = useMutation({
    mutationFn: (values: Record<string, unknown>) => formApi.createRow(wid!, formId!, values),
    onSuccess: (resp) => {
      // 绑定审批流：提交进入审批而非直接落库，不刷新行列表
      if (isApprovalSubmitResponse(resp)) {
        message.success(`已提交审批（${resp.approval.workflow_name}），等待审批人处理`)
      } else {
        message.success('提交成功')
        invalidateRows()
      }
      setCreating(false)
      form.resetFields()
    },
    onError: (err) => message.error(err instanceof Error ? err.message : '提交失败'),
  })

  const updateRow = useMutation({
    mutationFn: ({ rowId, values }: { rowId: number | string; values: Record<string, unknown> }) =>
      formApi.updateRow(wid!, formId!, rowId, values),
    onSuccess: () => {
      message.success('已保存')
      setEditingRow(null)
      invalidateRows()
    },
    onError: (err) => message.error(err instanceof Error ? err.message : '保存失败'),
  })

  const deleteRow = useMutation({
    mutationFn: (rowId: number | string) => formApi.deleteRow(wid!, formId!, rowId),
    onSuccess: () => {
      message.success('已删除')
      invalidateRows()
    },
    onError: (err) => message.error(err instanceof Error ? err.message : '删除失败'),
  })

  const meta = metaQ.data
  const fields = useMemo(() => meta?.fields ?? [], [meta])

  const confirmDelete = (row: RowResponse) => {
    modal.confirm({
      title: '删除这条数据？',
      content: '删除后不可恢复。',
      okText: '删除', okType: 'danger', cancelText: '取消',
      onOk: () => deleteRow.mutate(row.id),
    })
  }

  const openEdit = (row: RowResponse) => {
    setEditingRow(row)
    const init: Record<string, unknown> = {}
    for (const f of fields) init[f.field_name] = toControlValue(f.field_type, row[f.field_name])
    form.setFieldsValue(init)
  }

  const openCreate = () => {
    setCreating(true)
    const init: Record<string, unknown> = {}
    for (const f of fields) {
      init[f.field_name] = f.default_value !== undefined && f.default_value !== null
        ? toControlValue(f.field_type, f.default_value)
        : undefined
    }
    form.setFieldsValue(init)
  }

  const handleFinish = (raw: Record<string, unknown>) => {
    const values: Record<string, unknown> = {}
    for (const f of fields) {
      values[f.field_name] = serializeValue(f.field_type, raw[f.field_name])
    }
    if (editingRow) updateRow.mutate({ rowId: editingRow.id, values })
    else createRow.mutate(values)
  }

  if (metaQ.isLoading) {
    return <div style={{ padding: 48, textAlign: 'center' }}><Spin /></div>
  }
  if (metaQ.isError || !meta) {
    return (
      <div style={{ padding: 24 }}>
        <Alert type="error" showIcon message="表单不存在或无权访问" />
      </div>
    )
  }

  const columns = [
    ...fields.map(f => ({
      title: f.label || f.field_name,
      key: f.field_name,
      dataIndex: f.field_name,
      ellipsis: true,
      render: (v: unknown) => displayValue(v),
    })),
    {
      title: '操作',
      key: 'actions',
      width: 140,
      render: (_: unknown, row: RowResponse) => (
        <Space size="small">
          {meta.can_edit && (
            <Button size="small" type="link" icon={<EditOutlined />} onClick={() => openEdit(row)}>编辑</Button>
          )}
          {meta.can_delete && (
            <Button
              size="small" type="link" danger icon={<DeleteOutlined />}
              aria-label={`删除第 ${row.id} 行`} onClick={() => confirmDelete(row)}
            />
          )}
        </Space>
      ),
    },
  ]

  const total = rowsQ.data?.total ?? 0

  return (
    <div style={{ padding: 24 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 4 }}>
        <Button type="text" icon={<ArrowLeftOutlined />} aria-label="返回表单列表" onClick={() => window.history.back()} />
        <Title level={3} style={{ margin: 0 }}>{meta.name}</Title>
        <Tag color="blue">{meta.table_name}</Tag>
        {meta.approval_workflow_id && (
          <Tag color="gold" icon={<AuditOutlined />}>提交需审批</Tag>
        )}
      </div>
      {meta.description && (
        <Text type="secondary" style={{ display: 'block', marginBottom: 12 }}>{meta.description}</Text>
      )}

      {meta.invalid_fields.length > 0 && (
        <Alert
          type="warning" showIcon style={{ marginBottom: 12 }}
          message={`以下字段已失效，未参与本次表单渲染：${meta.invalid_fields.join('、')}`}
        />
      )}

      {meta.can_submit && (
        <div style={{ marginBottom: 12 }}>
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新增数据</Button>
        </div>
      )}

      <Table
        rowKey="id"
        size="middle"
        loading={rowsQ.isLoading}
        columns={columns}
        dataSource={rowsQ.data?.rows ?? []}
        pagination={{
          current: page.current,
          pageSize: page.pageSize,
          total,
          showSizeChanger: false,
          onChange: (current) => setPage(p => ({ ...p, current })),
        }}
      />

      <Drawer
        title={editingRow ? '编辑数据' : '新增数据'}
        open={creating || !!editingRow}
        onClose={() => { setCreating(false); setEditingRow(null); form.resetFields() }}
        width={520}
        destroyOnHidden
      >
        <Form form={form} layout="vertical" onFinish={handleFinish}>
          {fields.map(f => {
            const readOnly = !!editingRow && f.editable === false
            return (
              <Form.Item
                key={f.field_name}
                name={f.field_name}
                label={f.label || f.field_name}
                extra={f.help_text || undefined}
                rules={f.required ? [{ required: true, message: `请填写 ${f.label || f.field_name}` }] : []}
              >
                <FormFieldControl field={f} disabled={readOnly} />
              </Form.Item>
            )
          })}
          <Space>
            <Button onClick={() => { setCreating(false); setEditingRow(null); form.resetFields() }}>取消</Button>
            <Button type="primary" htmlType="submit" loading={createRow.isPending || updateRow.isPending}>
              {editingRow ? '保存' : '提交'}
            </Button>
          </Space>
        </Form>
      </Drawer>
    </div>
  )
}
