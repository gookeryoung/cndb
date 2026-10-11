/** 表单字段渲染器 — 按 field_type / widget 覆盖选择 antd 控件（表单填写/行编辑共用）.
 *
 * 与 PublicFormPage 的 FieldRenderer 同构，但输入为 FormMeta.fields 元素
 * （FormFieldConfig + field_type/config），透传 Form.Item 注入的 value/onChange/id。
 * 表单级控件覆盖：field.widget 非空时优先渲染覆盖控件（select/radio/rate），
 * options 取 widget_config.options（缺省回退字段定义 config.options）。
 */

import { DatePicker, Input, InputNumber, Radio, Rate, Select, Switch } from 'antd'

export interface FormFieldMeta {
  field_name: string
  label?: string | null
  required?: boolean | null
  editable?: boolean
  field_type?: string
  config?: Record<string, unknown> | null
  /** 表单级控件覆盖（与后端 ALLOWED_FORM_WIDGETS 对齐） */
  widget?: 'select' | 'radio' | 'rate' | null
  /** 控件覆盖参数（如 select/radio 的 options） */
  widget_config?: Record<string, unknown> | null
}

export function extractSelectOptions(config: unknown): Array<{ value: string; label: string }> {
  if (!config || typeof config !== 'object') return []
  const c = config as { options?: Array<{ value: string; label?: string }> | string[] }
  const opts = c.options || []
  if (opts.length === 0) return []
  if (typeof opts[0] === 'string') return (opts as string[]).map(v => ({ value: v, label: v }))
  return (opts as Array<{ value: string; label?: string }>).map(o => ({ value: o.value, label: o.label || o.value }))
}

/** 控件覆盖渲染（widget 非空时分流；返回 null 表示无覆盖） */
function WidgetOverride({ field, ...rest }: { field: FormFieldMeta } & Record<string, unknown>) {
  const options = extractSelectOptions(field.widget_config ?? field.config)
  switch (field.widget) {
    case 'select':
      return <Select {...rest} options={options} virtual={false} placeholder="请选择" />
    case 'radio':
      return <Radio.Group {...rest} options={options} />
    case 'rate':
      return <Rate {...rest} />
    default:
      return null
  }
}

export function FormFieldControl({ field, ...rest }: { field: FormFieldMeta } & Record<string, unknown>) {
  const overridden = WidgetOverride({ field, ...rest })
  if (overridden !== null) return overridden

  const ft = field.field_type || 'text'
  switch (ft) {
    case 'number':
    case 'decimal':
      return <InputNumber {...rest} style={{ width: '100%' }} placeholder="请输入数字" />
    case 'boolean':
      return <Switch {...rest} />
    case 'date':
      return <DatePicker {...rest} style={{ width: '100%' }} />
    case 'datetime':
      return <DatePicker {...rest} showTime style={{ width: '100%' }} />
    case 'select':
    case 'multi_select': {
      const options = extractSelectOptions(field.config)
      return (
        <Select
          {...rest}
          mode={ft === 'multi_select' ? 'multiple' : undefined}
          options={options}
          virtual={false}
          placeholder="请选择"
        />
      )
    }
    case 'email':
      return <Input {...rest} type="email" placeholder="请输入邮箱" />
    case 'url':
      return <Input {...rest} type="url" placeholder="https://..." />
    case 'phone':
      return <Input {...rest} placeholder="请输入手机号" />
    case 'long_text':
      return <Input.TextArea {...rest} rows={4} placeholder="请输入..." />
    default:
      return <Input {...rest} placeholder="请输入..." />
  }
}
