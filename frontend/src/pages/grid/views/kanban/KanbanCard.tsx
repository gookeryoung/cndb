/** 看板卡片 —— 标题/进度/优先级/负责人/额外字段/截止日期与完成勾选. */

import { memo, useEffect, useMemo, useRef, useState } from 'react'
import { App as AntApp, Button, Checkbox, Progress, Tooltip } from 'antd'
import { CheckCircleFilled, DeleteOutlined } from '@ant-design/icons'
import type { Field, RowResponse, RowValues } from '@/api'
import type { Density } from '@/theme/tableSettings'
import { findOptionSchema, resolveAutoField } from '../../view-config/viewOptionSchema'
import { formatFieldDisplayValue } from '../../cells/fieldValueFormat'
import { daysFromToday, parseDate } from '../../cells/dateUtils'
import { buildDoneToggleValue, isDoneRow, resolveDoneCtx } from '../kanbanBoard'
import { densityCardStyle } from './kanbanDensity'
import { AutoTag, DueDateBadge, PriorityBadge, getUrgencyVisual } from './kanbanVisuals'
import { WEIGHT } from '@/theme/tokens'

// ── 看板卡片 ──────────────────────────────────────────

export interface KanbanCardProps {
  row: RowResponse
  fields: Field[]
  opts: Record<string, unknown>   // 已由 KanbanView 顶层 resolveOpts 统一默认值
  density: Density
  onRowClick?: (r: RowResponse) => void
  onDelete?: (r: RowResponse) => void
  canDelete?: boolean
  /** 勾选/取消完成回调 —— 传入 done_field 的目标值；未配置完成标志或无权限时不传 */
  onToggleDone?: (r: RowResponse, values: RowValues) => void
  canEdit?: boolean
}

export const KanbanCard = memo(function KanbanCard({ row, fields, opts, density, onRowClick, onDelete, canDelete, onToggleDone, canEdit }: KanbanCardProps) {
  const { modal } = AntApp.useApp()
  const cs = densityCardStyle(density)
  const [hovered, setHovered] = useState(false)

  // 完成庆祝动画：仅在「未完成 → 完成」翻转时触发（初始加载即为完成的卡片不播）
  const [celebrate, setCelebrate] = useState(false)
  const prevDoneRef = useRef<boolean | null>(null)

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
  const pinToday = opts.pin_today !== false && !!dueDateField

  // 查找字段定义（用于格式化复杂类型值）
  const findField = (name: string): Field | undefined => fields.find((f) => f.name === name)

  // 计算状态
  const doneCtx = useMemo(() => resolveDoneCtx(opts, fields), [opts, fields])
  const isDone = isDoneRow(row, doneCtx)

  // 检测「未完成 → 完成」翻转，触发 1.2s 庆祝动画（卡片弹跳 + 彩纸）
  // prevDoneRef 以 null 表示「尚未初始化」：首次 effect 只记录当前状态，刷新加载时不播动画
  useEffect(() => {
    if (prevDoneRef.current === null) {
      prevDoneRef.current = isDone
      return
    }
    const wasDone = prevDoneRef.current
    prevDoneRef.current = isDone
    if (isDone && !wasDone) {
      setCelebrate(true)
      const timer = setTimeout(() => setCelebrate(false), 1200)
      return () => clearTimeout(timer)
    }
  }, [isDone])
  // 配置了完成标志且可编辑时，卡片 hover 显示勾选框（未完成未勾选 / 已完成已勾选，可双向切换）
  const showDoneToggle = !!canEdit && !!doneCtx && !!onToggleDone
  const dueDate = dueDateField ? parseDate(row[dueDateField]) : null
  const daysLeft = dueDate ? daysFromToday(dueDate) : null

  const progressVal = progressField ? Number(row[progressField]) : NaN
  const progress = Number.isFinite(progressVal) ? Math.max(0, Math.min(100, progressVal)) : NaN

  // 负责人显示值 —— 格式化后为空（null/undefined/''/空数组等）时不渲染 Tag，避免空白占位标签
  const assigneeFieldObj = assigneeField ? findField(assigneeField) : undefined
  const assigneeDisplay = assigneeField
    ? assigneeFieldObj
      ? formatFieldDisplayValue(assigneeFieldObj, row[assigneeField])
      : String(row[assigneeField] ?? '')
    : ''

  // 卡片标题 — 用字段定义正确格式化 link/select 等类型
  const titleFieldDef = findField(titleField)
  const title = titleFieldDef
    ? formatFieldDisplayValue(titleFieldDef, row[titleField]) || String(row.id)
    : String(row[titleField] ?? row.id)

  // 卡片边框样式（完成态优先于逾期/紧急提醒）
  // 注意：不能与 border 简写属性混用（React 会警告并可能渲染异常），
  // 下方 style 已拆成 borderTop/borderRight/borderBottom，此处仅控制 borderLeft
  let borderStyle: React.CSSProperties = { borderLeft: '1px solid var(--cn-border)' }
  let bgStyle: React.CSSProperties = {}
  if (isDone) {
    borderStyle = { borderLeft: `${cs.borderLeftWidth}px solid #52c41a` }
    bgStyle = { background: 'var(--cn-bg-success-subtle)' }
  } else {
    const urgency = getUrgencyVisual(daysLeft, urgentThreshold, cs.borderLeftWidth, pinToday)
    if (urgency) {
      borderStyle = { borderLeft: urgency.borderLeft }
      if (urgency.background) bgStyle = { background: urgency.background }
    }
  }

  return (
    <div
      onClick={() => onRowClick?.(row)}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      className={celebrate ? 'kb-done-celebrate' : undefined}
      style={{
        padding: cs.padding,
        marginBottom: cs.marginBottom,
        borderTop: '1px solid var(--cn-border)',
        borderRight: '1px solid var(--cn-border)',
        borderBottom: '1px solid var(--cn-border)',
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
      {/* 庆祝彩纸 —— 仅完成瞬间播放（kb-confetti 内粒子角度/颜色由 CSS nth-child 定义） */}
      {celebrate && (
        <div className="kb-confetti" aria-hidden>
          {Array.from({ length: 10 }, (_, i) => <i key={i} />)}
        </div>
      )}
      {/* 标题行（flex 行容器：左边标题文本 + 日期徽章 + 完成对勾，右边完成勾选框 + 删除按钮；
          alignItems: center 保证所有元素纵向居中对齐；hover 才显示的控件以 flex 子项加入控制组，不再绝对定位） */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 6,
          marginBottom: cs.titleMarginBottom,
        }}
      >
        <div
          style={{
            flex: 1,
            minWidth: 0,
            fontWeight: WEIGHT.semibold,
            fontSize: cs.titleFontSize,
            lineHeight: cs.titleLineHeight,
            wordBreak: 'break-word',
            ...(isDone ? { color: 'var(--cn-text-muted)', textDecoration: 'line-through' } : {}),
          }}
        >
          {title}
          {isDone && <CheckCircleFilled className={celebrate ? 'kb-check-pop' : undefined} style={{ color: '#52c41a', marginLeft: 6, fontSize: cs.titleFontSize }} />}
          {/* 完成卡片整体隐藏截止日期徽章（X天/-X天都不再显示） */}
          {dueDateField && !isDone && <DueDateBadge dueDate={dueDate} daysLeft={daysLeft} urgentThreshold={urgentThreshold} pinToday={pinToday} />}
        </div>
        {/* hover 显示的控制组 —— flex 子项，右侧对齐，与标题/日期徽章同一水平基线 */}
        {hovered && (showDoneToggle || (canDelete && onDelete)) && (
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 2,
              flexShrink: 0,
              marginLeft: 4,
            }}
            onClick={(e) => e.stopPropagation()}
          >
            {/* 完成勾选框 —— hover 显示，未完成/已完成都可见（点击双向切换）；
                无值操作符（is_empty/is_not_empty）下 buildDoneToggleValue 返回 undefined 哨兵 → 不渲染勾选框 */}
            {showDoneToggle && doneCtx && buildDoneToggleValue(row, doneCtx) !== undefined && (
              <Tooltip title={isDone ? '取消完成' : '标记为完成'}>
                <Checkbox
                  checked={isDone}
                  onChange={() => onToggleDone!(row, { [doneCtx!.field]: buildDoneToggleValue(row, doneCtx!) } as RowValues)}
                  style={{ margin: 0 }}
                />
              </Tooltip>
            )}
            {/* 删除按钮 —— hover 显示 */}
            {canDelete && onDelete && (
              <Tooltip title="删除此卡片">
                <Button
                  size="small"
                  type="text"
                  danger
                  icon={<DeleteOutlined />}
                  style={{ opacity: 0.85 }}
                  onClick={() => {
                    modal.confirm({
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
          </div>
        )}
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

      {/* 元信息行：优先级 + 负责人（两者都未配置时不占位；值为空的字段不渲染 Tag，避免空白标签） */}
      {(priorityField || assigneeField) && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: cs.metaGap, marginBottom: cs.metaMarginBottom }}>
          {priorityField && (
            <PriorityBadge field={findField(priorityField)} value={row[priorityField]} />
          )}
          {assigneeDisplay && (
            <AutoTag
              value={assigneeDisplay}
              options={assigneeFieldObj?.config?.options}
              style={{ paddingInline: 6 }}
            />
          )}
        </div>
      )}

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
