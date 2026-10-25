/** 看板视觉元素：紧急度配色、自动配色 Tag、优先级与截止日期徽章. */

import { Tag, Tooltip } from 'antd'
import { ClockCircleOutlined } from '@ant-design/icons'
import type { Field } from '@/api'
import { resolveTagColor } from '@/utils/tagColors'
import { formatFieldDisplayValue } from '../../cells/fieldValueFormat'
import { fmtDate } from '../../cells/dateUtils'
import { mixColor } from '@/theme/themeMix'
import { WEIGHT } from '@/theme/tokens'

// ── 严重程度分级（逾期/紧急按天数细分背景浓度） ──────────

/** 根据 daysLeft 返回卡片边框与背景色 style.
 *
 * 三档紧急态统一为红色系（透明红背景 + 深红左边框），靠浓度区分轻重：
 * - 逾期（daysLeft < 0）：最深红边框 `#a8071a` + 28% 透明红背景；
 * - 当天截止（pinToday=true && daysLeft === 0）：`#cf1322` 边框 + 24% 透明红背景；
 * - 紧急（0 ≤ daysLeft ≤ urgentThreshold）：`#cf1322` 边框 + 20% 透明红背景。
 *
 * 正常或无截止日期返回 null（不设置背景/边框覆盖）.
 * 背景用 color-mix 与 transparent 混合，主题下都是半透明红覆盖层。
 */
export function getUrgencyVisual(
  daysLeft: number | null,
  urgentThreshold: number,
  borderLeftWidth: number,
  pinToday = false,
): { borderLeft: string; background?: string } | null {
  if (daysLeft === null) return null

  if (daysLeft < 0) {
    // 逾期：最深红边框 + 透明红背景（浓度最高）
    return {
      borderLeft: `${borderLeftWidth}px solid #a8071a`,
      background: mixColor('#ef4444', 28, 'transparent'),
    }
  }

  if (pinToday && daysLeft === 0) {
    // 当天截止：深红边框 + 透明红背景（介于逾期和普通紧急之间）
    return {
      borderLeft: `${borderLeftWidth}px solid #cf1322`,
      background: mixColor('#ef4444', 24, 'transparent'),
    }
  }

  if (daysLeft <= urgentThreshold) {
    // 紧急：深红边框 + 透明红背景（与逾期/当天靠背景浓度区分）
    return {
      borderLeft: `${borderLeftWidth}px solid #cf1322`,
      background: mixColor('#ef4444', 20, 'transparent'),
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
  return <Tag color={color} style={{ margin: 0, fontWeight: WEIGHT.medium }}>{label}</Tag>
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
      <Tag color={color} icon={<ClockCircleOutlined />} style={{ margin: 0, marginLeft: 6, verticalAlign: 'middle', fontWeight: WEIGHT.regular }}>{daysLeft}天</Tag>
    </Tooltip>
  )
}
