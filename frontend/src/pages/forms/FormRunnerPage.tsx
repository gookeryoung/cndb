/** 表单运行器页 — 打开表单、填写字段、提交创建记录、查看/删除记录. */

import React from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  Card, Table, Button, Drawer, Form, Input, Select, Tag, Typography,
  App as AntApp, Spin, Space, message as antdMessage,
} from 'antd'
import { PlusOutlined, DeleteOutlined, ArrowLeftOutlined } from '@ant-design/icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { formApi, tableApi, recordApi, fieldApi } from '@/api'
import type {
  FormDefinition, FormFieldConfig, RowResponse, Field, TableDetail,
} from '@/api'

const { Title, Text } = Typography

/** 表单内字段配置 + 完整字段定义的合并视图. */
interface _FormField {
  field_name: string
  field_type: string
  editable: boolean
  visible: boolean
  required: boolean
  options?: string[]  // select 类型可用值列表
}

export default function FormRunnerPage() {
  const { modal } = AntApp.useApp()
  const { wid, fid } = useParams<{ wid: string; fid: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const workspaceId = Number(wid)
  const formId = Number(fid)

  const [drawerOpen, setDrawerOpen] = React.useState(false)
  const [submitting, setSubmitting] = React.useState(false)
  const [form] = Form.useForm()

  // 加载表单定义
  const { data: formDef, isLoading: formLoading } = useQuery<FormDefinition>({
    queryKey: ['form', workspaceId, formId],
    queryFn: () => formApi.get(workspaceId, formId),
    enabled: !Number.isNaN(workspaceId) && !Number.isNaN(formId),
  })

  // 加载所属表详情（含字段列表）
  const { data: tableDetail, isLoading: tableLoading } = useQuery<TableDetail>({
    queryKey: ['table', workspaceId, formDef?.table_id],
    queryFn: () => tableApi.get(workspaceId, String(formDef!.table_id)),
    enabled: !!formDef,
  })

  // 加载表内字段（field_name -> Field 映射）
  const { data: fields = [] } = useQuery<Field[]>({
    queryKey: ['fields', workspaceId, formDef?.table_id],
    queryFn: () => fieldApi.list(workspaceId, String(formDef!.table_id)),
    enabled: !!formDef,
  })

  // 加载记录列表
  const { data: recordsData, isLoading: recordsLoading } = useQuery({
    queryKey: ['records', workspaceId, formDef?.table_id],
    queryFn: () => recordApi.list(workspaceId, formDef!.table_id, { limit: 500 }),
    enabled: !!formDef,
  })

  const formFields: _FormField[] = React.useMemo(() => {
    if (!formDef || !tableDetail) return []
    const fieldMap = new Map<string, Field>()
    for (const f of fields) fieldMap.set(f.name, f)
    const cfgMap = new Map<string, FormFieldConfig>()
    for (const fc of formDef.field_config) cfgMap.set(fc.field_name, fc)
    // 只取表单配置里的字段
    return formDef.field_config.map((fc) => {
      const fld = fieldMap.get(fc.field_name)
      return {
        field_name: fc.field_name,
        field_type: fld?.field_type ?? 'text',
        editable: fc.editable ?? true,
        visible: fc.visible ?? true,
        required: fc.required ?? false,
        options: fld?.config?.options as string[] | undefined,
      }
    }).filter((f) => f.visible)
  }, [formDef, tableDetail, fields])

  // 提交表单
  const submitMutation = useMutation({
    mutationFn: (values: Record<string, unknown>) =>
      formApi.submit(workspaceId, formId, { values }),
    onSuccess: (resp) => {
      antdMessage.success(resp.message || '提交成功')
      setDrawerOpen(false)
      form.resetFields()
      setSubmitting(false)
      // 刷新记录
      queryClient.invalidateQueries({ queryKey: ['records', workspaceId, formDef!.table_id] })
    },
    onError: (err: any) => {
      setSubmitting(false)
      const detail = err?.response?.data?.detail || err?.message || '提交失败'
      antdMessage.error(typeof detail === 'string' ? detail : JSON.stringify(detail))
    },
  })

  // 删除行
  const deleteMutation = useMutation({
    mutationFn: (rid: number) => recordApi.remove(workspaceId, formDef!.table_id, rid),
    onSuccess: () => {
      antdMessage.success('已删除')
      queryClient.invalidateQueries({ queryKey: ['records', workspaceId, formDef!.table_id] })
    },
    onError: (err: any) => {
      const detail = err?.response?.data?.detail || err?.message || '删除失败'
      antdMessage.error(typeof detail === 'string' ? detail : JSON.stringify(detail))
    },
  })

  const [recordColumns, setRecordColumns] = React.useState<any[]>([])

  React.useEffect(() => {
    if (!formDef || !fields) return
    const cols: any[] = formFields.map((ff) => ({
      title: ff.field_name,
      dataIndex: ff.field_name,
      key: ff.field_name,
      width: 150,
    }))
    cols.push({
      title: '操作',
      key: 'action',
      width: 80,
      fixed: 'right',
      render: (_: unknown, row: RowResponse) => (
        <Space>
          <Button
            type="text"
            size="small"
            danger
            icon={<DeleteOutlined />}
            aria-label={`删除第 ${row.id} 行`}
            onClick={() => {
              modal.confirm({
                title: '确认删除',
                content: `确定要删除这条记录吗？`,
                okButtonProps: { danger: true },
                okText: '删除',
                cancelText: '取消',
                onOk: () => {
                  deleteMutation.mutate(Number(row.id))
                },
              })
            }}
          />
        </Space>
      ),
    })
    setRecordColumns(cols)
  }, [formDef, fields, formFields, deleteMutation, modal])

  if (formLoading || tableLoading) {
    return <div style={{ padding: 48, textAlign: 'center' }}><Spin /></div>
  }
  if (!formDef || !tableDetail) {
    return <div style={{ padding: 24 }}>表单不存在</div>
  }

  const records: RowResponse[] = (recordsData as any)?.items ?? (recordsData as any)?.results ?? []

  return (
    <div style={{ padding: 24 }}>
      {/* 顶部：表单信息 */}
      <main style={{ marginBottom: 16 }}>
        <Space align="center" size={12} wrap>
          <Button icon={<ArrowLeftOutlined />} onClick={() => navigate(`/w/${workspaceId}/forms`)} />
          <Title level={3} style={{ margin: 0 }}>{formDef.name}</Title>
          <Tag color="blue">{tableDetail.name}</Tag>
          {formDef.description && <Text type="secondary">{formDef.description}</Text>}
        </Space>
      </main>

      {/* 数据区 */}
      <Card
        title="提交记录"
        extra={
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => setDrawerOpen(true)}
          >
            新增数据
          </Button>
        }
        styles={{ body: { padding: 0 } }}
      >
        <Table
          rowKey="id"
          size="small"
          dataSource={records}
          columns={recordColumns}
          loading={recordsLoading}
          pagination={{ pageSize: 20 }}
          scroll={{ x: 'max-content' }}
          rowClassName={(row) => `row-${row.id}`}
        />
      </Card>

      {/* 新增数据 Drawer（role=dialog 由 antd Drawer 渲染） */}
      <Drawer
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        title={`新增 ${formDef.name}`}
        width={480}
        destroyOnClose
      >
        <Form
          form={form}
          layout="vertical"
          onFinish={(values) => {
            setSubmitting(true)
            submitMutation.mutate(values)
          }}
        >
          {formFields.map((ff) => (
            <Form.Item
              key={ff.field_name}
              label={ff.field_name}
              name={ff.field_name}
              rules={ff.required ? [{ required: true, message: `请填写${ff.field_name}` }] : []}
            >
              {ff.field_type === 'select' || (ff.options && ff.options.length > 0) ? (
                <Select
                  placeholder={`请选择${ff.field_name}`}
                  options={(ff.options ?? []).map((opt) => ({ label: opt, value: opt }))}
                  allowClear={!ff.required}
                />
              ) : ff.field_type === 'number' ? (
                <Input type="number" placeholder={`请输入${ff.field_name}`} />
              ) : (
                <Input placeholder={`请输入${ff.field_name}`} />
              )}
            </Form.Item>
          ))}
          <Form.Item>
            <Button type="primary" htmlType="submit" loading={submitting} block>
              提交
            </Button>
          </Form.Item>
        </Form>
      </Drawer>
    </div>
  )
}
