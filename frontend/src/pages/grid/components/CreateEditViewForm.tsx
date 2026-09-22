/** 创建 / 编辑视图表单（合并版，消除 GridPage 里 CreateViewForm 与 EditViewForm 的 90% 重复）.
 *
 * 通过 initialName / initialType / initialOptions 三个可选 prop 区分创建 vs 编辑场景.
 */

import { useState } from 'react'
import { Button, Form, Input, Select, Switch } from 'antd'
import type { Field } from '@/api'
import { getOptionSchema, resolveFieldOptions } from './viewOptionSchema'
import type { ViewOptionSchema } from './viewOptionSchema'
import DoneFlagFields from './DoneFlagFields'

// ── 类型 ──────────────────────────────────────────

interface CreateEditViewFormProps {
  fields: Field[]
  initialName?: string
  initialType?: string
  initialOptions?: Record<string, unknown> | null
  submitLabel?: string
  onSubmit: (name: string, viewType: string, viewOptions: Record<string, unknown>) => void
}

// ── 视图类型配置区 ──────────────────────────────────

interface ViewTypeConfigProps {
  vt: string
  opts: Record<string, unknown>
  fields: Field[]
  updateOpt: (key: string, value: unknown) => void
}

/** 渲染单个 ViewOptionSchema item 为 Form.Item 块 */
function ConfigItem({ opt, fields, opts, updateOpt }: {
  opt: ViewOptionSchema
  fields: Field[]
  opts: Record<string, unknown>
  updateOpt: (key: string, value: unknown) => void
}) {
  const currentValue = opts[opt.key]
  const fallbackValue = opt.defaultValue

  if (opt.kind === 'switch') {
    return (
      <Form.Item label={opt.label} tooltip={opt.tooltip} valuePropName="checked">
        <Switch
          checked={currentValue !== false && currentValue !== undefined}
          onChange={v => updateOpt(opt.key, v)}
          checkedChildren="开"
          unCheckedChildren="关"
        />
      </Form.Item>
    )
  }

  if (opt.kind === 'direction' || opt.kind === 'enum_select' || opt.kind === 'number_enum') {
    return (
      <Form.Item label={opt.label} tooltip={opt.tooltip}>
        <Select
          style={{ width: '100%' }}
          value={(currentValue ?? fallbackValue) as string | number}
          onChange={v => updateOpt(opt.key, v)}
          options={opt.enumOptions?.map(o => ({ value: o.value, label: o.label })) || []}
        />
      </Form.Item>
    )
  }

  // 完成标志：字段下拉 + 匹配值复合控件（存 done_field + done_value 两键）
  if (opt.kind === 'done_flag') {
    return (
      <Form.Item label={opt.label} tooltip={opt.tooltip}>
        <DoneFlagFields
          fields={fields}
          doneField={opts.done_field as string | undefined}
          doneValue={opts.done_value}
          onChange={(patch) => Object.entries(patch).forEach(([k, v]) => updateOpt(k, v))}
        />
      </Form.Item>
    )
  }

  // field_select / field_multi_select
  const fieldOptions = resolveFieldOptions(fields, opt)
  const isMultiple = opt.kind === 'field_multi_select'
  return (
    <Form.Item label={opt.label} tooltip={opt.tooltip} required={opt.required}>
      <Select
        mode={isMultiple ? 'multiple' : undefined}
        style={{ width: '100%' }}
        allowClear
        showSearch
        placeholder={isMultiple ? '选择多个字段' : '选择字段'}
        options={fieldOptions}
        value={isMultiple ? (currentValue as string[]) || [] : ((currentValue as string) || undefined)}
        onChange={v => {
          if (isMultiple) updateOpt(opt.key, v)
          else updateOpt(opt.key, v ?? '')
        }}
      />
    </Form.Item>
  )
}

/** 通用视图专属配置块 — 从 viewOptionSchema 渲染指定 view_type 的所有 option 字段 */
function ConfigBlock({ vt, opts, fields, updateOpt }: ViewTypeConfigProps) {
  const schema = getOptionSchema(vt)
  if (schema.length === 0) return null
  return (
    <>
      {schema.map(opt => (
        <ConfigItem key={opt.key} opt={opt} fields={fields} opts={opts} updateOpt={updateOpt} />
      ))}
    </>
  )
}

/** 看板视图专属配置字段 — 由 viewOptionSchema.ts 驱动 */
function KanbanConfig(props: ViewTypeConfigProps) {
  if (props.vt !== 'kanban') return null
  return <ConfigBlock {...props} />
}

/** 日历视图专属配置字段 — 由 viewOptionSchema.ts 驱动 */
function CalendarConfig(props: ViewTypeConfigProps) {
  if (props.vt !== 'calendar') return null
  return <ConfigBlock {...props} />
}

/** 画廊视图专属配置字段 — 由 viewOptionSchema.ts 驱动 */
function GalleryConfig(props: ViewTypeConfigProps) {
  if (props.vt !== 'gallery') return null
  return <ConfigBlock {...props} />
}

/** 甘特图视图专属配置字段 — 由 viewOptionSchema.ts 驱动 */
function GanttConfig(props: ViewTypeConfigProps) {
  if (props.vt !== 'gantt') return null
  return <ConfigBlock {...props} />
}

/** WBS 工作分解结构视图专属配置字段 — 由 viewOptionSchema.ts 驱动 */
function WbsConfig(props: ViewTypeConfigProps) {
  if (props.vt !== 'wbs') return null
  return <ConfigBlock {...props} />
}

// ── 主表单组件 ──────────────────────────────────────────

/** 合并后的创建/编辑视图表单（根据 initialName 是否存在自动区分模式） */
export default function CreateEditViewForm({
  fields,
  initialName = '',
  initialType = 'grid',
  initialOptions,
  submitLabel = '创建',
  onSubmit,
}: CreateEditViewFormProps) {
  const [name, setName] = useState(initialName)
  const [vt, setVt] = useState(initialType)
  const [opts, setOpts] = useState<Record<string, unknown>>(initialOptions ? { ...initialOptions } : {})

  const updateOpt = (key: string, value: unknown) => {
    setOpts(prev => {
      const next = { ...prev }
      if (value === undefined || value === null || value === '') delete next[key]
      else next[key] = value
      return next
    })
  }

  const viewTypeOptions = [
    { value: 'grid', label: '表格（Grid）' },
    { value: 'kanban', label: '看板（Kanban）' },
    { value: 'gallery', label: '画廊（Gallery）' },
    { value: 'calendar', label: '日历（Calendar）' },
    { value: 'gantt', label: '甘特图（Gantt）' },
    { value: 'wbs', label: '工作分解（WBS）' },
  ]

  return (
    <Form layout="vertical" style={{ marginTop: 12 }}>
      <Form.Item label="视图名称" required>
        <Input placeholder="例如：只看进行中" value={name} onChange={e => setName(e.target.value)} autoFocus />
      </Form.Item>
      <Form.Item label="视图类型">
        <Select value={vt} onChange={(v) => { setVt(v); setOpts({}) }} options={viewTypeOptions} />
      </Form.Item>
      <KanbanConfig vt={vt} opts={opts} fields={fields} updateOpt={updateOpt} />
      <CalendarConfig vt={vt} opts={opts} fields={fields} updateOpt={updateOpt} />
      <GalleryConfig vt={vt} opts={opts} fields={fields} updateOpt={updateOpt} />
      <GanttConfig vt={vt} opts={opts} fields={fields} updateOpt={updateOpt} />
      <WbsConfig vt={vt} opts={opts} fields={fields} updateOpt={updateOpt} />
      <div style={{ textAlign: 'right', marginTop: 12 }}>
        <Button type="primary" disabled={!name.trim()}
          onClick={() => onSubmit(name.trim(), vt, opts)}>{submitLabel}</Button>
      </div>
    </Form>
  )
}
