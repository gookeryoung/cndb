/** 完成标志复合控件 — 字段下拉 + 按字段类型动态切换的匹配值控件.
 *
 * 供 CreateEditViewForm（创建/编辑视图）与 ViewConfigDialog（视图专属设置 Tab）共用。
 * 数据存储为 view_options 的两个扁平键：done_field（字段名）+ done_value（匹配值）。
 */

import { Input, Select } from 'antd'
import type { Field } from '@/api'
import { extractSelectOptions } from '../cells/fieldOps'
import { findOptionSchema, resolveFieldOptions } from '../view-config/viewOptionSchema'

export interface DoneFlagFieldsProps {
  fields: Field[]
  doneField?: string
  doneValue?: unknown
  /** patch 键固定为 done_field / done_value，undefined 表示移除该键 */
  onChange: (patch: { done_field?: string; done_value?: unknown }) => void
}

/** 完成标志复合控件：选字段 → 按字段类型选/填匹配值（切换字段时清空旧值） */
export default function DoneFlagFields({ fields, doneField, doneValue, onChange }: DoneFlagFieldsProps) {
  const doneSchema = findOptionSchema('kanban', 'done_field')
  const fieldOptions = doneSchema ? resolveFieldOptions(fields, doneSchema) : []
  const selectedField = doneField ? fields.find((f) => f.name === doneField) : undefined
  const ft = selectedField?.field_type

  // 切换字段时清空 done_value，避免跨类型残留值导致隐性误匹配
  const handleFieldChange = (v: string | undefined) => {
    onChange({ done_field: v, done_value: undefined })
    // 布尔字段选好后默认匹配 true，减少一次点击
    if (v && fields.find((f) => f.name === v)?.field_type === 'boolean') {
      onChange({ done_field: v, done_value: true })
    }
  }

  // 按字段类型渲染匹配值控件
  let valueControl: React.ReactNode
  if (!selectedField) {
    valueControl = <span style={{ fontSize: 12, color: 'var(--cn-text-muted)' }}>先选择字段</span>
  } else if (ft === 'boolean') {
    valueControl = (
      <Select
        style={{ width: '100%' }}
        value={typeof doneValue === 'boolean' ? doneValue : undefined}
        onChange={(v) => onChange({ done_value: v })}
        options={[
          { value: true, label: '为真 (true)' },
          { value: false, label: '为假 (false)' },
        ]}
      />
    )
  } else if (ft === 'select') {
    const opts = extractSelectOptions(selectedField.config).map((o) => ({ value: o.value, label: o.label }))
    valueControl = (
      <Select
        style={{ width: '100%' }}
        allowClear
        showSearch
        placeholder="选择完成匹配值"
        value={typeof doneValue === 'string' ? doneValue : undefined}
        onChange={(v) => onChange({ done_value: v ?? undefined })}
        options={opts}
      />
    )
  } else if (ft === 'multiselect' || ft === 'multi_select') {
    const opts = extractSelectOptions(selectedField.config).map((o) => ({ value: o.value, label: o.label }))
    valueControl = (
      <Select
        mode="multiple"
        style={{ width: '100%' }}
        allowClear
        placeholder="选择完成匹配值（任一命中即完成）"
        value={Array.isArray(doneValue) ? (doneValue as string[]) : []}
        onChange={(v) => onChange({ done_value: v })}
        options={opts}
      />
    )
  } else {
    // text / longtext 及其他类型：精确匹配文本
    valueControl = (
      <Input
        placeholder="输入完成匹配文本（精确匹配）"
        value={typeof doneValue === 'string' ? doneValue : ''}
        onChange={(e) => onChange({ done_value: e.target.value || undefined })}
      />
    )
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      <Select
        style={{ width: '100%' }}
        allowClear
        showSearch
        placeholder="选择字段"
        options={fieldOptions}
        value={doneField || undefined}
        onChange={handleFieldChange}
      />
      {valueControl}
    </div>
  )
}
