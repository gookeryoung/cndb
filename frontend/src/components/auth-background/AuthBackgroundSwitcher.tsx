/** 背景切换器：原生按钮，点击循环切换 5 组（ADR 0014 D3 / D8） */

import { authBackgroundLabel, nextAuthBackground } from './preference'
import type { AuthBackgroundVariant } from './types'

export interface AuthBackgroundSwitcherProps {
  value: AuthBackgroundVariant
  onChange: (next: AuthBackgroundVariant) => void
}

export default function AuthBackgroundSwitcher({ value, onChange }: AuthBackgroundSwitcherProps) {
  const label = authBackgroundLabel(value)
  const next = nextAuthBackground(value)
  const nextLabel = authBackgroundLabel(next)

  return (
    <button
      type="button"
      className="auth-bg-switch"
      data-testid="auth-bg-switch"
      onClick={() => onChange(next)}
      aria-label={`切换登录背景，当前 ${label}，下一组 ${nextLabel}`}
      title={`当前背景：${label}，点击切换`}
    >
      <span className="auth-bg-switch-dot" aria-hidden="true" />
      <span>{label}</span>
    </button>
  )
}
