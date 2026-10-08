/** 视图配置对话框 — Tab：筛选规则 / 排序规则 / 字段显示（仅 grid）/ 视图专属设置. */

import { useEffect, useMemo, useRef, useState } from 'react'
import { Button, Checkbox, Modal, Segmented, Select, Space, Switch, Tabs, Input, InputNumber, Tooltip } from 'antd'
import { PlusOutlined, DeleteOutlined, RightOutlined } from '@ant-design/icons'
import { getOpsForField, extractSelectOptions } from '../cells/fieldOps'
import {
  CHART_OPTIONS,
  COLLAPSED_BY_DEFAULT_GROUPS,
  getOptionSchema,
  groupOptionSchema,
  normalizeChartList,
  optionColSpan,
  resolveFieldOptions,
  serializeChartList,
} from './viewOptionSchema'
import type { ViewOptionSchema } from './viewOptionSchema'
import { useChartListDraft } from './useChartListDraft'
import DoneFlagFields from '../views/DoneFlagFields'
import type { Field } from '@/api'
import HelpTip from '@/components/HelpTip'

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
  /** 显式保存按钮触发时调用 — 绕过 debounce 立即持久化到后端 */
  onSaveNow?: () => void
}

// ── 组件 ──────────────────────────────────────────

/** 单个视图专属设置项 —— 控件分支与 CreateEditViewForm 保持一致（真相源同在 viewOptionSchema.ts）.
 *
 * 列宽由 optionColSpan 决定（短控件单列、字段下拉与复合控件整行），由调用方包裹定位容器。
 */
interface ViewOptionItemProps {
  opt: ViewOptionSchema
  fields: Field[]
  opts: Record<string, unknown>
  onSet: (key: string, value: unknown) => void
  onPatch: (patch: Record<string, unknown>) => void
}

function ViewOptionItem({ opt, fields, opts, onSet, onPatch }: ViewOptionItemProps) {
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

/** 视图配置对话框（筛选 / 排序 / 视图专属设置可视化编辑） */
export default function ViewConfigDialog({
  open, viewType, filters, sortings, viewOptions, fields, onClose,
  filterLogic, onSaveFilterLogic, onSaveFilters, onSaveSortings, onSaveOptions, onSaveNow,
}: ViewConfigDialogProps) {
  const [draftFilters, setDraftFilters] = useState<FilterRule[]>([])
  const [draftSorts, setDraftSorts] = useState<SortRule[]>([])
  const [draftFilterLogic, setDraftFilterLogic] = useState<'AND' | 'OR'>('AND')
  const [draftOpt, setDraftOpt] = useState<Record<string, unknown>>({})
  const [activeTab, setActiveTab] = useState<'filter' | 'sort' | 'fields' | 'view'>('filter')
  // chart 多图条目草稿（共享 hook：条目切换 / patch / 增删 + 双形态写回）
  const chartDraft = useChartListDraft(draftOpt, setDraftOpt)
  // setActiveIdx 为 useState setter（稳定引用），解构供初始化 effect 依赖
  const { setActiveIdx: setChartActiveIdx } = chartDraft

  /** 草稿初始化守卫：仅在对话框打开瞬间执行。父组件 props 后续变化（如防抖保存
   *  触发 views refetch 重建 viewOptions 引用）不应重置用户正在操作的 tab 与草稿. */
  const wasOpenRef = useRef(false)
  useEffect(() => {
    if (open && !wasOpenRef.current) {
      setDraftFilters(filters.length ? [...filters] : [{ field_name: '', op: 'contains' }])
      setDraftSorts(sortings.length ? [...sortings] : [{ field_name: '', direction: 'asc' }])
      setDraftFilterLogic(filterLogic)
      setDraftOpt((viewOptions || {}) as Record<string, unknown>)
      setActiveTab('filter')
      setChartActiveIdx(0)
    }
    wasOpenRef.current = open
  }, [open, filters, sortings, filterLogic, viewOptions, setChartActiveIdx])

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

  // ── chart 多图条目（仅 view_type='chart'，逻辑收敛在 useChartListDraft） ──
  const isChartView = viewType === 'chart'
  const chartList = chartDraft.list
  const activeIdx = chartDraft.activeIdx
  const activeChartOpts: Record<string, unknown> = isChartView ? chartDraft.activeEntry : draftOpt

  /** 视图级隐藏字段 id 集合（draftOpt.hidden_fields 黑名单） */
  const viewHiddenFieldIds = useMemo(() => {
    const raw = draftOpt.hidden_fields
    return new Set<string>(Array.isArray(raw) ? raw.map(String) : [])
  }, [draftOpt])

  // 按 group 切分为分区卡片：低频分区（完成状态 / 时间轴 / 操作）默认收起；
  // chart 传当前图表条目（visibleWhen 按该条目 chart_type 显隐），其余传 draftOpt（既有语义不变）
  const viewSections = useMemo(
    () => groupOptionSchema(viewOptFields, isChartView ? (chartList[activeIdx] ?? {}) : draftOpt),
    [viewOptFields, isChartView, chartList, activeIdx, draftOpt],
  )
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>(
    () => Object.fromEntries(
      groupOptionSchema(getOptionSchema(viewType))
        .map(s => [s.label, COLLAPSED_BY_DEFAULT_GROUPS.has(s.label)]),
    ),
  )
  // 折叠重置只跟随分区标签集合变化（chart_type 切换时分区 items 变但标签恒定，不应重置用户折叠态）
  const viewSectionLabels = viewSections.map(s => s.label).join('\u0000')
  useEffect(() => {
    setCollapsed(Object.fromEntries(
      viewSections.map(s => [s.label, COLLAPSED_BY_DEFAULT_GROUPS.has(s.label)]),
    ))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [viewSectionLabels])

  const viewTabItems = useMemo(() => {
    const items: Array<{ key: string; label: React.ReactNode; children: React.ReactNode }> = [
      {
        key: 'filter',
        label: (
          <span>
            筛选{draftFilters.filter(f => f.field_name).length ? ` (${draftFilters.filter(f => f.field_name).length})` : ''}
            <HelpTip title="筛选规则：只显示满足条件的行，不改变表内数据；多个条件可用 AND / OR 组合" />
          </span>
        ),
        children: (
          <div className="vcvd-tab-body">
            <div className="vcvd-logic-bar">
              <span className="vcvd-logic-label">条件组合：</span>
              <Space.Compact size="small">
                <Button type={draftFilterLogic === 'AND' ? 'primary' : 'default'} onClick={() => setDraftFilterLogic('AND')}>全部满足（AND）</Button>
                <Button type={draftFilterLogic === 'OR' ? 'primary' : 'default'} onClick={() => setDraftFilterLogic('OR')}>任一满足（OR）</Button>
              </Space.Compact>
              <span className="vcvd-logic-hint">
                {draftFilterLogic === 'AND' ? '所有筛选条件同时生效' : '任一筛选条件生效即可'}
              </span>
            </div>
            {draftFilters.length === 0 && (
              <div className="vcvd-empty">暂无筛选条件</div>
            )}
            {draftFilters.map((rule, idx) => {
              const currentField = filterableFields.find(f => f.name === rule.field_name)
              const ops = currentField ? getOpsForField(currentField.field_type) : getOpsForField('text')
              const currentOp = ops.find(o => o.op === rule.op)
              const needValue = !!currentOp?.needValue
              const fieldOpts = filterableFields.map(f => ({ value: f.name, label: f.name }))
              const selectFieldOpts = extractSelectOptions(currentField?.config).map((o) => o.value)
              return (
                <div key={idx} className="vcvd-rule">
                  <span className="vcvd-rule-index">#{idx + 1}</span>
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
                    <span className="vcvd-rule-note">（无需值）</span>
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
                  <Tooltip title="删除这条筛选规则">
                    <Button size="small" type="text" danger icon={<DeleteOutlined />}
                      className="vcvd-rule-del" onClick={() => removeFilter(idx)} />
                  </Tooltip>
                </div>
              )
            })}
            <div className="vcvd-rule-actions">
              <Button size="small" type="dashed" icon={<PlusOutlined />} onClick={addFilter}>添加筛选条件</Button>
            </div>
          </div>
        ),
      },
      {
        key: 'sort',
        label: (
          <span>
            排序{draftSorts.filter(s => s.field_name).length ? ` (${draftSorts.filter(s => s.field_name).length})` : ''}
            <HelpTip title="排序规则：按字段升序/降序排列行；多条规则自上而下依次生效" />
          </span>
        ),
        children: (
          <div className="vcvd-tab-body">
            {draftSorts.length === 0 && (
              <div className="vcvd-empty">暂无排序规则</div>
            )}
            {draftSorts.map((rule, idx) => (
              <div key={idx} className="vcvd-rule">
                <span className="vcvd-rule-index">#{idx + 1}</span>
                <Select size="small" value={rule.field_name || undefined}
                  onChange={(v) => updateSort(idx, { field_name: v })}
                  placeholder="字段" style={{ flex: 1 }}
                  options={sortableFields.map(f => ({ value: f.name, label: f.name }))} />
                <Select size="small" value={rule.direction}
                  onChange={(v: 'asc' | 'desc') => updateSort(idx, { direction: v })}
                  style={{ width: 100 }}
                  options={[{ value: 'asc', label: '升序 ↑' }, { value: 'desc', label: '降序 ↓' }]} />
                <Tooltip title="删除这条排序规则">
                  <Button size="small" type="text" danger icon={<DeleteOutlined />}
                    className="vcvd-rule-del" onClick={() => removeSort(idx)} />
                </Tooltip>
              </div>
            ))}
            <div className="vcvd-rule-actions">
              <Button size="small" type="dashed" icon={<PlusOutlined />} onClick={addSort}>添加排序</Button>
            </div>
          </div>
        ),
      },
    ]
    // 字段显示 tab（仅 grid）：不进 viewOptionSchema 的原因是交互形态不同——
    // 全字段 checkbox + 字段级 hidden 禁用态，而非按类型过滤的有限选择。
    if (viewType === 'grid') {
      items.push({
        key: 'fields',
        label: (
          <span>
            字段显示
            <HelpTip title="取消勾选的字段仅在本视图的表格中不显示（列布局），不影响筛选、排序与行详情；字段管理器的「隐藏」为全局开关" />
          </span>
        ),
        children: (
          <div className="vcvd-tab-body">
            {fields.length === 0 && <div className="vcvd-empty">暂无字段</div>}
            <div className="vcvd-field-list">
              {fields.map(f => {
                const fid = String(f.id)
                const viewHidden = viewHiddenFieldIds.has(fid)
                return (
                  <div key={fid} className="vcvd-field-item">
                    <Checkbox
                      checked={!viewHidden}
                      disabled={!!f.hidden}
                      onChange={e => {
                        const next = new Set(viewHiddenFieldIds)
                        if (e.target.checked) next.delete(fid)
                        else next.add(fid)
                        setDraftOpt(prev => {
                          const arr = [...next]
                          const p = { ...prev }
                          if (arr.length) p.hidden_fields = arr
                          else delete p.hidden_fields
                          return p
                        })
                      }}
                    >
                      {f.name}
                    </Checkbox>
                    {f.hidden && <span className="vcvd-field-locked-tag">字段已隐藏</span>}
                    {!f.hidden && viewHidden && f.required && (
                      <Tooltip title="必填字段在本视图隐藏后，内联新增行将无法填写该字段、无法保存">
                        <span className="vcvd-field-warn-tag">必填</span>
                      </Tooltip>
                    )}
                  </div>
                )
              })}
            </div>
          </div>
        ),
      })
    }
    if (viewSections.length > 0) {
      items.push({
        key: 'view',
        label: `${viewType} 专属设置`,
        children: (
          <div className="vcvd-tab-body">
            {isChartView && (
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12, flexWrap: 'wrap' }}>
                <Segmented
                  size="small"
                  value={activeIdx}
                  onChange={(v) => chartDraft.setActiveIdx(Number(v))}
                  options={chartList.map((_, i) => ({ label: `图表 ${i + 1}`, value: i }))}
                />
                <Tooltip title={chartList.length >= 6 ? '最多 6 个图表' : '新增一个图表条目'}>
                  <Button size="small" type="dashed" icon={<PlusOutlined />} disabled={chartList.length >= 6} onClick={chartDraft.addEntry}>
                    添加图表
                  </Button>
                </Tooltip>
                <Tooltip title={chartList.length <= 1 ? '至少保留一个图表' : '删除当前图表'}>
                  <Button size="small" type="text" danger icon={<DeleteOutlined />} disabled={chartList.length <= 1} onClick={chartDraft.removeEntry}>
                    删除当前图表
                  </Button>
                </Tooltip>
              </div>
            )}
            {viewSections.map(section => {
              const isCollapsed = !!collapsed[section.label]
              return (
                <section key={section.label} className={`vcvd-section${isCollapsed ? ' collapsed' : ''}`}>
                  <button
                    type="button"
                    className="vcvd-section-head"
                    aria-expanded={!isCollapsed}
                    onClick={() => setCollapsed(prev => ({ ...prev, [section.label]: !prev[section.label] }))}
                  >
                    <RightOutlined className="vcvd-section-chevron" />
                    <span>{section.label}</span>
                  </button>
                  {!isCollapsed && (
                    <div className="vcvd-section-body vcvd-grid">
                      {section.items.map(opt => (
                        <div
                          key={opt.key}
                          className={optionColSpan(opt.kind) === 2 ? 'vcvd-col-2' : 'vcvd-col-1'}
                        >
                          <ViewOptionItem
                            opt={opt}
                            fields={fields}
                            opts={activeChartOpts}
                            onSet={(key, value) => {
                              if (isChartView) { chartDraft.patchEntry({ [key]: value }); return }
                              setDraftOpt(prev => ({ ...prev, [key]: value }))
                            }}
                            onPatch={(patch) => {
                              if (isChartView) { chartDraft.patchEntry(patch); return }
                              setDraftOpt(prev => {
                                const next = { ...prev }
                                for (const [k, v] of Object.entries(patch)) {
                                  if (v === undefined) delete next[k]
                                  else next[k] = v
                                }
                                return next
                              })
                            }}
                          />
                        </div>
                      ))}
                    </div>
                  )}
                </section>
              )
            })}
          </div>
        ),
      })
    }
    return items
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draftFilters, draftSorts, draftFilterLogic, filterableFields, sortableFields, viewSections, collapsed, draftOpt, viewHiddenFieldIds, viewType, fields, isChartView, chartList, activeIdx, activeChartOpts, chartDraft])

  return (
    <Modal
      title={viewType === 'grid' ? '筛选排序规则' : `筛选排序规则 — ${viewType} 专属设置`}
      open={open}
      onCancel={onClose}
      width={680}
      className="vcvd-modal"
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
          if (viewType === 'chart') {
            // chart：以 normalize/serialize 双向转换产物为准（charts[] 与扁平键不并存，条目级空值清洗）
            delete cleanOpt.charts
            for (const opt of CHART_OPTIONS) delete cleanOpt[opt.key]
            const ser = serializeChartList(normalizeChartList(draftOpt))
            if (ser) Object.assign(cleanOpt, ser)
          }
          onSaveOptions(Object.keys(cleanOpt).length ? cleanOpt : null)
          // 显式保存 — 绕过自动保存的 debounce，确保刷新/关闭后配置不丢失
          onSaveNow?.()
          onClose()
        }}>保存</Button>,
      ]}
      destroyOnHidden
    >
      <Tabs activeKey={activeTab} onChange={(k) => setActiveTab(k as typeof activeTab)} size="small" items={viewTabItems} />
    </Modal>
  )
}
