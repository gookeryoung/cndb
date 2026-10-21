import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  AUTH_EFFECT_STORAGE_KEY,
  DEFAULT_AUTH_EFFECT,
  authEffectLabel,
  isAuthEffect,
  loadAuthEffect,
  nextAuthEffect,
  saveAuthEffect,
} from './preference'

describe('认证页背景效果偏好', () => {
  beforeEach(() => {
    window.localStorage.clear()
    vi.restoreAllMocks()
  })

  it('无存储值时回落流场粒子', () => {
    expect(loadAuthEffect()).toBe(DEFAULT_AUTH_EFFECT)
  })

  it('合法值持久化后可读回', () => {
    saveAuthEffect('galaxy')

    expect(window.localStorage.getItem(AUTH_EFFECT_STORAGE_KEY)).toBe('galaxy')
    expect(loadAuthEffect()).toBe('galaxy')
  })

  it('非法值回落默认', () => {
    window.localStorage.setItem(AUTH_EFFECT_STORAGE_KEY, 'nebula')

    expect(loadAuthEffect()).toBe(DEFAULT_AUTH_EFFECT)
  })

  it('读取失败时回落默认', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('storage blocked')
    })

    expect(loadAuthEffect()).toBe(DEFAULT_AUTH_EFFECT)
  })

  it('写入失败静默忽略', () => {
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('storage blocked')
    })

    expect(() => saveAuthEffect('galaxy')).not.toThrow()
  })

  it('按固定顺序循环切换', () => {
    expect(nextAuthEffect('flowfield')).toBe('galaxy')
    expect(nextAuthEffect('galaxy')).toBe('flowfield')
  })

  it('只接受两个合法效果 id', () => {
    expect(isAuthEffect('flowfield')).toBe(true)
    expect(isAuthEffect('galaxy')).toBe(true)
    expect(isAuthEffect('rain')).toBe(false)
    expect(isAuthEffect('')).toBe(false)
  })

  it('文案与效果一一对应', () => {
    expect(authEffectLabel('flowfield')).toBe('流场粒子')
    expect(authEffectLabel('galaxy')).toBe('宇宙星系')
  })
})
