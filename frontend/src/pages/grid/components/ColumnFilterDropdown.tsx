/** 列级筛选下拉面板 — 嵌入 AntD Table 列头 filterDropdown. */

import { useEffect, useState } from 'react'
import { Button, Select, Input } from 'antd'
import { getOpsForField, FIELD_TYPE_ALIASES, extractSelectOptions, type FieldOp } from './fieldOps'
import type { Field } from '@/api'

interface ColumnFilterDropdownProps {
  field: Field
  currentFilter?: { op: string; value: unknown }
  onApply: (op: string, value: unknown) => void
  onReset: () => void
}

/** 列级筛选下拉面板 */
export default function ColumnFilterDropdown({
  field,
  currentFilter,
  onApply,
  onReset,
}: ColumnFilterDropdownProps) {
  const allOps = getOpsForField(field.field_type)
  const defaultOp = allOps[0]?.op || '='
  const [op, setOp] = useState<string>(currentFilter?.op || defaultOp)
  const [value, setValue] = useState<unknown>(currentFilter?.value ?? '')

  // 当 field 变化（切换到不同列）时重置
  useEffect(() => {
    const newOps = getOpsForField(field.field_type)
    setOp(currentFilter?.op || newOps[0]?.op || '=')
    setValue(currentFilter?.value ?? '')
  }, [field.name]) // eslint-disable-line react-hooks/exhaustive-deps

  const currentOp: FieldOp | undefined = allOps.find(o => o.op === op)
  const noValue = !!currentOp?.needValue

  const _numericTypes = new Set(['number', 'float', 'decimal', 'percentage', 'timestamp'])
  const _resolveFt = (ft: string) => FIELD_TYPE_ALIASES[ft] ?? ft
  const isSelect = _resolveFt(field.field_type) === 'select' || _resolveFt(field.field_type) === 'multiselect'
  const options = isSelect
    ? extractSelectOptions(field.config).map(o => ({ value: o.value, label: o.label }))
    : []

  return (
    <div style={{ padding: 12, width: 280 }}>
      <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8, color: '#1f2937' }}>
        筛选「{field.name}」
      </div>
      <div style={{ marginBottom: 8 }}>
        <Select
          value={op}
          onChange={(v) => { setOp(v); setValue('') }}
          style={{ width: '100%' }}
          options={allOps.map(o => ({ value: o.op, label: o.label }))}
          size="small"
        />
      </div>
      {!noValue && (
        <div style={{ marginBottom: 12 }}>
          {isSelect ? (
            <Select
              mode={op === 'in' ? 'multiple' : undefined}
              value={value as string | string[] | undefined}
              onChange={(v) => setValue(v)}
              style={{ width: '100%' }}
              size="small"
              placeholder={op === 'in' ? '选择多个值' : '选择值'}
              options={options}
              allowClear
              showSearch
            />
          ) : _numericTypes.has(_resolveFt(field.field_type)) ? (
            <Input
              type="number"
              value={value as string | number}
              onChange={e => setValue(e.target.value)}
              size="small"
              placeholder="输入数值"
            />
          ) : field.field_type === 'boolean' ? (
            <Select
              value={value as boolean | undefined}
              onChange={(v) => setValue(v)}
              style={{ width: '100%' }}
              size="small"
              placeholder="选择"
              options={[{ value: true, label: '是' }, { value: false, label: '否' }]}
              allowClear
            />
          ) : (
            <Input
              value={value as string}
              onChange={e => setValue(e.target.value)}
              size="small"
              placeholder="输入值"
            />
          )}
        </div>
      )}
      {noValue && (
        <div style={{ fontSize: 12, color: '#64748b', marginBottom: 12 }}>
          此条件无需输入值
        </div>
      )}
      <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
        <Button size="small" onClick={onReset}>清除</Button>
        <Button
          size="small"
          type="primary"
          onClick={() => {
            if (noValue) {
              onApply(op, null)
            } else {
              onApply(op, value)
            }
          }}
          disabled={!noValue && (value === '' || value === null || value === undefined)}
        >确定</Button>
      </div>
    </div>
  )
}
