/** 视图配置对话框 — 三个 Tab：筛选规则 / 排序规则 / 视图专属设置. */

import { useEffect, useMemo, useState } from 'react'
import { Button, Modal, Select, Space, Switch, Tabs, Input, InputNumber } from 'antd'
import { PlusOutlined, DeleteOutlined } from '@ant-design/icons'
import { getOpsForField, extractSelectOptions } from './fieldOps'
import { getOptionSchema, resolveFieldOptions } from './viewOptionSchema'
import type { ViewOptionSchema } from './viewOptionSchema'
import type { Field } from '@/api'

// ── 类型 ──────────────────────────────────────────

export interface FilterRule { field_name: string; op: string; value?: unknown }
export interface SortRule { field_name: string; direction: 'asc' | 'desc' }

export interface ViewConfigDialogProps {
  open: boolean
  viewType: string
  filters: FilterRule[]
  sortings: SortRule[]
  viewOptions: Record<string, unknown> | null
  fields: Field[]
  onClose: () => void
  filterLogic: 'AND' | 'OR'
  onSaveFilterLogic: (logic: 'AND' | 'OR') => void
  onSaveFilters: (f: FilterRule[]) => void
  onSaveSortings: (s: SortRule[]) => void
  onSaveOptions: (o: Record<string, unknown> | null) => void
}

// ── 组件 ──────────────────────────────────────────

/** 视图配置对话框（筛选 / 排序 / 视图专属设置可视化编辑） */
export default function ViewConfigDialog({
  open, viewType, filters, sortings, viewOptions, fields, onClose,
  filterLogic, onSaveFilterLogic, onSaveFilters, onSaveSortings, onSaveOptions,
}: ViewConfigDialogProps) {
  const [draftFilters, setDraftFilters] = useState<FilterRule[]>([])
  const [draftSorts, setDraftSorts] = useState<SortRule[]>([])
  const [draftFilterLogic, setDraftFilterLogic] = useState<'AND' | 'OR'>('AND')
  const [draftOpt, setDraftOpt] = useState<Record<string, unknown>>({})
  const [activeTab, setActiveTab] = useState<'filter' | 'sort' | 'view'>('filter')

  useEffect(() => {
    if (open) {
      setDraftFilters(filters.length ? [...filters] : [{ field_name: '', op: 'contains' }])
      setDraftSorts(sortings.length ? [...sortings] : [{ field_name: '', direction: 'asc' }])
      setDraftFilterLogic(filterLogic)
      setDraftOpt((viewOptions || {}) as Record<string, unknown>)
      setActiveTab('filter')
    }
  }, [open, filters, sortings, filterLogic, viewOptions])

  const filterableFields = fields.filter(f => !f.hidden)
  const sortableFields = fields.filter(f => !f.hidden)

  // ── 筛选规则增删改 ──
  const addFilter = () => setDraftFilters(prev => [...prev, { field_name: '', op: 'contains' }])
  const removeFilter = (idx: number) => setDraftFilters(prev => prev.filter((_, i) => i !== idx))
  const updateFilter = (idx: number, patch: Partial<FilterRule>) => {
    setDraftFilters(prev => prev.map((r, i) => (i === idx ? { ...r, ...patch } : r)))
  }

  // ── 排序规则增删改 ──
  const addSort = () => setDraftSorts(prev => [...prev, { field_name: '', direction: 'asc' }])
  const removeSort = (idx: number) => setDraftSorts(prev => prev.filter((_, i) => i !== idx))
  const updateSort = (idx: number, patch: Partial<SortRule>) => {
    setDraftSorts(prev => prev.map((r, i) => (i === idx ? { ...r, ...patch } : r)))
  }

  // ── 视图专属设置结构化配置（真相源在 viewOptionSchema.ts） ──
  const viewOptFields: ViewOptionSchema[] = useMemo(
    () => getOptionSchema(viewType),
    [viewType],
  )

  const viewTabItems = useMemo(() => {
    const items: Array<{ key: string; label: string; children: React.ReactNode }> = [
      {
        key: 'filter',
        label: `筛选${draftFilters.filter(f => f.field_name).length ? ` (${draftFilters.filter(f => f.field_name).length})` : ''}`,
        children: (
          <div style={{ minHeight: 120 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 10, paddingBottom: 8, borderBottom: '1px solid var(--cn-border)' }}>
              <span style={{ fontSize: 13, color: 'var(--cn-text-primary)' }}>条件组合：</span>
              <Space.Compact size="small">
                <Button type={draftFilterLogic === 'AND' ? 'primary' : 'default'} onClick={() => setDraftFilterLogic('AND')}>全部满足（AND）</Button>
                <Button type={draftFilterLogic === 'OR' ? 'primary' : 'default'} onClick={() => setDraftFilterLogic('OR')}>任一满足（OR）</Button>
              </Space.Compact>
              <span style={{ fontSize: 12, color: 'var(--cn-text-muted)' }}>
                {draftFilterLogic === 'AND' ? '所有筛选条件同时生效' : '任一筛选条件生效即可'}
              </span>
            </div>
            {draftFilters.length === 0 && (
              <div style={{ textAlign: 'center', color: 'var(--cn-text-muted)', padding: '20px 0', border: '1px dashed var(--cn-border)', borderRadius: 6 }}>
                暂无筛选条件
              </div>
            )}
            {draftFilters.map((rule, idx) => {
              const currentField = filterableFields.find(f => f.name === rule.field_name)
              const ops = currentField ? getOpsForField(currentField.field_type) : getOpsForField('text')
              const currentOp = ops.find(o => o.op === rule.op)
              const needValue = !!currentOp?.needValue
              const fieldOpts = filterableFields.map(f => ({ value: f.name, label: f.name }))
              const selectFieldOpts = extractSelectOptions(currentField?.config).map((o) => o.value)
              return (
                <div key={idx} style={{ display: 'flex', gap: 6, marginBottom: 6, alignItems: 'center' }}>
                  <span style={{ fontSize: 11, color: 'var(--cn-text-muted)', width: 24, textAlign: 'center', flexShrink: 0 }}>#{idx + 1}</span>
                  <Select size="small" value={rule.field_name || undefined}
                    onChange={(v) => {
                      const nextField = filterableFields.find(f => f.name === v)
                      const nextOps = nextField ? getOpsForField(nextField.field_type) : getOpsForField('text')
                      updateFilter(idx, { field_name: v, op: nextOps[0].op, value: undefined })
                    }}
                    placeholder="字段" style={{ width: 130 }} options={fieldOpts} />
                  <Select size="small" value={rule.op}
                    onChange={(v) => updateFilter(idx, { op: v, value: undefined })}
                    placeholder="操作符" style={{ width: 130 }} options={ops.map(o => ({ value: o.op, label: o.label }))} />
                  {needValue ? (
                    <span style={{ fontSize: 12, color: 'var(--cn-text-muted)' }}>（无需值）</span>
                  ) : currentOp?.valueKind === 'boolean' ? (
                    <Switch size="small" checked={!!rule.value} onChange={(v) => updateFilter(idx, { value: v })} />
                  ) : currentOp?.valueKind === 'number' ? (
                    <InputNumber size="small" value={rule.value as number | undefined}
                      onChange={(v) => updateFilter(idx, { value: v ?? undefined })} style={{ width: 120 }} placeholder="数值" />
                  ) : currentOp?.valueKind === 'select' ? (
                    <Select size="small" value={rule.value as string | undefined}
                      onChange={(v) => updateFilter(idx, { value: v })} style={{ width: 130 }} allowClear
                      options={selectFieldOpts.map(o => ({ value: o, label: o }))} placeholder="值" />
                  ) : currentOp?.valueKind === 'date' ? (
                    <Input size="small" value={rule.value as string | undefined}
                      onChange={(e) => updateFilter(idx, { value: e.target.value })} style={{ width: 140 }}
                      placeholder="YYYY-MM-DD" />
                  ) : (
                    <Input size="small" value={rule.value as string | undefined}
                      onChange={(e) => updateFilter(idx, { value: e.target.value })} style={{ flex: 1 }} placeholder="值" />
                  )}
                  <Button size="small" type="text" danger disabled={draftFilters.length <= 1} icon={<DeleteOutlined />}
                    onClick={() => removeFilter(idx)} />
                </div>
              )
            })}
            <div style={{ marginTop: 8 }}>
              <Button size="small" type="dashed" icon={<PlusOutlined />} onClick={addFilter}>添加筛选条件</Button>
            </div>
          </div>
        ),
      },
      {
        key: 'sort',
        label: `排序${draftSorts.filter(s => s.field_name).length ? ` (${draftSorts.filter(s => s.field_name).length})` : ''}`,
        children: (
          <div style={{ minHeight: 120 }}>
            {draftSorts.length === 0 && (
              <div style={{ textAlign: 'center', color: 'var(--cn-text-muted)', padding: '20px 0', border: '1px dashed var(--cn-border)', borderRadius: 6 }}>
                暂无排序规则
              </div>
            )}
            {draftSorts.map((rule, idx) => (
              <div key={idx} style={{ display: 'flex', gap: 6, marginBottom: 6, alignItems: 'center' }}>
                <span style={{ fontSize: 11, color: 'var(--cn-text-muted)', width: 24, textAlign: 'center', flexShrink: 0 }}>#{idx + 1}</span>
                <Select size="small" value={rule.field_name || undefined}
                  onChange={(v) => updateSort(idx, { field_name: v })}
                  placeholder="字段" style={{ flex: 1 }}
                  options={sortableFields.map(f => ({ value: f.name, label: f.name }))} />
                <Select size="small" value={rule.direction}
                  onChange={(v: 'asc' | 'desc') => updateSort(idx, { direction: v })}
                  style={{ width: 100 }}
                  options={[{ value: 'asc', label: '升序 ↑' }, { value: 'desc', label: '降序 ↓' }]} />
                <Button size="small" type="text" danger disabled={draftSorts.length <= 1} icon={<DeleteOutlined />}
                  onClick={() => removeSort(idx)} />
              </div>
            ))}
            <div style={{ marginTop: 8 }}>
              <Button size="small" type="dashed" icon={<PlusOutlined />} onClick={addSort}>添加排序</Button>
            </div>
          </div>
        ),
      },
    ]
    if (viewOptFields.length > 0) {
      items.push({
        key: 'view',
        label: `${viewType} 专属设置`,
        children: (
          <div>
            {viewOptFields.map(opt => {
              const currentValue = draftOpt[opt.key]
              const fallbackValue = opt.defaultValue

              if (opt.kind === 'switch') {
                return (
                  <div key={opt.key} style={{ marginBottom: 8 }}>
                    <div style={{ fontSize: 12, color: 'var(--cn-text-primary)', marginBottom: 4 }}>{opt.label}</div>
                    <Switch
                      checked={currentValue !== false && currentValue !== undefined}
                      onChange={v => setDraftOpt(prev => ({ ...prev, [opt.key]: v }))}
                      checkedChildren="开"
                      unCheckedChildren="关"
                    />
                  </div>
                )
              }

              if (opt.kind === 'direction' || opt.kind === 'enum_select' || opt.kind === 'number_enum') {
                return (
                  <div key={opt.key} style={{ marginBottom: 8 }}>
                    <div style={{ fontSize: 12, color: 'var(--cn-text-primary)', marginBottom: 4 }}>{opt.label}</div>
                    <Select
                      style={{ width: '100%' }}
                      value={(currentValue ?? fallbackValue) as string | number}
                      onChange={v => setDraftOpt(prev => ({ ...prev, [opt.key]: v }))}
                      options={opt.enumOptions?.map(o => ({ value: o.value, label: o.label })) || []}
                    />
                  </div>
                )
              }

              // field_select / field_multi_select
              const fieldOptions = resolveFieldOptions(fields, opt)
              const isMultiple = opt.kind === 'field_multi_select'
              return (
                <div key={opt.key} style={{ marginBottom: 8 }}>
                  <div style={{ fontSize: 12, color: 'var(--cn-text-primary)', marginBottom: 4 }}>{opt.label}</div>
                  <Select
                    mode={isMultiple ? 'multiple' : undefined}
                    style={{ width: '100%' }}
                    allowClear
                    showSearch
                    placeholder={isMultiple ? '选择多个字段' : '选择字段'}
                    options={fieldOptions}
                    value={isMultiple ? (currentValue as string[]) || [] : ((currentValue as string) || undefined)}
                    onChange={v => {
                      if (isMultiple) setDraftOpt(prev => ({ ...prev, [opt.key]: v }))
                      else setDraftOpt(prev => ({ ...prev, [opt.key]: v ?? '' }))
                    }}
                  />
                </div>
              )
            })}
          </div>
        ),
      })
    }
    return items
  }, [draftFilters, draftSorts, draftFilterLogic, filterableFields, sortableFields, viewOptFields, draftOpt, viewType, fields])

  return (
    <Modal
      title={viewType === 'grid' ? '视图配置' : `视图配置 — ${viewType} 专属设置`}
      open={open}
      onCancel={onClose}
      width={640}
      footer={[
        <Button key="cancel" onClick={onClose}>取消</Button>,
        <Button key="ok" type="primary" onClick={() => {
          const cleanFilters = draftFilters.filter(f => f.field_name)
          onSaveFilterLogic(draftFilterLogic)
          onSaveFilters(cleanFilters)
          const cleanSorts = draftSorts.filter(s => s.field_name)
          onSaveSortings(cleanSorts)
          const cleanOpt = Object.fromEntries(
            Object.entries(draftOpt).filter(([, v]) => v !== '' && v != null && (Array.isArray(v) ? v.length > 0 : true)),
          )
          onSaveOptions(Object.keys(cleanOpt).length ? cleanOpt : null)
          onClose()
        }}>保存</Button>,
      ]}
      destroyOnHidden
    >
      <Tabs activeKey={activeTab} onChange={(k) => setActiveTab(k as typeof activeTab)} size="small" items={viewTabItems} />
    </Modal>
  )
}
