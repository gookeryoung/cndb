/** 共享「筛选条件编辑器」— 视图筛选规则与行级权限规则条件共用.
 *
 * 从 ViewConfigDialog 的筛选 Tab 抽出：条件组合（AND/OR）+ 逐条规则（字段 / 操作符 / 值 / 删除）+ 添加。
 * 受控组件：自身不持有规则状态，增删改一律通过 onChange 回传，由调用方决定落在哪份草稿上。
 * DOM 结构与类名（vcvd-rule / vcvd-rule-index / vcvd-rule-del / vcvd-logic-bar ...）保持原样，
 * 以便复用既有样式与测试选择器。
 */

import { Button, Input, InputNumber, Select, Space, Switch, Tooltip } from 'antd'
import { DeleteOutlined, PlusOutlined } from '@ant-design/icons'
import type { Field } from '@/api'
import { extractSelectOptions, getOpsForField } from '../cells/fieldOps'

/** 单条筛选条件（与后端 filters 契约同构） */
export interface FilterRule { field_name: string; op: string; value?: unknown }

export interface FilterConditionEditorProps {
  /** 可选字段（已按可见性过滤） */
  fields: Field[]
  rules: FilterRule[]
  /** 规则增删改后回传新数组（受控） */
  onChange: (rules: FilterRule[]) => void
  logic?: 'AND' | 'OR'
  onLogicChange?: (logic: 'AND' | 'OR') => void
  /** 是否渲染 AND/OR 条件组合栏（默认渲染；需同时提供 onLogicChange） */
  showLogic?: boolean
  emptyText?: string
  addText?: string
  /** 添加规则时的默认操作符（默认 contains） */
  defaultOp?: string
}

/** 逐条筛选条件编辑器（受控） */
export default function FilterConditionEditor({
  fields,
  rules,
  onChange,
  logic = 'AND',
  onLogicChange,
  showLogic = true,
  emptyText = '暂无筛选条件',
  addText = '添加筛选条件',
  defaultOp = 'contains',
}: FilterConditionEditorProps) {
  const addRule = () => onChange([...rules, { field_name: '', op: defaultOp }])
  const removeRule = (idx: number) => onChange(rules.filter((_, i) => i !== idx))
  const updateRule = (idx: number, patch: Partial<FilterRule>) =>
    onChange(rules.map((r, i) => (i === idx ? { ...r, ...patch } : r)))

  return (
    <>
      {showLogic && onLogicChange && (
        <div className="vcvd-logic-bar">
          <span className="vcvd-logic-label">条件组合：</span>
          <Space.Compact size="small">
            <Button type={logic === 'AND' ? 'primary' : 'default'} onClick={() => onLogicChange('AND')}>全部满足（AND）</Button>
            <Button type={logic === 'OR' ? 'primary' : 'default'} onClick={() => onLogicChange('OR')}>任一满足（OR）</Button>
          </Space.Compact>
          <span className="vcvd-logic-hint">
            {logic === 'AND' ? '所有筛选条件同时生效' : '任一筛选条件生效即可'}
          </span>
        </div>
      )}
      {rules.length === 0 && (
        <div className="vcvd-empty">{emptyText}</div>
      )}
      {rules.map((rule, idx) => {
        const currentField = fields.find(f => f.name === rule.field_name)
        const ops = currentField ? getOpsForField(currentField.field_type) : getOpsForField('text')
        const currentOp = ops.find(o => o.op === rule.op)
        const needValue = !!currentOp?.needValue
        const fieldOpts = fields.map(f => ({ value: f.name, label: f.name }))
        const selectFieldOpts = extractSelectOptions(currentField?.config).map(o => o.value)
        return (
          <div key={idx} className="vcvd-rule">
            <span className="vcvd-rule-index">#{idx + 1}</span>
            <Select size="small" value={rule.field_name || undefined}
              onChange={(v) => {
                const nextField = fields.find(f => f.name === v)
                const nextOps = nextField ? getOpsForField(nextField.field_type) : getOpsForField('text')
                updateRule(idx, { field_name: v, op: nextOps[0].op, value: undefined })
              }}
              placeholder="字段" style={{ width: 130 }} options={fieldOpts} />
            <Select size="small" value={rule.op}
              onChange={(v) => updateRule(idx, { op: v, value: undefined })}
              placeholder="操作符" style={{ width: 130 }} options={ops.map(o => ({ value: o.op, label: o.label }))} />
            {needValue ? (
              <span className="vcvd-rule-note">（无需值）</span>
            ) : currentOp?.valueKind === 'boolean' ? (
              <Switch size="small" checked={!!rule.value} onChange={(v) => updateRule(idx, { value: v })} />
            ) : currentOp?.valueKind === 'number' ? (
              <InputNumber size="small" value={rule.value as number | undefined}
                onChange={(v) => updateRule(idx, { value: v ?? undefined })} style={{ width: 120 }} placeholder="数值" />
            ) : currentOp?.valueKind === 'select' ? (
              <Select size="small" value={rule.value as string | undefined}
                onChange={(v) => updateRule(idx, { value: v })} style={{ width: 130 }} allowClear
                options={selectFieldOpts.map(o => ({ value: o, label: o }))} placeholder="值" />
            ) : currentOp?.valueKind === 'date' ? (
              <Input size="small" value={rule.value as string | undefined}
                onChange={(e) => updateRule(idx, { value: e.target.value })} style={{ width: 140 }}
                placeholder="YYYY-MM-DD" />
            ) : (
              <Input size="small" value={rule.value as string | undefined}
                onChange={(e) => updateRule(idx, { value: e.target.value })} style={{ flex: 1 }} placeholder="值" />
            )}
            <Tooltip title="删除这条筛选规则">
              <Button size="small" type="text" danger icon={<DeleteOutlined />}
                className="vcvd-rule-del" onClick={() => removeRule(idx)} />
            </Tooltip>
          </div>
        )
      })}
      <div className="vcvd-rule-actions">
        <Button size="small" type="dashed" icon={<PlusOutlined />} onClick={addRule}>{addText}</Button>
      </div>
    </>
  )
}
