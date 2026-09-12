import { useState } from 'react'
import { Modal, Table, Button, Tag, Input, Select, Form, Row, Col, Popconfirm, Checkbox, message } from 'antd'
import { PlusOutlined, DeleteOutlined, EditOutlined } from '@ant-design/icons'
import { useMutation } from '@tanstack/react-query'
import { fieldApi } from '@/api'
import type { Field, FieldCreate, FieldType } from '@/api'

interface Props {
  open: boolean
  wid: string
  tid: string
  fields: Field[]
  onClose: () => void
  onChanged: () => void
}

const FIELD_TYPES: { value: FieldType; label: string }[] = [
  { value: 'text', label: '单行文本' }, { value: 'long_text', label: '多行文本' },
  { value: 'number', label: '整数' }, { value: 'decimal', label: '小数' },
  { value: 'boolean', label: '是/否' }, { value: 'date', label: '日期' },
  { value: 'datetime', label: '日期时间' }, { value: 'select', label: '单选' },
  { value: 'multi_select', label: '多选' }, { value: 'email', label: '邮箱' },
  { value: 'url', label: '链接' }, { value: 'phone', label: '电话' },
  { value: 'link', label: '关联' },
  // NOTE: attachment 后端 FieldTypeRegistry 尚未实现，暂不暴露给前端
]

export default function FieldManager({ open, wid, tid, fields, onClose, onChanged }: Props) {
  const [innerOpen, setInnerOpen] = useState(false)
  const [editTarget, setEditTarget] = useState<Field | null>(null)
  const [form] = Form.useForm()
  const sorted = [...fields].sort((a, b) => (a.order ?? 0) - (b.order ?? 0))

  const create = useMutation({
    mutationFn: (data: FieldCreate) => fieldApi.create(wid, tid, data),
    onSuccess: () => { message.success('已添加字段'); setInnerOpen(false); form.resetFields(); onChanged() },
  })
  const update = useMutation({
    mutationFn: (args: { fid: number | string; data: Partial<Field> }) => fieldApi.update(wid, tid, args.fid, args.data),
    onSuccess: () => { message.success('已更新'); setEditTarget(null); form.resetFields(); onChanged() },
  })
  const remove = useMutation({
    mutationFn: (fid: number | string) => fieldApi.remove(wid, tid, fid),
    onSuccess: () => { message.success('已删除'); onChanged() },
  })

  return (
    <Modal title="字段管理" width={720} open={open} onCancel={onClose} footer={null}>
      <div style={{ marginBottom: 12, textAlign: 'right' }}>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => { setEditTarget(null); setInnerOpen(true); form.resetFields() }}>
          新建字段
        </Button>
      </div>

      <Table size="small" rowKey="id" pagination={false} dataSource={sorted}
        columns={[
          { title: '名称', dataIndex: 'name', render: (v, r) => r.is_primary ? <span><Tag color="gold">PK</Tag> {v}</span> : v },
          { title: '类型', dataIndex: 'field_type', render: (v) => <Tag>{String(v)}</Tag> },
          { title: '必填', dataIndex: 'required', render: v => v ? '是' : '否', width: 70 },
          { title: '隐藏', dataIndex: 'hidden', render: v => v ? '是' : '否', width: 70 },
          {
            title: '操作', key: 'op', width: 160,
            render: (_, r) => (
              <span>
                <Button size="small" icon={<EditOutlined />} style={{ marginRight: 4 }}
                  onClick={() => { setEditTarget(r); form.setFieldsValue(r); setInnerOpen(true) }}>编辑</Button>
                {!r.is_primary && (
                  <Popconfirm title="确认删除？" onConfirm={() => remove.mutate(r.id)}>
                    <Button size="small" danger icon={<DeleteOutlined />} />
                  </Popconfirm>
                )}
              </span>
            ),
          },
        ]} />

      <Modal
        title={editTarget ? '编辑字段' : '新建字段'}
        open={innerOpen}
        onCancel={() => { setInnerOpen(false); setEditTarget(null); form.resetFields() }}
        onOk={() => form.submit()}
        confirmLoading={create.isPending || update.isPending}
      >
        <Form form={form} layout="vertical"
          onFinish={(v) => {
            if (editTarget) update.mutate({ fid: editTarget.id, data: v })
            else create.mutate(v)
          }}>
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item name="name" label="字段名" rules={[{ required: true }]}><Input /></Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="field_type" label="类型" rules={[{ required: true }]}>
                <Select options={FIELD_TYPES} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="required" valuePropName="checked" label="必填">
                <Checkbox />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="hidden" valuePropName="checked" label="在视图中隐藏">
                <Checkbox />
              </Form.Item>
            </Col>
          </Row>
        </Form>
      </Modal>
    </Modal>
  )
}
