import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { Card, Form, Input, Button, Typography, message, Spin } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { publicApi } from '@/api'
import type { PublicForm } from '@/api'

const { Title } = Typography

export default function PublicFormPage() {
  const { slug } = useParams<{ slug: string }>()
  const { data: formInfo, isLoading } = useQuery<PublicForm>({
    queryKey: ['public-form', slug],
    queryFn: () => publicApi.getForm(slug!),
    enabled: !!slug,
  })
  const [submitting, setSubmitting] = useState(false)

  const handleSubmit = async (values: Record<string, unknown>) => {
    if (!slug) return
    setSubmitting(true)
    try {
      await publicApi.submitForm(slug, values)
      message.success('提交成功，感谢！')
    } catch {
      message.error('提交失败')
    } finally {
      setSubmitting(false)
    }
  }

  if (isLoading) return <div style={{ padding: 48, textAlign: 'center' }}><Spin /></div>
  if (!formInfo) return <div style={{ padding: 48 }}>表单不存在或已下线</div>

  return (
    <Card>
      <Title level={3}>{formInfo.title}</Title>
      {formInfo.description && <p style={{ color: '#6b7280' }}>{formInfo.description}</p>}
      <Form layout="vertical" onFinish={handleSubmit}>
        {formInfo.fields.map(f => (
          <Form.Item
            key={String(f.id)}
            name={f.name}
            label={f.name}
            rules={f.required ? [{ required: true, message: `${f.name} 为必填` }] : []}
          >
            <Input placeholder={`请输入 ${f.name}`} />
          </Form.Item>
        ))}
        <Button type="primary" htmlType="submit" block size="large" loading={submitting}>提交</Button>
      </Form>
    </Card>
  )
}
