/** 看板视图组件 — 支持进度跟踪、紧急提醒、优先级徽章.
 *
 * view_options 扩展字段:
 * - group_field:       分组字段（select/multi_select）
 * - title_field:       卡片标题字段（text/主键字段）
 * - progress_field:    进度百分比字段（number, 0-100）
 * - due_date_field:    截止日期字段（date/datetime）
 * - priority_field:    优先级字段（select）
 * - assignee_field:    负责人字段（text）
 * - card_fields:       卡片额外显示的字段列表（string[]）
 * - urgent_threshold_days: 临近截止多少天标记为紧急（默认 3）
 * - show_progress_bar: 是否显示进度条（默认 true，有 progress_field 时）
 */

import { useMemo } from 'react'
import { Tag, Progress, Tooltip, Empty } from 'antd'
import {
  CalendarOutlined,
  UserOutlined,
  ClockCircleOutlined,
  WarningOutlined,
} from '@ant-design/icons'
import type { RowResponse, Field, View } from '@/api'

// ── 工具函数 ──────────────────────────────────────────

/** 解析字段的 label/name 展示值 */
function getSelectLabel(field: Field, value: unknown): string {
  if (!value) return ''
  const options = (field.config as Record<string, unknown> | undefined)?.options as
    | Array<Record<string, unknown>>
    | undefined
  if (!options) return String(value)
  const strVal = String(value)
  const found = options.find((o) => String(o.value ?? o.name ?? '') === strVal)
  return found ? String(found.label ?? found.value ?? found.name ?? value) : strVal
}

/** 解析日期字段值为 Date */
function parseDate(value: unknown): Date | null {
  if (!value) return null
  const str = String(value).slice(0, 10) // 取 YYYY-MM-DD
  const d = new Date(str)
  return Number.isNaN(d.getTime()) ? null : d
}

/** 计算距今天数（负数表示已逾期） */
function daysFromToday(target: Date): number {
  const now = new Date()
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const t = new Date(target.getFullYear(), target.getMonth(), target.getDate())
  return Math.round((t.getTime() - today.getTime()) / (1000 * 60 * 60 * 24))
}

/** 优先级到颜色映射 */
const PRIORITY_COLORS: Record<string, string> = {
  紧急: 'red',
  高: 'orange',
  中: 'gold',
  低: 'blue',
  Critical: 'red',
  High: 'orange',
  Medium: 'gold',
  Low: 'blue',
  P0: 'red',
  P1: 'orange',
  P2: 'gold',
  P3: 'blue',
}

function priorityColor(value: string): string {
  return PRIORITY_COLORS[value] || 'default'
}

// ── 看板卡片 ──────────────────────────────────────────

interface KanbanCardProps {
  row: RowResponse
  fields: Field[]
  view?: View | null
  onRowClick?: (r: RowResponse) => void
}

function KanbanCard({ row, fields, view, onRowClick }: KanbanCardProps) {
  const opts = (view?.view_options || {}) as Record<string, unknown>

  // 字段解析
  const titleField = (opts.title_field as string) || fields.find((f) => f.is_primary)?.name || 'id'
  const progressField = opts.progress_field as string | undefined
  const dueDateField = opts.due_date_field as string | undefined
  const priorityField = opts.priority_field as string | undefined
  const assigneeField = opts.assignee_field as string | undefined
  const cardFields = (opts.card_fields as string[] | undefined) || []
  const showProgressBar = opts.show_progress_bar !== false && !!progressField
  const urgentThreshold = Number(opts.urgent_threshold_days) || 3

  // 计算状态
  const dueDate = dueDateField ? parseDate(row[dueDateField]) : null
  const daysLeft = dueDate ? daysFromToday(dueDate) : null
  const isOverdue = daysLeft !== null && daysLeft < 0
  const isUrgent = daysLeft !== null && daysLeft >= 0 && daysLeft <= urgentThreshold

  const progressVal = progressField ? Number(row[progressField]) : NaN
  const progress = Number.isFinite(progressVal) ? Math.max(0, Math.min(100, progressVal)) : NaN

  // 卡片标题
  const title = String(row[titleField] ?? row.id)

  // 卡片边框样式（紧急提醒）
  let borderStyle: React.CSSProperties = {}
  let bgStyle: React.CSSProperties = {}
  if (isOverdue) {
    borderStyle = { borderLeft: '4px solid #ff4d4f' }
    bgStyle = { background: '#fff2f0' }
  } else if (isUrgent) {
    borderStyle = { borderLeft: '4px solid #faad14' }
    bgStyle = { background: '#fffbe6' }
  }

  return (
    <div
      onClick={() => onRowClick?.(row)}
      style={{
        padding: 12,
        marginBottom: 8,
        border: '1px solid #e5e7eb',
        borderRadius: 8,
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
      <div style={{ fontWeight: 600, fontSize: 14, marginBottom: 8, lineHeight: 1.4, wordBreak: 'break-word' }}>
        {title}
      </div>

      {/* 进度条 */}
      {showProgressBar && Number.isFinite(progress) && (
        <div style={{ marginBottom: 8 }}>
          <Progress
            percent={progress}
            size="small"
            strokeColor={progress >= 100 ? '#52c41a' : progress >= 50 ? '#1677ff' : '#faad14'}
            showInfo
          />
        </div>
      )}

      {/* 元信息行：优先级 + 截止日期 + 负责人 */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginBottom: 6 }}>
        {priorityField && (
          <PriorityBadge field={fields.find((f) => f.name === priorityField)} value={row[priorityField]} />
        )}
        {dueDateField && <DueDateBadge dueDate={dueDate} daysLeft={daysLeft} urgentThreshold={urgentThreshold} />}
        {assigneeField && (
          <Tag icon={<UserOutlined />} style={{ margin: 0 }}>
            {String(row[assigneeField] || '—')}
          </Tag>
        )}
      </div>

      {/* 卡片额外字段 */}
      {cardFields.length > 0 && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
          {cardFields.map((cf) => {
            const field = fields.find((f) => f.name === cf)
            if (!field) return null
            const rawVal = row[cf]
            if (rawVal === null || rawVal === undefined || rawVal === '') return null
            const displayVal =
              field.field_type === 'select' || field.field_type === 'multi_select'
                ? getSelectLabel(field, rawVal)
                : String(rawVal)
            return (
              <Tag key={cf} style={{ margin: 0 }} color="blue">
                {field.name}: {displayVal}
              </Tag>
            )
          })}
        </div>
      )}

      {/* 紧急/逾期标记徽章 */}
      {isOverdue && (
        <Tooltip title={`已逾期 ${Math.abs(daysLeft!)} 天`}>
          <Tag color="red" icon={<WarningOutlined />} style={{ marginTop: 6 }}>
            已逾期 {Math.abs(daysLeft!)}天
          </Tag>
        </Tooltip>
      )}
      {isUrgent && !isOverdue && (
        <Tooltip title={`还剩 ${daysLeft} 天`}>
          <Tag color="orange" icon={<ClockCircleOutlined />} style={{ marginTop: 6 }}>
            仅剩 {daysLeft}天
          </Tag>
        </Tooltip>
      )}
    </div>
  )
}

// ── 优先级徽章 ───────────────────────────────────────

function PriorityBadge({ field, value }: { field?: Field; value: unknown }) {
  if (!value) return null
  const label = field ? getSelectLabel(field, value) : String(value)
  const color = priorityColor(label)
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
  onRowClick,
}: {
  rows: RowResponse[]
  fields: Field[]
  view?: View | null
  onRowClick?: (r: RowResponse) => void
}) {
  const opts = (view?.view_options || {}) as Record<string, unknown>
  const groupField =
    (opts.group_field as string) ||
    fields.find((f) => f.field_type === 'select' || f.field_type === 'multi_select')?.name

  // 按分组字段聚合成列
  const columns = useMemo(() => {
    const cols: Array<{ key: string; title: string; rows: RowResponse[]; urgentCount: number }> = []

    if (!groupField) {
      // 无分组 → 单列
      cols.push({ key: 'all', title: '全部', rows, urgentCount: 0 })
      return cols
    }

    const groups = new Map<string, RowResponse[]>()
    for (const r of rows) {
      let rawVal = r[groupField]
      // multi_select 可能返回数组 → 取第一个元素作为分组键
      if (Array.isArray(rawVal)) rawVal = rawVal[0]
      const key = rawVal ? String(rawVal) : '未分组'
      if (!groups.has(key)) groups.set(key, [])
      groups.get(key)!.push(r)
    }

    // 统计每个分组的紧急/逾期卡片数
    const urgentThreshold = Number(opts.urgent_threshold_days) || 3
    const dueDateField = opts.due_date_field as string | undefined

    for (const [title, list] of groups) {
      let urgentCount = 0
      if (dueDateField) {
        for (const r of list) {
          const dueDate = parseDate(r[dueDateField])
          if (!dueDate) continue
          const dl = daysFromToday(dueDate)
          if (dl < 0 || dl <= urgentThreshold) urgentCount++
        }
      }
      cols.push({ key: title, title, rows: list, urgentCount })
    }

    return cols
  }, [rows, groupField, opts])

  if (columns.length === 0) {
    return <Empty description="暂无记录" style={{ padding: 48 }} />
  }

  return (
    <div
      style={{
        display: 'flex',
        gap: 16,
        overflowX: 'auto',
        paddingBottom: 16,
        minHeight: 300,
      }}
    >
      {columns.map((col) => (
        <div
          key={col.key}
          style={{
            minWidth: 300,
            maxWidth: 360,
            background: '#f8fafc',
            borderRadius: 12,
            padding: 12,
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
              padding: '4px 8px 10px',
              borderBottom: '1px solid #e2e8f0',
              marginBottom: 8,
            }}
          >
            <span style={{ fontWeight: 600, fontSize: 14, color: '#1f2937' }}>
              {col.title}
            </span>
            <span style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
              <span
                style={{
                  fontSize: 12,
                  color: '#94a3b8',
                  background: '#e2e8f0',
                  padding: '2px 8px',
                  borderRadius: 10,
                }}
              >
                {col.rows.length}
              </span>
              {col.urgentCount > 0 && (
                <Tag color="red" style={{ margin: 0, fontSize: 11 }}>
                  {col.urgentCount} 紧急
                </Tag>
              )}
            </span>
          </div>

          {/* 卡片列表 */}
          <div style={{ flex: 1, overflowY: 'auto' }}>
            {col.rows.map((r) => (
              <KanbanCard key={r.id} row={r} fields={fields} view={view} onRowClick={onRowClick} />
            ))}
            {col.rows.length === 0 && (
              <div
                style={{
                  textAlign: 'center',
                  padding: 24,
                  color: '#94a3b8',
                  fontSize: 13,
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
