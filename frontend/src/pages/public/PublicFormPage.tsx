/** 公开表单页面 — 匿名用户填写数据提交. */

import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { Card, Form, Input, Button, Typography, App as AntApp, Spin, Select, DatePicker, InputNumber, Switch, Tag } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { publicApi } from '@/api'

const { Title, Text } = Typography

export default function PublicFormPage() {
  const { message } = AntApp.useApp()
  const { slug } = useParams<{ slug: string }>()
  const { data, isLoading } = useQuery({
    queryKey: ['public-form', slug],
    queryFn: () => publicApi.getForm(slug!),
    enabled: !!slug,
  })
  const [submitting, setSubmitting] = useState(false)
  const [form] = Form.useForm()

  const fields = data?.table.fields || []
  const viewName = data?.view.name || '公开表单'
  const tableName = data?.table.name || ''
  const description = data?.table.description || ''

  const handleSubmit = async (values: Record<string, unknown>) => {
    if (!slug) return
    setSubmitting(true)
    try {
      await publicApi.submitForm(slug, values)
      message.success('提交成功，感谢！')
      form.resetFields()
    } catch {
      message.error('提交失败，请稍后重试')
    } finally {
      setSubmitting(false)
    }
  }

  if (isLoading) return <div style={{ padding: 48, textAlign: 'center' }}><Spin /></div>
  if (!data) return <div style={{ padding: 48, textAlign: 'center', color: '#9ca3af' }}>表单不存在或已下线</div>

  return (
    <Card style={{ maxWidth: 640, margin: '40px auto' }}>
      <Title level={3} style={{ marginBottom: 4 }}>{viewName}</Title>
      <div style={{ marginBottom: 16 }}>
        {tableName && <Tag color="blue">{tableName}</Tag>}
        {description && <Text type="secondary">{description}</Text>}
      </div>
      <Form form={form} layout="vertical" onFinish={handleSubmit} preserve={false}>
        {fields.map(f => (
          <Form.Item
            key={String(f.id)}
            name={f.name}
            label={f.name}
            rules={f.required ? [{ required: true, message: `请填写 ${f.name}` }] : []}
          >
            <FieldRenderer field={f} />
          </Form.Item>
        ))}
        <Button type="primary" htmlType="submit" block size="large" loading={submitting}>提交</Button>
      </Form>
    </Card>
  )
}

/** 简单字段类型渲染器 — 根据 field_type 选择合适的控件. */
function FieldRenderer({ field }: { field: { field_type: string; config?: unknown } }) {
  const ft = field.field_type
  switch (ft) {
    case 'number':
    case 'decimal':
      return <InputNumber style={{ width: '100%' }} placeholder="请输入数字" />
    case 'boolean':
      return <Switch />
    case 'date':
      return <DatePicker style={{ width: '100%' }} />
    case 'datetime':
      return <DatePicker showTime style={{ width: '100%' }} />
    case 'select':
    case 'multi_select': {
      const options = extractSelectOptions(field.config)
      return <Select mode={ft === 'multi_select' ? 'multiple' : undefined} options={options} placeholder="请选择" />
    }
    case 'email':
      return <Input type="email" placeholder="请输入邮箱" />
    case 'url':
      return <Input type="url" placeholder="https://..." />
    case 'phone':
      return <Input placeholder="请输入手机号" />
    case 'long_text':
      return <Input.TextArea rows={4} placeholder="请输入..." />
    default:
      return <Input placeholder="请输入..." />
  }
}

function extractSelectOptions(config: unknown): Array<{ value: string; label: string }> {
  if (!config || typeof config !== 'object') return []
  const c = config as { options?: Array<{ value: string; label?: string }> | string[] }
  const opts = c.options || []
  if (opts.length === 0) return []
  if (typeof opts[0] === 'string') return (opts as string[]).map(v => ({ value: v, label: v }))
  return (opts as Array<{ value: string; label?: string }>).map(o => ({ value: o.value, label: o.label || o.value }))
}
