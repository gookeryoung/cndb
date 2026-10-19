/** 视图配置对话框 — Tab：筛选规则 / 排序规则 / 字段显示（仅 grid）/ 视图专属设置. */

import { useEffect, useMemo, useRef, useState } from 'react'
import { Alert, Button, Modal, Tabs } from 'antd'
import { validateAndNormalizeDraft } from './filterValueRules'
import {
  CHART_OPTIONS,
  COLLAPSED_BY_DEFAULT_GROUPS,
  getOptionSchema,
  groupOptionSchema,
  normalizeChartList,
  serializeChartList,
} from './viewOptionSchema'
import type { ViewOptionSchema } from './viewOptionSchema'
import { useChartListDraft } from './useChartListDraft'
import type { Field } from '@/api'
import { buildFieldsTab, buildFilterTab, buildSortTab, buildViewTab } from './viewTabItems'
import type { ViewTabItem } from './viewTabItems'

// ── 类型 ──────────────────────────────────────────

// FilterRule 定义已下沉到共享的 FilterConditionEditor，此处 re-export 保持既有 import 路径不变
export type { FilterRule } from './FilterConditionEditor'
import type { FilterRule } from './FilterConditionEditor'
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
  // 保存校验错误（每条 = 规则序号 + 问题 + 修正方向），非空时渲染 Alert 并阻止保存
  const [filterErrors, setFilterErrors] = useState<string[]>([])
  // chart 多图条目草稿（共享 hook：条目切换 / patch / 增删 + 双形态写回）
  const chartDraft = useChartListDraft(draftOpt, setDraftOpt)
  // setActiveIdx 为 useState setter（稳定引用），解构供初始化 effect 依赖
  const { setActiveIdx: setChartActiveIdx } = chartDraft

  /** 草稿初始化守卫：仅在对话框打开瞬间执行。父组件 props 后续变化（如防抖保存
   *  触发 views refetch 重建 viewOptions 引用）不应重置用户正在操作的 tab 与草稿. */
  const wasOpenRef = useRef(false)
  useEffect(() => {
    if (open && !wasOpenRef.current) {
      setDraftFilters(filters.length ? [...filters] : [])
      setDraftSorts(sortings.length ? [...sortings] : [])
      setDraftFilterLogic(filterLogic)
      setDraftOpt((viewOptions || {}) as Record<string, unknown>)
      setActiveTab('filter')
      setChartActiveIdx(0)
      setFilterErrors([])
    }
    wasOpenRef.current = open
  }, [open, filters, sortings, filterLogic, viewOptions, setChartActiveIdx])

  const filterableFields = fields.filter(f => !f.hidden)
  const sortableFields = fields.filter(f => !f.hidden)

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
    const items: ViewTabItem[] = [
      buildFilterTab({ draftFilterLogic, draftFilters, filterableFields, setDraftFilters, setDraftFilterLogic }),
      buildSortTab({ addSort, draftSorts, removeSort, sortableFields, updateSort }),
    ]
    // 字段显示 tab（仅 grid）：不进 viewOptionSchema 的原因是交互形态不同——
    // 全字段 checkbox + 字段级 hidden 禁用态，而非按类型过滤的有限选择。
    if (viewType === 'grid') {
      items.push(buildFieldsTab({ fields, setDraftOpt, viewHiddenFieldIds }))
    }
    if (viewSections.length > 0) {
      items.push(buildViewTab({
        activeChartOpts, activeIdx, chartDraft, chartList, collapsed, fields,
        isChartView, setCollapsed, setDraftOpt, viewSections, viewType,
      }))
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
          // 统一校验 + 自动归一：可转换输入静默修正（日期零填充、数字解析、空白清理等），
          // 非法输入列出全部错误并阻止保存（保留草稿供用户修正）
          const result = validateAndNormalizeDraft(draftFilters, draftSorts, fields)
          if (result.errors.length) {
            setFilterErrors(result.errors.map(e => `#${e.index + 1} ${e.message}`))
            setActiveTab('filter')
            return
          }
          setFilterErrors([])
          onSaveFilterLogic(draftFilterLogic)
          onSaveFilters(result.filters)
          onSaveSortings(result.sorts)
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
      {filterErrors.length > 0 && (
        <Alert
          type="error"
          showIcon
          style={{ marginBottom: 8 }}
          message={`筛选/排序规则有误（共 ${filterErrors.length} 处），已阻止保存`}
          description={(
            <ul style={{ margin: 0, paddingLeft: 18 }}>
              {filterErrors.map((msg, i) => <li key={i}>{msg}</li>)}
            </ul>
          )}
        />
      )}
      <Tabs activeKey={activeTab} onChange={(k) => setActiveTab(k as typeof activeTab)} size="small" items={viewTabItems} />
    </Modal>
  )
}
