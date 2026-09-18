/** 新建行 Modal — "新增行"按钮触发的弹窗表单.
 *
 * 收集必填字段后再提交，避免直接插入空行触发数据库 NOT NULL 约束失败
 * （required 字段在物理表上对应 NOT NULL 列，无法创建全空行）.
 */
import { useEffect } from 'react'
import { Modal, Form, Input, InputNumber, Select, DatePicker, message } from 'antd'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import type { Field, RowValues } from '@/api'
import { recordApi } from '@/api'

interface Props {
  open: boolean
  wid: number | string
  tid: number | string
  fields: Field[]
  onClose: () => void
  /** 创建成功回调（刷新列表后由父组件触发） */
  onCreated?: () => void
}

/** 只读字段类型（系统维护，不参与新行表单） */
const READONLY_TYPES = new Set([
  'auto_id', 'created_time', 'updated_time', 'created_by', 'updated_by', 'formula', 'link', 'attachment',
])

/** 表单支持的字段类型 */
function isEditableType(f: Field): boolean {
  return !READONLY_TYPES.has(f.field_type) && !f.hidden && !f.trashed
}

/** select 字段选项：后端 config.options 可能是 string[] 或 {label,value}[] */
function selectOptions(field: Field): Array<{ value: string; label: string }> {
  const opts = (field.config?.options as unknown) || []
  return (Array.isArray(opts) ? opts : []).map((o) => {
    if (typeof o === 'string') return { value: o, label: o }
    const obj = o as { label?: unknown; value?: unknown }
    return { value: String(obj.value ?? obj.label), label: String(obj.label ?? obj.value) }
  })
}

/** 渲染单个字段的输入控件（受控：透传 Form.Item 注入的 value/onChange，否则表单永不收集值） */
function FieldInput({ field, value, onChange }: { field: Field; value?: unknown; onChange?: (v: unknown) => void }) {
  const ft = field.field_type
  switch (ft) {
    case 'number':
    case 'decimal':
    case 'float':
    case 'percentage':
    case 'timestamp':
      return (
        <InputNumber
          value={value as number}
          onChange={onChange}
          style={{ width: '100%' }}
          step={ft === 'timestamp' ? 1 : ft === 'decimal' || ft === 'float' || ft === 'percentage' ? 0.01 : 1}
          placeholder={`请输入 ${field.name}`}
        />
      )
    case 'boolean': {
      const opts = [{ value: 'true', label: '是' }, { value: 'false', label: '否' }]
      return (
        <Select
          value={value as string | undefined}
          onChange={onChange}
          options={opts}
          allowClear={!field.required}
          placeholder={field.required ? '请选择' : '不设置（可选）'}
        />
      )
    }
    case 'select':
      return (
        <Select
          value={value as string}
          onChange={onChange}
          options={selectOptions(field)}
          placeholder={`请选择 ${field.name}`}
          showSearch
          optionFilterProp="label"
        />
      )
    case 'multi_select':
    case 'multiselect':
      return (
        <Select
          mode="multiple"
          value={value as string[]}
          onChange={onChange}
          options={selectOptions(field)}
          placeholder={`请选择 ${field.name}（可多选）`}
        />
      )
    case 'date':
      return <DatePicker style={{ width: '100%' }} value={value as unknown} onChange={onChange} placeholder={`请选择 ${field.name}`} />
    case 'datetime':
      return <DatePicker style={{ width: '100%' }} showTime value={value as unknown} onChange={onChange} placeholder={`请选择 ${field.name}`} />
    case 'long_text':
    case 'longtext':
      return <Input.TextArea rows={3} value={value as string} onChange={onChange} placeholder={`请输入 ${field.name}`} />
    default:
      return <Input value={value as string} onChange={onChange} placeholder={`请输入 ${field.name}`} />
  }
}

/** 表单值 → 后端 values：剔空值、布尔转实际布尔、日期转字符串 */
function toRowValues(raw: RowValues): RowValues {
  const out: RowValues = {}
  for (const [key, value] of Object.entries(raw)) {
    if (value === undefined || value === null || value === '') continue
    if (value === 'true') { out[key] = true; continue }
    if (value === 'false') { out[key] = false; continue }
    out[key] = value
  }
  return out
}

export default function NewRowModal({ open, wid, tid, fields, onClose, onCreated }: Props) {
  const [form] = Form.useForm()
  const queryClient = useQueryClient()

  // 每次打开时重置表单
  useEffect(() => {
    if (open) form.resetFields()
  }, [open, form])

  const createRow = useMutation({
    mutationFn: (values: RowValues) => recordApi.create(wid, tid, { values }),
    onSuccess: () => {
      message.success('已新增 1 行')
      queryClient.invalidateQueries({ queryKey: ['table-records', `${wid}/${tid}`] })
      queryClient.invalidateQueries({ queryKey: ['table', `${wid}/${tid}`] })
      onClose()
      onCreated?.()
    },
    onError: (err) => {
      message.error(err instanceof Error ? err.message : '新增行失败')
    },
  })

  const editableFields = fields.filter(isEditableType).sort((a, b) => (a.order ?? 0) - (b.order ?? 0))

  return (
    <Modal
      title="新增一行"
      open={open}
      onCancel={onClose}
      onOk={() => form.submit()}
      okText="创建"
      cancelText="取消"
      confirmLoading={createRow.isPending}
      destroyOnHidden
      width={520}
    >
      <Form
        form={form}
        layout="vertical"
        onFinish={(values) => createRow.mutate(toRowValues(values as RowValues))}
      >
        {editableFields.map((field) => {
          const ft = field.field_type
          // 布尔字段不强制必填校验（未设即视为不设置），但 required 时需选择
          const required = !!field.required && ft !== 'boolean'
          const rules = required
            ? [{ required: true, message: `请填写 ${field.name}` }]
            : (ft === 'boolean' && field.required
              ? [{ required: true, message: `请选择 ${field.name}` }]
              : [])
          return (
            <Form.Item
              key={String(field.id)}
              name={field.name}
              label={field.name}
              rules={rules}
              valuePropName={ft === 'boolean' ? 'value' : 'value'}
            >
              <FieldInput field={field} />
            </Form.Item>
          )
        })}
      </Form>
    </Modal>
  )
}