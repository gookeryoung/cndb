import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  AUTH_BACKGROUND_STORAGE_KEY,
  DEFAULT_AUTH_BACKGROUND,
  authBackgroundLabel,
  loadAuthBackground,
  nextAuthBackground,
  saveAuthBackground,
} from './preference'
import { AUTH_BACKGROUND_VARIANTS, type AuthBackgroundVariant } from './types'

describe('认证页背景偏好', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('无存储值时回落星座', () => {
    expect(loadAuthBackground()).toBe(DEFAULT_AUTH_BACKGROUND)
    expect(DEFAULT_AUTH_BACKGROUND).toBe('constellation')
  })

  it('读取合法的已保存值', () => {
    localStorage.setItem(AUTH_BACKGROUND_STORAGE_KEY, 'aurora')
    expect(loadAuthBackground()).toBe('aurora')
  })

  it('非法值回落默认', () => {
    localStorage.setItem(AUTH_BACKGROUND_STORAGE_KEY, 'not-a-variant')
    expect(loadAuthBackground()).toBe('constellation')
  })

  it('保存后可读回', () => {
    saveAuthBackground('rain')
    expect(localStorage.getItem(AUTH_BACKGROUND_STORAGE_KEY)).toBe('rain')
    expect(loadAuthBackground()).toBe('rain')
  })

  it('按固定顺序循环，末尾回到第一组', () => {
    const visited: AuthBackgroundVariant[] = [AUTH_BACKGROUND_VARIANTS[0]]
    for (let i = 0; i < AUTH_BACKGROUND_VARIANTS.length; i++) {
      visited.push(nextAuthBackground(visited[visited.length - 1]))
    }
    expect(visited.slice(0, AUTH_BACKGROUND_VARIANTS.length)).toEqual([...AUTH_BACKGROUND_VARIANTS])
    expect(visited[visited.length - 1]).toBe(AUTH_BACKGROUND_VARIANTS[0])
  })

  it('localStorage 抛错时读取与写入都不崩溃', () => {
    const getItem = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('denied')
    })
    const setItem = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('denied')
    })

    expect(loadAuthBackground()).toBe('constellation')
    expect(() => saveAuthBackground('orbs')).not.toThrow()

    getItem.mockRestore()
    setItem.mockRestore()
  })

  it('元数据覆盖全部变体且均有中文标签', () => {
    for (const variant of AUTH_BACKGROUND_VARIANTS) {
      expect(authBackgroundLabel(variant)).not.toBe(variant)
    }
  })
})
