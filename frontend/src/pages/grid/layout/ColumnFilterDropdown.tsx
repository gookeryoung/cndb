/** 列级筛选下拉面板 — 嵌入 AntD Table 列头 filterDropdown. */

import { useEffect, useState } from 'react'
import { Button, Select, Input } from 'antd'
import {
  getOpsForField,
  effectiveFieldType,
  FIELD_TYPE_ALIASES,
  extractSelectOptions,
  type FieldOp,
} from '../cells/fieldOps'
import type { Field } from '@/api'
import { WEIGHT } from '@/theme/tokens'

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
  // 引用（lookup）字段按后端同步的源字段类型筛选：源字段 文本→单选 后操作符随之切换
  const effectiveType = effectiveFieldType(field)
  const _numericTypes = new Set(['number', 'float', 'decimal', 'percentage', 'timestamp'])
  const _resolveFt = (ft: string) => FIELD_TYPE_ALIASES[ft] ?? ft
  const resolvedType = _resolveFt(effectiveType)
  const isSelect = resolvedType === 'select' || resolvedType === 'multiselect'
  const options = isSelect
    ? extractSelectOptions(field.config).map(o => ({ value: o.value, label: o.label }))
    : []
  // 引用字段只同步了源类型、拿不到源字段选项：去掉依赖选项集合的 in 操作符，
  // 值输入回退为文本，避免渲染一个没有选项的空下拉
  const hasOptions = options.length > 0
  const allOps = getOpsForField(effectiveType)
  const visibleOps = isSelect && !hasOptions ? allOps.filter(o => o.op !== 'in') : allOps
  const defaultOp = visibleOps[0]?.op || '='
  const [op, setOp] = useState<string>(currentFilter?.op || defaultOp)
  const [value, setValue] = useState<unknown>(currentFilter?.value ?? '')

  // 当 field 变化（切换到不同列）时重置
  useEffect(() => {
    const newOps = getOpsForField(effectiveFieldType(field))
    const nextOps = field.field_type === 'lookup' && !extractSelectOptions(field.config).length
      ? newOps.filter(o => o.op !== 'in')
      : newOps
    setOp(currentFilter?.op || nextOps[0]?.op || '=')
    setValue(currentFilter?.value ?? '')
  }, [field.name]) // eslint-disable-line react-hooks/exhaustive-deps

  const currentOp: FieldOp | undefined = visibleOps.find(o => o.op === op)
  const noValue = !!currentOp?.needValue

  return (
    <div style={{ padding: 12, width: 280 }}>
      <div style={{ fontSize: 13, fontWeight: WEIGHT.semibold, marginBottom: 8, color: '#1f2937' }}>
        筛选「{field.name}」
      </div>
      <div style={{ marginBottom: 8 }}>
        <Select
          value={op}
          onChange={(v) => { setOp(v); setValue('') }}
          style={{ width: '100%' }}
          options={visibleOps.map(o => ({ value: o.op, label: o.label }))}
          size="small"
        />
      </div>
      {!noValue && (
        <div style={{ marginBottom: 12 }}>
          {isSelect && hasOptions ? (
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
          ) : _numericTypes.has(resolvedType) ? (
            <Input
              type="number"
              value={value as string | number}
              onChange={e => setValue(e.target.value)}
              size="small"
              placeholder="输入数值"
            />
          ) : resolvedType === 'boolean' ? (
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
              placeholder={isSelect ? '输入选项值' : '输入值'}
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
