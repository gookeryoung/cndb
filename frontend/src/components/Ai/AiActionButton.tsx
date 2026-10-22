/** AI 入口按钮 —— 统一 loading / disabled / 图标 / tooltip（ADR 0020 C11）.
 *
 * AI 面只做「建议 → 预览 → 确认」，按钮本身不承担请求逻辑；
 * loading 由调用方传入（来自 `useLlmAction`），避免每个页面各写一套禁用态。
 */

import type { ReactNode } from 'react'
import { Button, Tooltip, type ButtonProps } from 'antd'

export interface AiActionButtonProps extends Omit<ButtonProps, 'icon' | 'children'> {
  /** 按钮文案 */
  label?: ReactNode
  /** 前置图标 */
  icon?: ReactNode
  /** 悬停提示（为空则不包 Tooltip） */
  tooltip?: ReactNode
  /** 无障碍标签（默认取 label 文案） */
  ariaLabel?: string
  /** 测试定位 id */
  testId?: string
}

export default function AiActionButton({
  label,
  icon,
  tooltip,
  ariaLabel,
  testId = 'ai-action-button',
  ...buttonProps
}: AiActionButtonProps) {
  const button = (
    <Button
      {...buttonProps}
      icon={icon}
      aria-label={ariaLabel ?? (typeof label === 'string' ? label : undefined)}
      data-testid={testId}
    >
      {label}
    </Button>
  )
  return tooltip ? <Tooltip title={tooltip}>{button}</Tooltip> : button
}
