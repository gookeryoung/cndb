/** 认证页背景效果偏好：单键 localStorage + 循环切换（ADR 0016 D3）.
 *
 * 读取失败、值非法、localStorage 不可用一律回落默认流场粒子，
 * 保证登录页永不因偏好异常而失败。
 */

import { AUTH_EFFECTS, type AuthEffect } from './types'

export const AUTH_EFFECT_STORAGE_KEY = 'cndb_auth_bg'
export const DEFAULT_AUTH_EFFECT: AuthEffect = 'flowfield'

export function isAuthEffect(value: string): value is AuthEffect {
  return AUTH_EFFECTS.some(meta => meta.id === value)
}

export function loadAuthEffect(): AuthEffect {
  if (typeof window === 'undefined') return DEFAULT_AUTH_EFFECT
  try {
    const raw = window.localStorage.getItem(AUTH_EFFECT_STORAGE_KEY)
    if (raw && isAuthEffect(raw)) return raw
  } catch {
    /* 隐私模式 / 存储被禁用：回落默认 */
  }
  return DEFAULT_AUTH_EFFECT
}

export function saveAuthEffect(effect: AuthEffect): void {
  if (typeof window === 'undefined') return
  try {
    window.localStorage.setItem(AUTH_EFFECT_STORAGE_KEY, effect)
  } catch {
    /* 写不进去不影响本次会话的切换 */
  }
}

/** 按固定顺序循环，末尾回到第一组 */
export function nextAuthEffect(effect: AuthEffect): AuthEffect {
  const index = AUTH_EFFECTS.findIndex(meta => meta.id === effect)
  return AUTH_EFFECTS[(index + 1) % AUTH_EFFECTS.length].id
}

export function authEffectLabel(effect: AuthEffect): string {
  return AUTH_EFFECTS.find(meta => meta.id === effect)?.label ?? effect
}
