/** dashboard widget 外壳：统一卡片边框 + 标题 + 加载/错误/空态（ADR 0023 P0）.
 *
 * 只负责壳与状态呈现，具体内容由 widgets/* 注入；四态优先级：
 * 错误 > 加载 > 空 > 内容。
 */

import type { ReactNode } from 'react'
import { Empty, Skeleton } from 'antd'
import { WEIGHT } from '@/theme/tokens'

export interface WidgetShellProps {
  title?: string
  /** 错误文案；非空时覆盖内容显示错误态 */
  error?: string
  /** 数据加载中 */
  loading?: boolean
  /** 数据为空（text 组件恒为 false） */
  empty?: boolean
  emptyText?: string
  /** 卡片高度撑满栅格单元 */
  children: ReactNode
  testId?: string
}

export default function WidgetShell({
  title,
  error,
  loading = false,
  empty = false,
  emptyText = '暂无数据',
  children,
  testId = 'dashboard-widget',
}: WidgetShellProps) {
  let body: ReactNode = children
  if (error) {
    body = (
      <div
        data-testid={`${testId}-error`}
        style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--cn-danger, #cf1322)', fontSize: 12 }}
      >
        {error}
      </div>
    )
  } else if (loading) {
    body = (
      <div data-testid={`${testId}-loading`} style={{ flex: 1, minHeight: 0 }}>
        <Skeleton active title={false} paragraph={{ rows: 3 }} />
      </div>
    )
  } else if (empty) {
    body = (
      <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={emptyText} data-testid={`${testId}-empty`} />
      </div>
    )
  }

  return (
    <div
      data-testid={testId}
      style={{
        height: '100%', minHeight: 0, display: 'flex', flexDirection: 'column',
        padding: '10px 12px', boxSizing: 'border-box', overflow: 'hidden',
        background: 'var(--cn-bg-container)', border: '1px solid var(--cn-border)', borderRadius: 8,
      }}
    >
      {title && (
        <div
          data-testid={`${testId}-title`}
          style={{
            flexShrink: 0, marginBottom: 8, fontWeight: WEIGHT.semibold, fontSize: 13,
            color: 'var(--cn-text-primary)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
          }}
        >
          {title}
        </div>
      )}
      <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column' }}>{body}</div>
    </div>
  )
}
