/** 全局错误边界 —— 基于 react-error-boundary，捕获子树渲染异常，避免整页白屏.
 *
 *  使用约定：
 *  - App.tsx 在路由级 <Suspense> 外层包裹，任何 lazy 页面渲染崩溃时
 *    展示降级 UI（错误信息 + 重试 / 刷新），而非白屏；
 *  - resetErrorBoundary 仅清除边界错误状态并重挂 children（React 重新
 *    执行渲染），错误若持续复现会再次进入 fallback，不会死循环；
 *  - onError 钩子是错误上报的接入点（Sentry 等可在此接入，当前仅
 *    console.error 保留原始堆栈）。
 */

import type { ReactNode } from 'react'
import {
  ErrorBoundary as ReactErrorBoundary,
  type FallbackProps,
} from 'react-error-boundary'
import { Button } from 'antd'
import { ReloadOutlined, RedoOutlined, WarningOutlined } from '@ant-design/icons'
import { WEIGHT } from '@/theme/tokens'

/** 降级 UI —— 与 PageFallback 同风格，居中卡片 + 操作按钮 */
function ErrorFallback({ error, resetErrorBoundary }: FallbackProps) {
  return (
    <div
      role="alert"
      style={{
        padding: '64px 24px',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        gap: 12,
      }}
    >
      <WarningOutlined style={{ fontSize: 40, color: 'var(--cn-text-muted)' }} aria-hidden />
      <h2 style={{ margin: 0, fontSize: 18, fontWeight: WEIGHT.semibold, color: 'var(--cn-text-primary)' }}>
        页面出现异常
      </h2>
      <p style={{ margin: 0, color: 'var(--cn-text-secondary)', fontSize: 13, maxWidth: 480 }}>
        {error instanceof Error ? error.message : String(error)}
      </p>
      <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
        <Button type="primary" icon={<RedoOutlined />} onClick={resetErrorBoundary}>重试</Button>
        <Button icon={<ReloadOutlined />} onClick={() => window.location.reload()}>刷新页面</Button>
      </div>
    </div>
  )
}

interface ErrorBoundaryProps {
  children: ReactNode
}

export default function ErrorBoundary({ children }: ErrorBoundaryProps) {
  return (
    <ReactErrorBoundary
      FallbackComponent={ErrorFallback}
      onError={(error, info) => {
        // 错误上报接入点：当前仅保留控制台堆栈，接入 Sentry 等在此扩展
        console.error('[ErrorBoundary]', error, info.componentStack)
      }}
    >
      {children}
    </ReactErrorBoundary>
  )
}
