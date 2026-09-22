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
 * - done_field:        完成标志字段（boolean/select/multiselect/text 等）
 * - done_value:        完成匹配值（boolean 字段为 true/false；select 为 option value；
 *                      multiselect 为 value 数组任一命中；text 为精确匹配文本）
 * - done_bg_color:     完成卡片背景色（'auto'=跟随主题默认绿，或具体色值）
 * - done_text_color:   完成卡片标题文字颜色（'auto'=跟随主题默认灰，或具体色值）
 *                      匹配完成的卡片：绿底灰字 + 绿色左边框，隐藏截止日期徽章，
 *                      不参与紧急置顶、不计入列头紧急计数。
 */

import { memo, useMemo, useRef, useState } from 'react'
import { Tag, Progress, Tooltip, Empty, Button, Modal } from 'antd'
import { useVirtualizer } from '@tanstack/react-virtual'
import {
  CalendarOutlined,
  ClockCircleOutlined,
  WarningOutlined,
  DeleteOutlined,
  PlusOutlined,
} from '@ant-design/icons'
import type { RowResponse, Field, View, RowValues } from '@/api'
import { resolveTagColor } from '@/utils/tagColors'
import type { Density } from '@/theme/tableSettings'
import { resolveOpts, KANBAN_OPTIONS, resolveAutoField, findOptionSchema } from './viewOptionSchema'
import { formatFieldDisplayValue } from './fieldValueFormat'
import { parseDate, daysFromToday } from './dateUtils'
import { type KanbanColumnData, resolveGroupField, groupKanbanColumns, resolveDoneCtx, isDoneRow } from './kanbanBoard'

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
function AutoTag({ value, style, options }: { value: string; style?: React.CSSProperties; options?: unknown }) {
  return <Tag color={resolveTagColor(value, options)} style={{ margin: 0, ...style }}>{value}</Tag>
}

// ── 卡片排序/分组聚合已抽至 ./kanbanBoard.ts ─────────

// ── 看板卡片 ──────────────────────────────────────────

interface KanbanCardProps {
  row: RowResponse
  fields: Field[]
  opts: Record<string, unknown>   // 已由 KanbanView 顶层 resolveOpts 统一默认值
  density: Density
  onRowClick?: (r: RowResponse) => void
  onDelete?: (r: RowResponse) => void
  canDelete?: boolean
}

const KanbanCard = memo(function KanbanCard({ row, fields, opts, density, onRowClick, onDelete, canDelete }: KanbanCardProps) {
  const cs = densityCardStyle(density)
  const [hovered, setHovered] = useState(false)

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
  const doneCtx = useMemo(() => resolveDoneCtx(opts, fields), [opts, fields])
  const isDone = isDoneRow(row, doneCtx)
  const doneBg = opts.done_bg_color === 'auto' ? 'var(--cn-bg-success-subtle)' : (opts.done_bg_color as string)
  const doneTextColor = opts.done_text_color === 'auto' ? 'var(--cn-text-muted)' : (opts.done_text_color as string)
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

  // 卡片边框样式（完成态优先于逾期/紧急提醒）
  let borderStyle: React.CSSProperties = {}
  let bgStyle: React.CSSProperties = {}
  if (isDone) {
    borderStyle = { borderLeft: `${cs.borderLeftWidth}px solid #52c41a` }
    bgStyle = { background: doneBg }
  } else if (isOverdue) {
    borderStyle = { borderLeft: `${cs.borderLeftWidth}px solid #ff4d4f` }
    bgStyle = { background: 'var(--cn-bg-danger-subtle)' }
  } else if (isUrgent) {
    borderStyle = { borderLeft: `${cs.borderLeftWidth}px solid #faad14` }
    bgStyle = { background: 'var(--cn-bg-warning-subtle)' }
  }

  return (
    <div
      onClick={() => onRowClick?.(row)}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        padding: cs.padding,
        marginBottom: cs.marginBottom,
        border: '1px solid var(--cn-border)',
        borderRadius: cs.borderRadius,
        cursor: 'pointer',
        transition: 'box-shadow 0.15s ease, transform 0.15s ease',
        position: 'relative',
        ...borderStyle,
        ...bgStyle,
      }}
      onMouseOver={(e) => {
        e.currentTarget.style.boxShadow = '0 2px 8px rgba(0,0,0,0.08)'
        e.currentTarget.style.transform = 'translateY(-1px)'
      }}
      onMouseOut={(e) => {
        e.currentTarget.style.boxShadow = 'none'
        e.currentTarget.style.transform = 'none'
      }}
    >
      {/* 删除按钮 —— hover 显示 */}
      {canDelete && hovered && onDelete && (
        <Tooltip title="删除此卡片">
          <Button
            size="small"
            type="text"
            danger
            icon={<DeleteOutlined />}
            style={{ position: 'absolute', top: 4, right: 4, zIndex: 10, opacity: 0.85 }}
            onClick={(e) => {
              e.stopPropagation()
              Modal.confirm({
                title: '确定删除此卡片？',
                content: title,
                okText: '删除',
                okType: 'danger',
                cancelText: '取消',
                onOk: () => onDelete(row),
              })
            }}
          />
        </Tooltip>
      )}
      {/* 标题行（完成卡片用不显眼的灰色文字） */}
      <div style={{ fontWeight: 600, fontSize: cs.titleFontSize, marginBottom: cs.titleMarginBottom, lineHeight: cs.titleLineHeight, wordBreak: 'break-word', ...(isDone ? { color: doneTextColor } : {}) }}>
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
        {/* 完成卡片整体隐藏截止日期徽章（逾期/还剩/X天后都不再显示） */}
        {dueDateField && !isDone && <DueDateBadge dueDate={dueDate} daysLeft={daysLeft} urgentThreshold={urgentThreshold} />}
        {assigneeField && (() => {
          const assigneeFieldObj = findField(assigneeField)
          const rawVal = assigneeFieldObj
            ? formatFieldDisplayValue(assigneeFieldObj, row[assigneeField]) || '—'
            : String(row[assigneeField] || '—')
          return (
            <AutoTag
              value={rawVal}
              options={assigneeFieldObj?.config?.options}
              style={{ paddingInline: 6 }}
            />
          )
        })()}
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
})

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

// ── 看板列（虚拟化） ───────────────────────────────────

/** 卡片高度估算 —— 不同 density 给一个合理 baseline，virtualizer 运行时会用 measureElement 自动修正 */
function estimateCardHeight(density: Density): number {
  if (density === 'compact') return 100
  if (density === 'spacious') return 130
  return 115
}

/** 单列看板列组件 —— 当 rows >= 100 时启用虚拟滚动，否则全量渲染更简单 */
interface KanbanColumnProps {
  col: KanbanColumnData
  fields: Field[]
  opts: Record<string, unknown>
  density: Density
  colStyle: ReturnType<typeof densityColumnStyle>
  onRowClick?: (r: RowResponse) => void
  onDeleteCard?: (r: RowResponse) => void
  canDelete?: boolean
  onAddCard?: (initialValues: RowValues) => void
  canAdd?: boolean
}

function KanbanColumn({ col, fields, opts, density, colStyle, onRowClick, onDeleteCard, canDelete, onAddCard, canAdd }: KanbanColumnProps) {
  const scrollRef = useRef<HTMLDivElement>(null)
  const useVirtual = col.rows.length >= 100
  const estimatedSize = estimateCardHeight(density)

  const virtualizer = useVirtualizer({
    count: col.rows.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => estimatedSize,
    overscan: 5,
  })

  const items = useVirtual
    ? virtualizer.getVirtualItems()
    : col.rows.map((_, i) => ({ index: i, start: 0, size: estimatedSize, key: i, lane: 0 }))

  // 新增卡片时预填 group_field 的值
  const handleAddCard = () => {
    if (!onAddCard) return
    const groupFieldName = (opts.group_field as string)
    if (groupFieldName && col.rawValue !== undefined) {
      onAddCard({ [groupFieldName]: col.rawValue })
    } else {
      onAddCard({})
    }
  }

  return (
    <div
      key={col.key}
      style={{
        minWidth: colStyle.colMinWidth,
        maxWidth: colStyle.colMaxWidth,
        background: 'var(--cn-bg-subtle)',
        borderRadius: colStyle.borderRadius,
        padding: colStyle.colPadding,
        border: '1px solid var(--cn-border)',
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
          borderBottom: '1px solid var(--cn-border)',
          marginBottom: colStyle.colHeaderMarginBottom,
        }}
      >
        <span style={{ fontWeight: 600, fontSize: colStyle.colHeaderFontSize, color: 'var(--cn-text-primary)' }}>
          {col.title}
        </span>
        <span style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
          <span
            style={{
              fontSize: colStyle.colHeaderCountFontSize,
              color: 'var(--cn-text-muted)',
              background: 'var(--cn-bg-container)',
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
      <div ref={scrollRef} style={{ flex: 1, overflowY: 'auto' }}>
        {col.rows.length === 0 ? (
          <div
            style={{
              textAlign: 'center',
              padding: colStyle.emptyPadding,
              color: 'var(--cn-text-muted)',
              fontSize: colStyle.emptyFontSize,
            }}
          >
            无记录
          </div>
        ) : useVirtual ? (
          <div style={{ height: virtualizer.getTotalSize(), position: 'relative' }}>
            {items.map((vi) => (
              <div
                key={vi.key}
                style={{
                  position: 'absolute',
                  top: 0,
                  left: 0,
                  width: '100%',
                  height: vi.size,
                  transform: `translateY(${vi.start}px)`,
                }}
                ref={virtualizer.measureElement}
                data-index={vi.index}
              >
                <KanbanCard
                  row={col.rows[vi.index]}
                  fields={fields}
                  opts={opts}
                  density={density}
                  onRowClick={onRowClick}
                  onDelete={onDeleteCard}
                  canDelete={canDelete}
                />
              </div>
            ))}
          </div>
        ) : (
          col.rows.map((r) => (
            <KanbanCard
              key={r.id}
              row={r}
              fields={fields}
              opts={opts}
              density={density}
              onRowClick={onRowClick}
              onDelete={onDeleteCard}
              canDelete={canDelete}
            />
          ))
        )}
      </div>

      {/* 列底部：新增卡片入口 */}
      {canAdd && onAddCard && (
        <Button
          type="text"
          size="small"
          icon={<PlusOutlined />}
          onClick={handleAddCard}
          style={{ marginTop: 8, color: 'var(--cn-text-muted)', justifyContent: 'flex-start' }}
        >+ 新增卡片</Button>
      )}
    </div>
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
  onDeleteCard,
  canDelete,
  onAddCard,
  canAdd,
}: {
  rows: RowResponse[]
  fields: Field[]
  view?: View | null
  density: Density
  sortings?: Array<{ field_name: string; direction: 'asc' | 'desc' }>
  onRowClick?: (r: RowResponse) => void
  onDeleteCard?: (r: RowResponse) => void
  canDelete?: boolean
  onAddCard?: (initialValues: RowValues) => void
  canAdd?: boolean
}) {
  const opts = useMemo(
    () => resolveOpts(view?.view_options as Record<string, unknown> | undefined, KANBAN_OPTIONS),
    [view?.view_options],
  )
  const { name: groupField, def: groupFieldDef } = resolveGroupField(fields, opts)

  const colStyle = densityColumnStyle(density)

  // 按分组字段聚合成列 — 排序/分组/紧急统计逻辑在 kanbanBoard.ts（纯函数，可独立单测）
  const columns = useMemo(
    () => groupKanbanColumns(rows, fields, opts, groupField, groupFieldDef, sortings),
    [rows, groupField, groupFieldDef, opts, fields, sortings],
  )

  if (columns.length === 0) {
    return (
      <Empty
        description={rows.length === 0 ? '这张表还没有数据：回到表格视图新增一行或导入数据' : '当前视图下没有可分组的数据，试试调整筛选条件'}
        style={{ padding: 48 }}
      />
    )
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
        <KanbanColumn
          key={col.key}
          col={col}
          fields={fields}
          opts={opts}
          density={density}
          colStyle={colStyle}
          onRowClick={onRowClick}
          onDeleteCard={onDeleteCard}
          canDelete={canDelete}
          onAddCard={onAddCard}
          canAdd={canAdd}
        />
      ))}
    </div>
  )
}
