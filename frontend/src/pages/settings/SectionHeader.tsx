/** 设置页分区标题 —— GitHub 风格：标题行下紧跟分隔线，而不是在内容块之间插分隔符.
 *
 * 标题与行内辅助说明同一行，底线明确每节的起点；`topGap` 供同页多节时拉开节奏，
 * `extra` 用于标题行右侧的动作（帮助按钮 / 状态标签 / 刷新等）。
 */

import type { ReactNode } from 'react'
import { Typography } from 'antd'

const { Text } = Typography

export default function SectionHeader({ title, description, topGap = 0, extra }: {
  title: string
  description: string
  topGap?: number
  extra?: ReactNode
}) {
  return (
    <div
      className="settings-section-header"
      style={{
        marginTop: topGap,
        paddingBottom: 8,
        marginBottom: 16,
        borderBottom: '1px solid var(--cn-border)',
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        flexWrap: 'wrap',
      }}
    >
      <Text strong style={{ fontSize: 'var(--cn-text-md)' }}>{title}</Text>
      <Text type="secondary" style={{ fontSize: 'var(--cn-text-xs)' }}>{description}</Text>
      {extra != null && (
        <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 8 }}>
          {extra}
        </div>
      )}
    </div>
  )
}
