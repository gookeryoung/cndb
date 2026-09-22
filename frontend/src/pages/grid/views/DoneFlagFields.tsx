/** 完成标志复合控件 — 字段下拉 + 操作符 + 按字段类型动态切换的匹配值控件.
 *
 * 供 CreateEditViewForm（创建/编辑视图）与 ViewConfigDialog（视图专属设置 Tab）共用。
 * 数据存储为 view_options 的三个扁平键：done_field（字段名）+ done_op（判定操作符，缺省 = 等值）+ done_value（匹配值）。
 */

import { DatePicker, Input, Select } from 'antd'
import dayjs from 'dayjs'
import type { Field } from '@/api'
import { DONE_FLAG_OPS, extractSelectOptions, getOpsForField } from '../cells/fieldOps'
import { findOptionSchema, resolveFieldOptions } from '../view-config/viewOptionSchema'

export interface DoneFlagFieldsProps {
  fields: Field[]
  doneField?: string
  /** 判定操作符（DONE_FLAG_OPS 子集）；undefined 按等值 '=' 处理 */
  doneOp?: string
  doneValue?: unknown
  /** patch 键固定为 done_field / done_op / done_value，undefined 表示移除该键 */
  onChange: (patch: { done_field?: string; done_op?: string; done_value?: unknown }) => void
}

/** 完成标志复合控件：选字段 → 选操作符 → 按字段类型选/填匹配值（无值操作符隐藏值控件） */
export default function DoneFlagFields({ fields, doneField, doneOp, doneValue, onChange }: DoneFlagFieldsProps) {
  const doneSchema = findOptionSchema('kanban', 'done_field')
  const fieldOptions = doneSchema ? resolveFieldOptions(fields, doneSchema) : []
  const selectedField = doneField ? fields.find((f) => f.name === doneField) : undefined
  const ft = selectedField?.field_type

  // 操作符候选 = 该字段类型的筛选操作符 ∩ DONE_FLAG_OPS；缺省回退 '='
  const opOptions = ft
    ? getOpsForField(ft)
      .filter((o) => (DONE_FLAG_OPS as readonly string[]).includes(o.op))
      .map((o) => ({ value: o.op, label: o.label }))
    : []
  const currentOp = doneOp && (DONE_FLAG_OPS as readonly string[]).includes(doneOp) ? doneOp : '='
  // needValue=true 的语义是"无需输入值"（is_empty/is_not_empty 直通）→ 隐藏匹配值控件
  const opValueless = ft
    ? getOpsForField(ft).find((o) => o.op === currentOp)?.needValue === true
    : false

  // 切换字段时清空 done_value / done_op，避免跨类型残留值导致隐性误匹配
  const handleFieldChange = (v: string | undefined) => {
    onChange({ done_field: v, done_op: undefined, done_value: undefined })
    // 布尔字段选好后默认匹配 true，减少一次点击
    if (v && fields.find((f) => f.name === v)?.field_type === 'boolean') {
      onChange({ done_field: v, done_op: undefined, done_value: true })
    }
  }

  // 切换操作符时清空匹配值（等值 ↔ 无值操作符之间值语义不互通）
  const handleOpChange = (v: string) => {
    onChange({ done_op: v, done_value: undefined })
  }

  // 按字段类型渲染匹配值控件（无值操作符下不渲染）
  let valueControl: React.ReactNode = null
  if (!selectedField) {
    valueControl = <span style={{ fontSize: 12, color: 'var(--cn-text-muted)' }}>先选择字段</span>
  } else if (opValueless) {
    valueControl = null
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
  } else if (ft === 'date' || ft === 'datetime') {
    // 日期类用 DatePicker：回写格式与行值存储格式一致（date → 'YYYY-MM-DD'，datetime → 'YYYY-MM-DD HH:mm:ss'）
    valueControl = (
      <DatePicker
        style={{ width: '100%' }}
        showTime={ft === 'datetime'}
        value={doneValue ? dayjs(String(doneValue)) : null}
        onChange={(d) => onChange({
          done_value: d
            ? (ft === 'datetime' ? d.format('YYYY-MM-DD HH:mm:ss') : d.format('YYYY-MM-DD'))
            : undefined,
        })}
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
      {selectedField && (
        <Select
          style={{ width: '100%' }}
          placeholder="判定条件"
          options={opOptions}
          value={currentOp}
          onChange={handleOpChange}
        />
      )}
      {valueControl}
    </div>
  )
}
