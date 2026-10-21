/** 认证页背景偏好：单一 localStorage 键 + 循环切换（ADR 0016 D3）.
 *
 * 读取失败、值非法、localStorage 不可用一律回落默认星座，保证登录页永不因偏好异常而失败。
 */

import {
  AUTH_BACKGROUND_META,
  AUTH_BACKGROUND_VARIANTS,
  isAuthBackgroundVariant,
  type AuthBackgroundVariant,
} from './types'

export const AUTH_BACKGROUND_STORAGE_KEY = 'cndb_auth_bg'
export const DEFAULT_AUTH_BACKGROUND: AuthBackgroundVariant = 'constellation'

export function loadAuthBackground(): AuthBackgroundVariant {
  try {
    const raw = localStorage.getItem(AUTH_BACKGROUND_STORAGE_KEY)
    if (raw && isAuthBackgroundVariant(raw)) return raw
  } catch {
    /* 隐私模式 / 存储被禁用：回落默认 */
  }
  return DEFAULT_AUTH_BACKGROUND
}

export function saveAuthBackground(variant: AuthBackgroundVariant) {
  try {
    localStorage.setItem(AUTH_BACKGROUND_STORAGE_KEY, variant)
  } catch {
    /* 写不进去不影响本次会话的视觉切换 */
  }
}

/** 按固定顺序循环，末尾回到第一组 */
export function nextAuthBackground(variant: AuthBackgroundVariant): AuthBackgroundVariant {
  const index = AUTH_BACKGROUND_VARIANTS.indexOf(variant)
  return AUTH_BACKGROUND_VARIANTS[(index + 1) % AUTH_BACKGROUND_VARIANTS.length]
}

export function authBackgroundLabel(variant: AuthBackgroundVariant): string {
  return AUTH_BACKGROUND_META.find(meta => meta.id === variant)?.label ?? variant
}
