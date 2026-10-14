/** 视图专属设置的单条目渲染（switch / select / number 等形态）.
 *
 * 从 ViewConfigDialog 抽出。
 */

import { Select, Switch } from 'antd'

import type { Field } from '@/api'
import DoneFlagFields from '../views/DoneFlagFields'
import { resolveFieldOptions } from './viewOptionSchema'
import type { ViewOptionSchema } from './viewOptionSchema'

interface ViewOptionItemProps {
  opt: ViewOptionSchema
  fields: Field[]
  opts: Record<string, unknown>
  onSet: (key: string, value: unknown) => void
  onPatch: (patch: Record<string, unknown>) => void
}

export default function ViewOptionItem({ opt, fields, opts, onSet, onPatch }: ViewOptionItemProps) {
  const currentValue = opts[opt.key]
  const label = <div className="vcvd-item-label">{opt.label}</div>

  if (opt.kind === 'switch') {
    // 当 currentValue 未显式配置时，用 opt.defaultValue 回退；
    // false / true 为显式值不回退。与 resolveOpts 行为保持一致。
    const effective = currentValue !== undefined && currentValue !== null ? !!currentValue : !!opt.defaultValue
    return (
      <div className="vcvd-item">
        {label}
        <Switch
          checked={effective}
          onChange={v => onSet(opt.key, v)}
          checkedChildren="开"
          unCheckedChildren="关"
        />
      </div>
    )
  }

  if (opt.kind === 'direction' || opt.kind === 'enum_select' || opt.kind === 'number_enum') {
    return (
      <div className="vcvd-item">
        {label}
        <Select
          style={{ width: '100%' }}
          value={(currentValue ?? opt.defaultValue) as string | number}
          onChange={v => onSet(opt.key, v)}
          options={opt.enumOptions?.map(o => ({ value: o.value, label: o.label })) || []}
        />
      </div>
    )
  }

  // 完成标志：字段下拉 + 操作符 + 匹配值复合控件（存 done_field + done_op + done_value 三键）
  if (opt.kind === 'done_flag') {
    return (
      <div className="vcvd-item">
        {label}
        <DoneFlagFields
          fields={fields}
          doneField={opts.done_field as string | undefined}
          doneOp={opts.done_op as string | undefined}
          doneValue={opts.done_value}
          onChange={onPatch}
        />
      </div>
    )
  }

  // field_select / field_multi_select
  const fieldOptions = resolveFieldOptions(fields, opt)
  const isMultiple = opt.kind === 'field_multi_select'
  return (
    <div className="vcvd-item">
      {label}
      <Select
        mode={isMultiple ? 'multiple' : undefined}
        style={{ width: '100%' }}
        allowClear
        showSearch
        placeholder={isMultiple ? '选择多个字段' : '选择字段'}
        options={fieldOptions}
        value={isMultiple ? (currentValue as string[]) || [] : ((currentValue as string) || undefined)}
        onChange={v => onSet(opt.key, isMultiple ? v : (v ?? ''))}
      />
    </div>
  )
}
