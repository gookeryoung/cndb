/** 看板视图组件 — 支持进度跟踪、紧急提醒、优先级徽章.
 *
 * view_options 扩展字段:
 * - group_field:       分组字段（select/multi_select/link）
 * - title_field:       卡片标题字段（text/主键字段/link/select 等任意可显示字段）
 * - progress_field:    进度百分比字段（number, 0-100）
 * - due_date_field:    截止日期字段（date/datetime）
 * - priority_field:    优先级字段（select）
 * - assignee_field:    负责人字段（text/link）
 * - card_fields:       卡片额外显示的字段列表（string[]）
 * - urgent_threshold_days: 临近截止多少天标记为紧急（默认 3）
 * - show_progress_bar: 是否显示进度条（默认 true，有 progress_field 时）
 * - card_sort_field:   卡片排序字段（可选）；留空则按 API 返回顺序
 * - card_sort_direction: 卡片排序方向 'asc' | 'desc'，默认 desc
 * - pin_urgent:        是否把逾期/紧急卡片置顶（默认 true，有 due_date_field 时）
 */

import { useMemo } from 'react'
import { Tag, Progress, Tooltip, Empty } from 'antd'
import {
  CalendarOutlined,
  ClockCircleOutlined,
  WarningOutlined,
} from '@ant-design/icons'
import type { RowResponse, Field, View } from '@/api'
import { resolveTagColor } from '@/utils/tagColors'
import type { Density } from '@/theme/tableSettings'
import { resolveOpts, KANBAN_OPTIONS, resolveAutoField, findOptionSchema } from './viewOptionSchema'
import {
  getSelectLabel,
  getLinkFirstLabel,
  getMultiSelectFirstLabel,
  formatFieldDisplayValue,
} from './fieldValueFormat'
import { parseDate, daysFromToday } from './dateUtils'

// ── 密度样式映射 ──────────────────────────────────────

/** 根据 density 返回看板卡片各部位的间距/字号数值 */
function densityCardStyle(density: Density) {
  if (density === 'compact') {
    return {
      padding: 8,
      marginBottom: 4,
      borderRadius: 6,
      titleFontSize: 13,
      titleMarginBottom: 4,
      titleLineHeight: 1.3,
      progressMarginBottom: 4,
      metaGap: 2,
      metaMarginBottom: 3,
      extraGap: 2,
      borderLeftWidth: 3,
    }
  }
  if (density === 'spacious') {
    return {
      padding: 16,
      marginBottom: 12,
      borderRadius: 10,
      titleFontSize: 15,
      titleMarginBottom: 10,
      titleLineHeight: 1.5,
      progressMarginBottom: 10,
      metaGap: 6,
      metaMarginBottom: 8,
      extraGap: 6,
      borderLeftWidth: 5,
    }
  }
  // comfortable（默认）
  return {
    padding: 12,
    marginBottom: 8,
    borderRadius: 8,
    titleFontSize: 14,
    titleMarginBottom: 8,
    titleLineHeight: 1.4,
    progressMarginBottom: 8,
    metaGap: 4,
    metaMarginBottom: 6,
    extraGap: 4,
    borderLeftWidth: 4,
  }
}

/** 根据 density 返回看板列容器的间距/尺寸数值 */
function densityColumnStyle(density: Density) {
  if (density === 'compact') {
    return {
      gap: 10,
      padding: 8,
      colPadding: 8,
      colMinWidth: 260,
      colMaxWidth: 320,
      colHeaderPadding: '2px 6px 6px',
      colHeaderMarginBottom: 6,
      colHeaderFontSize: 13,
      colHeaderCountFontSize: 11,
      emptyPadding: 16,
      emptyFontSize: 12,
      borderRadius: 10,
    }
  }
  if (density === 'spacious') {
    return {
      gap: 22,
      padding: 20,
      colPadding: 16,
      colMinWidth: 340,
      colMaxWidth: 400,
      colHeaderPadding: '8px 12px 14px',
      colHeaderMarginBottom: 10,
      colHeaderFontSize: 15,
      colHeaderCountFontSize: 13,
      emptyPadding: 32,
      emptyFontSize: 14,
      borderRadius: 14,
    }
  }
  // comfortable（默认）
  return {
    gap: 16,
    padding: 16,
    colPadding: 12,
    colMinWidth: 300,
    colMaxWidth: 360,
    colHeaderPadding: '4px 8px 10px',
    colHeaderMarginBottom: 8,
    colHeaderFontSize: 14,
    colHeaderCountFontSize: 12,
    emptyPadding: 24,
    emptyFontSize: 13,
    borderRadius: 12,
  }
}

// ── 工具函数（link/multi_select/select/通用格式化已抽到 ./fieldValueFormat.ts；日期工具已抽到 ./dateUtils.ts） ──

// ── 自动配色 Tag ──────────────────────────────────────
function AutoTag({ value, style }: { value: string; style?: React.CSSProperties }) {
  return <Tag color={resolveTagColor(value)} style={{ margin: 0, ...style }}>{value}</Tag>
}

// ── 卡片排序 ──────────────────────────────────────────

/** 计算卡片紧急级别（0=正常, 1=紧急, 2=逾期），用于置顶排序 */
function getUrgencyRank(
  row: RowResponse,
  dueDateField?: string,
  urgentThreshold = 3,
): number {
  if (!dueDateField) return 0
  const due = parseDate(row[dueDateField])
  if (!due) return 0
  const dl = daysFromToday(due)
  if (dl < 0) return 2
  if (dl <= urgentThreshold) return 1
  return 0
}

/** 按优先级字段值计算排序权重（高→低） */
function getPriorityRank(_row: RowResponse, field?: Field, value?: unknown): number {
  if (!field || !field.config) return 0
  const options = (field.config as Record<string, unknown>).options as
    | Array<Record<string, unknown>>
    | undefined
  if (!options) return 0
  const strVal = String(value ?? '')
  // options 数组靠前的视为更高优先级 —— 索引越小权重越大
  const idx = options.findIndex(
    (o: Record<string, unknown>) => String(o.value ?? o.name ?? '') === strVal,
  )
  return idx >= 0 ? options.length - idx : 0
}

/** 单字段比较器：按字段类型正确比较两个 row */
function compareField(
  a: RowResponse,
  b: RowResponse,
  fieldName: string,
  fields: Field[],
  direction: 'asc' | 'desc',
): number {
  const field = fields.find((f) => f.name === fieldName)
  const av = a[fieldName]
  const bv = b[fieldName]
  // null/undefined 排末尾
  const aEmpty = av === null || av === undefined || av === ''
  const bEmpty = bv === null || bv === undefined || bv === ''
  if (aEmpty && bEmpty) return 0
  if (aEmpty) return 1
  if (bEmpty) return -1

  let cmp = 0
  if (field && ['number', 'decimal', 'float', 'percentage', 'timestamp'].includes(field.field_type)) {
    cmp = Number(av) - Number(bv)
  } else if (field && ['date', 'datetime'].includes(field.field_type)) {
    const ad = new Date(String(av)).getTime()
    const bd = new Date(String(bv)).getTime()
    cmp = ad - bd
  } else {
    cmp = String(av).localeCompare(String(bv), 'zh-CN')
  }
  return direction === 'asc' ? cmp : -cmp
}

/** 对一列卡片应用完整排序：先紧急置顶，再按 card_sort_field / 级联 view_sortings 排序 */
function sortKanbanCards(
  rows: RowResponse[],
  fields: Field[],
  opts: Record<string, unknown>,
  viewSortings: Array<{ field_name: string; direction: 'asc' | 'desc' }> = [],
): RowResponse[] {
  // opts 已由 KanbanView 顶层 resolveOpts 统一默认值，此处直接取值即可
  const urgentThreshold = Number(opts.urgent_threshold_days)
  const dueDateField = opts.due_date_field as string | undefined
  const priorityField = opts.priority_field as string | undefined
  const pinUrgent = opts.pin_urgent !== false && !!dueDateField
  const cardSortField = opts.card_sort_field as string | undefined
  const cardSortDir = opts.card_sort_direction as 'asc' | 'desc'
  const priorityFieldDef = priorityField ? fields.find((f) => f.name === priorityField) : undefined

  // 把所有排序规则拼成有序列表
  // 优先级：紧急置顶 > card_sort_field > 级联 view_sortings > 优先级权重 > 创建时间倒序
  const sortKeys: Array<{ field_name: string; direction: 'asc' | 'desc' }> = []
  if (cardSortField) sortKeys.push({ field_name: cardSortField, direction: cardSortDir })
  for (const s of viewSortings) {
    if (s.field_name === cardSortField) continue // 去重
    sortKeys.push(s)
  }

  return [...rows].sort((a, b) => {
    // 1) 紧急置顶（逾期 > 紧急 > 正常）
    if (pinUrgent) {
      const au = getUrgencyRank(a, dueDateField, urgentThreshold)
      const bu = getUrgencyRank(b, dueDateField, urgentThreshold)
      if (au !== bu) return bu - au // 权重 2 排在最前
    }

    // 2) 应用配置的字段排序
    for (const sk of sortKeys) {
      const c = compareField(a, b, sk.field_name, fields, sk.direction)
      if (c !== 0) return c
    }

    // 3) 按优先级字段权重（如果有配置且未在 sortKeys 中）
    if (priorityField && !sortKeys.some((s) => s.field_name === priorityField)) {
      const pwA = getPriorityRank(a, priorityFieldDef, a[priorityField])
      const pwB = getPriorityRank(b, priorityFieldDef, b[priorityField])
      if (pwA !== pwB) return pwB - pwA
    }

    // 4) 兜底：创建时间倒序（新的在前）或 id 倒序
    const aCreated = (a.created_at as string | undefined) || ''
    const bCreated = (b.created_at as string | undefined) || ''
    if (aCreated && bCreated) {
      const c = bCreated.localeCompare(aCreated)
      if (c !== 0) return c
    }
    return (b.id as number) - (a.id as number)
  })
}

// ── 看板卡片 ──────────────────────────────────────────

interface KanbanCardProps {
  row: RowResponse
  fields: Field[]
  opts: Record<string, unknown>   // 已由 KanbanView 顶层 resolveOpts 统一默认值
  density: Density
  onRowClick?: (r: RowResponse) => void
}

function KanbanCard({ row, fields, opts, density, onRowClick }: KanbanCardProps) {
  const cs = densityCardStyle(density)

  // 字段解析（opts 已 resolve 默认值；title_field 走 schema 自动推断 fallback）
  const titleField: string = (opts.title_field as string)
    || resolveAutoField(fields, findOptionSchema('kanban', 'title_field'))
    || fields[0]?.name
    || 'id'
  const progressField = opts.progress_field as string | undefined
  const dueDateField = opts.due_date_field as string | undefined
  const priorityField = opts.priority_field as string | undefined
  const assigneeField = opts.assignee_field as string | undefined
  const cardFields = (opts.card_fields as string[] | undefined) || []
  const showProgressBar = opts.show_progress_bar !== false && !!progressField
  const urgentThreshold = Number(opts.urgent_threshold_days)

  // 查找字段定义（用于格式化复杂类型值）
  const findField = (name: string): Field | undefined => fields.find((f) => f.name === name)

  // 计算状态
  const dueDate = dueDateField ? parseDate(row[dueDateField]) : null
  const daysLeft = dueDate ? daysFromToday(dueDate) : null
  const isOverdue = daysLeft !== null && daysLeft < 0
  const isUrgent = daysLeft !== null && daysLeft >= 0 && daysLeft <= urgentThreshold

  const progressVal = progressField ? Number(row[progressField]) : NaN
  const progress = Number.isFinite(progressVal) ? Math.max(0, Math.min(100, progressVal)) : NaN

  // 卡片标题 — 用字段定义正确格式化 link/select 等类型
  const titleFieldDef = findField(titleField)
  const title = titleFieldDef
    ? formatFieldDisplayValue(titleFieldDef, row[titleField]) || String(row.id)
    : String(row[titleField] ?? row.id)

  // 卡片边框样式（紧急提醒）
  let borderStyle: React.CSSProperties = {}
  let bgStyle: React.CSSProperties = {}
  if (isOverdue) {
    borderStyle = { borderLeft: `${cs.borderLeftWidth}px solid #ff4d4f` }
    bgStyle = { background: 'var(--cn-bg-danger-subtle)' }
  } else if (isUrgent) {
    borderStyle = { borderLeft: `${cs.borderLeftWidth}px solid #faad14` }
    bgStyle = { background: 'var(--cn-bg-warning-subtle)' }
  }

  return (
    <div
      onClick={() => onRowClick?.(row)}
      style={{
        padding: cs.padding,
        marginBottom: cs.marginBottom,
        border: '1px solid var(--cn-border)',
        borderRadius: cs.borderRadius,
        cursor: 'pointer',
        transition: 'box-shadow 0.15s ease, transform 0.15s ease',
        ...borderStyle,
        ...bgStyle,
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.boxShadow = '0 2px 8px rgba(0,0,0,0.08)'
        e.currentTarget.style.transform = 'translateY(-1px)'
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.boxShadow = 'none'
        e.currentTarget.style.transform = 'none'
      }}
    >
      {/* 标题行 */}
      <div style={{ fontWeight: 600, fontSize: cs.titleFontSize, marginBottom: cs.titleMarginBottom, lineHeight: cs.titleLineHeight, wordBreak: 'break-word' }}>
        {title}
      </div>

      {/* 进度条 */}
      {showProgressBar && Number.isFinite(progress) && (
        <div style={{ marginBottom: cs.progressMarginBottom }}>
          <Progress
            percent={progress}
            size="small"
            strokeColor={progress >= 100 ? '#52c41a' : progress >= 50 ? '#1677ff' : '#faad14'}
            showInfo
          />
        </div>
      )}

      {/* 元信息行：优先级 + 截止日期 + 负责人 */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: cs.metaGap, marginBottom: cs.metaMarginBottom }}>
        {priorityField && (
          <PriorityBadge field={findField(priorityField)} value={row[priorityField]} />
        )}
        {dueDateField && <DueDateBadge dueDate={dueDate} daysLeft={daysLeft} urgentThreshold={urgentThreshold} />}
        {assigneeField && (
          <AutoTag
            value={
              findField(assigneeField)
                ? formatFieldDisplayValue(findField(assigneeField)!, row[assigneeField]) || '—'
                : String(row[assigneeField] || '—')
            }
            style={{ paddingInline: 6 }}
          />
        )}
      </div>

      {/* 卡片额外字段 */}
      {cardFields.length > 0 && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: cs.extraGap }}>
          {cardFields.map((cf) => {
            const field = findField(cf)
            if (!field) return null
            const displayVal = formatFieldDisplayValue(field, row[cf])
            if (!displayVal) return null
            return (
              <AutoTag key={cf} value={`${field.name}: ${displayVal}`} />
            )
          })}
        </div>
      )}
    </div>
  )
}

// ── 优先级徽章 ───────────────────────────────────────

function PriorityBadge({ field, value }: { field?: Field; value: unknown }) {
  if (value === null || value === undefined || value === '') return null
  const label = field ? formatFieldDisplayValue(field, value) : String(value)
  if (!label) return null
  const options = field?.config?.options
  const color = resolveTagColor(label, options)
  return <Tag color={color} style={{ margin: 0, fontWeight: 500 }}>{label}</Tag>
}

// ── 截止日期徽章 ──────────────────────────────────────

function DueDateBadge({
  dueDate,
  daysLeft,
  urgentThreshold,
}: {
  dueDate: Date | null
  daysLeft: number | null
  urgentThreshold: number
}) {
  if (!dueDate) return null

  let color: string
  let label: string
  let icon: React.ReactNode

  if (daysLeft === null) {
    color = 'default'
    label = dueDate.toISOString().slice(0, 10)
    icon = <CalendarOutlined />
  } else if (daysLeft < 0) {
    color = 'red'
    label = `逾期 ${Math.abs(daysLeft)}天`
    icon = <WarningOutlined />
  } else if (daysLeft <= urgentThreshold) {
    color = 'orange'
    label = `还剩 ${daysLeft}天`
    icon = <ClockCircleOutlined />
  } else {
    color = 'default'
    label = `${daysLeft}天后`
    icon = <CalendarOutlined />
  }

  return (
    <Tooltip title={dueDate.toISOString().slice(0, 10)}>
      <Tag color={color} icon={icon} style={{ margin: 0 }}>{label}</Tag>
    </Tooltip>
  )
}

// ── 看板主视图 ────────────────────────────────────────

export default function KanbanView({
  rows,
  fields,
  view,
  density,
  sortings,
  onRowClick,
}: {
  rows: RowResponse[]
  fields: Field[]
  view?: View | null
  density: Density
  sortings?: Array<{ field_name: string; direction: 'asc' | 'desc' }>
  onRowClick?: (r: RowResponse) => void
}) {
  const opts = useMemo(
    () => resolveOpts(view?.view_options as Record<string, unknown> | undefined, KANBAN_OPTIONS),
    [view?.view_options],
  )
  const groupField =
    (opts.group_field as string) ||
    fields.find((f) => f.field_type === 'select' || f.field_type === 'multi_select' || f.field_type === 'link')?.name

  const groupFieldDef = groupField ? fields.find((f) => f.name === groupField) : undefined

  const colStyle = densityColumnStyle(density)

  // 按分组字段聚合成列 — 正确处理 link/multiselect/select 的值
  const columns = useMemo(() => {
    const cols: Array<{ key: string; title: string; rows: RowResponse[]; urgentCount: number }> = []

    // 统计每个分组的紧急/逾期卡片数（opts 已 resolve，直接取值）
    const urgentThreshold = Number(opts.urgent_threshold_days)
    const dueDateField = opts.due_date_field as string | undefined

    const makeCol = (key: string, title: string, list: RowResponse[]) => {
      const sorted = sortKanbanCards(list, fields, opts, sortings)
      let urgentCount = 0
      if (dueDateField) {
        for (const r of sorted) {
          const dueDate = parseDate(r[dueDateField])
          if (!dueDate) continue
          const dl = daysFromToday(dueDate)
          if (dl < 0 || dl <= urgentThreshold) urgentCount++
        }
      }
      cols.push({ key, title, rows: sorted, urgentCount })
    }

    if (!groupField) {
      // 无分组 → 单列
      makeCol('all', '全部', rows)
      return cols
    }

    const groups = new Map<string, RowResponse[]>()
    for (const r of rows) {
      const rawVal = r[groupField]
      let key: string

      if (groupFieldDef) {
        const ft = groupFieldDef.field_type
        if (ft === 'link') {
          key = getLinkFirstLabel(rawVal)
        } else if (ft === 'multi_select' || ft === 'multiselect') {
          key = getMultiSelectFirstLabel(rawVal)
        } else if (ft === 'select') {
          key = getSelectLabel(groupFieldDef, rawVal) || String(rawVal || '')
        } else {
          key = rawVal !== null && rawVal !== undefined && rawVal !== '' ? String(rawVal) : ''
        }
      } else {
        // 未知字段类型，保守兜底
        if (Array.isArray(rawVal)) {
          const first = rawVal[0]
          key = first && typeof first === 'object'
            ? String((first as Record<string, unknown>).value ?? (first as Record<string, unknown>).id ?? '')
            : String(first ?? '')
        } else if (rawVal && typeof rawVal === 'object') {
          const o = rawVal as Record<string, unknown>
          key = String(o.value ?? o.label ?? o.id ?? '')
        } else {
          key = rawVal !== null && rawVal !== undefined && rawVal !== '' ? String(rawVal) : ''
        }
      }

      if (!key) key = '未分组'
      if (!groups.has(key)) groups.set(key, [])
      groups.get(key)!.push(r)
    }

    for (const [title, list] of groups) {
      makeCol(title, title, list)
    }

    return cols
  }, [rows, groupField, groupFieldDef, opts, fields, sortings])

  if (columns.length === 0) {
    return <Empty description="暂无记录" style={{ padding: 48 }} />
  }

  return (
    <div
      style={{
        display: 'flex',
        gap: colStyle.gap,
        overflowX: 'auto',
        paddingBottom: colStyle.padding,
        minHeight: 300,
      }}
    >
      {columns.map((col) => (
        <div
          key={col.key}
          style={{
            minWidth: colStyle.colMinWidth,
            maxWidth: colStyle.colMaxWidth,
            background: '#f8fafc',
            borderRadius: colStyle.borderRadius,
            padding: colStyle.colPadding,
            border: '1px solid #e2e8f0',
            flexShrink: 0,
            display: 'flex',
            flexDirection: 'column',
          }}
        >
          {/* 列头 */}
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              padding: colStyle.colHeaderPadding,
              borderBottom: '1px solid #e2e8f0',
              marginBottom: colStyle.colHeaderMarginBottom,
            }}
          >
            <span style={{ fontWeight: 600, fontSize: colStyle.colHeaderFontSize, color: '#1f2937' }}>
              {col.title}
            </span>
            <span style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
              <span
                style={{
                  fontSize: colStyle.colHeaderCountFontSize,
                  color: '#94a3b8',
                  background: '#e2e8f0',
                  padding: '2px 8px',
                  borderRadius: 10,
                }}
              >
                {col.rows.length}
              </span>
              {col.urgentCount > 0 && (
                <Tag color="red" style={{ margin: 0, fontSize: colStyle.colHeaderCountFontSize }}>
                  {col.urgentCount} 紧急
                </Tag>
              )}
            </span>
          </div>

          {/* 卡片列表 */}
          <div style={{ flex: 1, overflowY: 'auto' }}>
            {col.rows.map((r) => (
              <KanbanCard key={r.id} row={r} fields={fields} opts={opts} density={density} onRowClick={onRowClick} />
            ))}
            {col.rows.length === 0 && (
              <div
                style={{
                  textAlign: 'center',
                  padding: colStyle.emptyPadding,
                  color: '#94a3b8',
                  fontSize: colStyle.emptyFontSize,
                }}
              >
                无记录
              </div>
            )}
          </div>
        </div>
      ))}
    </div>
  )
}
