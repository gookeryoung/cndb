/** 认证页背景切换器：原生按钮，循环切换效果（ADR 0016 D3 / D8）.
 *
 * 独立于 `aria-hidden` 的背景层，是认证页唯一新增的可聚焦元素；
 * `aria-label` 同时给出当前效果与下一组，键盘 / 读屏都能完成切换。
 */

import { authEffectLabel, nextAuthEffect } from './preference'
import type { AuthEffect } from './types'

export interface AuthBackgroundSwitcherProps {
  effect: AuthEffect
  onSwitch: () => void
}

export default function AuthBackgroundSwitcher({ effect, onSwitch }: AuthBackgroundSwitcherProps) {
  const label = authEffectLabel(effect)
  const nextLabel = authEffectLabel(nextAuthEffect(effect))

  return (
    <button
      type="button"
      className="auth-bg-switch"
      data-testid="auth-bg-switch"
      data-effect={effect}
      onClick={onSwitch}
      aria-label={`切换登录背景动效：当前${label}，下一组${nextLabel}`}
      title={`当前背景：${label}，点击切换`}
    >
      <span className="auth-bg-switch-icon" aria-hidden="true" />
      <span>{label}</span>
    </button>
  )
}
