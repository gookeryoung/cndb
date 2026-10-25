/** 看板视觉元素：紧急度配色、自动配色 Tag、优先级与截止日期徽章. */

import { Tag, Tooltip } from 'antd'
import { ClockCircleOutlined } from '@ant-design/icons'
import type { Field } from '@/api'
import { resolveTagColor } from '@/utils/tagColors'
import { formatFieldDisplayValue } from '../../cells/fieldValueFormat'
import { fmtDate } from '../../cells/dateUtils'
import { mixColor } from '@/theme/themeMix'

// ── 严重程度分级（逾期/紧急按天数细分背景浓度） ──────────

/** 根据 daysLeft 返回卡片边框与背景色 style.
 *
 * 逾期（daysLeft < 0）：橙红（volcano）左边框 + 65% danger-subtle 背景，
 * 与逾期天数无关，浓度不低于"当天"。
 *
 * 当天截止（pinToday=true && daysLeft === 0）：金橙色左边框 + 55% 金黄背景，
 * 视觉上低于逾期、高于普通紧急。
 *
 * 紧急（0 ≤ daysLeft ≤ urgentThreshold）：深红左边框 + 透明红色背景。
 *
 * 正常或无截止日期返回 null（不设置背景/边框覆盖）.
 * 颜色用 color-mix 混合主题 CSS 变量，自动适配 10 种主题。
 */
export function getUrgencyVisual(
  daysLeft: number | null,
  urgentThreshold: number,
  borderLeftWidth: number,
  pinToday = false,
): { borderLeft: string; background?: string } | null {
  if (daysLeft === null) return null

  if (daysLeft < 0) {
    // 逾期：橙红 volcano + 65% danger-subtle 背景（浓度不低于当天）
    return {
      borderLeft: `${borderLeftWidth}px solid #ff7a45`,
      background: `var(--cn-mix-bg-danger-subtle-65-bg-container)`,
    }
  }

  if (pinToday && daysLeft === 0) {
    // 当天截止：金橙色边框 + 55% 金黄背景
    return {
      borderLeft: `${borderLeftWidth}px solid #fa8c16`,
      background: `var(--cn-mix-gold-55-bg-container)`,
    }
  }

  if (daysLeft <= urgentThreshold) {
    // 紧急：深红边框 + 透明红色背景（与逾期橙红、当天金橙区分）
    return {
      borderLeft: `${borderLeftWidth}px solid #cf1322`,
      background: mixColor('#ef4444', 12, 'transparent'),
    }
  }

  return null
}

// ── 自动配色 Tag ──────────────────────────────────────
export function AutoTag({ value, style, options }: { value: string; style?: React.CSSProperties; options?: unknown }) {
  return <Tag color={resolveTagColor(value, options)} style={{ margin: 0, ...style }}>{value}</Tag>
}

export function PriorityBadge({ field, value }: { field?: Field; value: unknown }) {
  if (value === null || value === undefined || value === '') return null
  const label = field ? formatFieldDisplayValue(field, value) : String(value)
  if (!label) return null
  const options = field?.config?.options
  const color = resolveTagColor(label, options)
  return <Tag color={color} style={{ margin: 0, fontWeight: 500 }}>{label}</Tag>
}

export function DueDateBadge({
  dueDate,
  daysLeft,
  urgentThreshold,
  pinToday,
}: {
  dueDate: Date | null
  daysLeft: number | null
  urgentThreshold: number
  pinToday?: boolean
}) {
  if (!dueDate || daysLeft === null) return null

  // 颜色分级：逾期橙红（volcano）；当天金橙；紧急阈值内橙色；其余默认
  const color = daysLeft < 0
    ? 'volcano'
    : pinToday && daysLeft === 0
      ? 'gold'
      : daysLeft <= urgentThreshold
        ? 'orange'
        : 'default'

  return (
    <Tooltip title={fmtDate(dueDate)}>
      <Tag color={color} icon={<ClockCircleOutlined />} style={{ margin: 0, marginLeft: 6, verticalAlign: 'middle', fontWeight: 400 }}>{daysLeft}天</Tag>
    </Tooltip>
  )
}
