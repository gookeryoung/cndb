import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  DEFAULT_OUTLINE_PREFS,
  OUTLINE_PREFS_KEY,
  OUTLINE_WIDTH_DEFAULT,
  OUTLINE_WIDTH_MAX,
  OUTLINE_WIDTH_MIN,
  clampOutlineWidth,
  loadOutlinePrefs,
  saveOutlinePrefs,
} from './outlinePrefs'

describe('outlinePrefs', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('无存储时返回默认偏好（默认展开、宽 240）', () => {
    expect(loadOutlinePrefs()).toEqual(DEFAULT_OUTLINE_PREFS)
    expect(DEFAULT_OUTLINE_PREFS).toEqual({ open: true, width: OUTLINE_WIDTH_DEFAULT })
  })

  it('损坏 JSON / 非对象 / 字段类型错误均回退默认', () => {
    localStorage.setItem(OUTLINE_PREFS_KEY, '{broken')
    expect(loadOutlinePrefs()).toEqual(DEFAULT_OUTLINE_PREFS)

    localStorage.setItem(OUTLINE_PREFS_KEY, 'null')
    expect(loadOutlinePrefs()).toEqual(DEFAULT_OUTLINE_PREFS)

    localStorage.setItem(OUTLINE_PREFS_KEY, JSON.stringify({ open: 'yes', width: 'wide' }))
    expect(loadOutlinePrefs()).toEqual(DEFAULT_OUTLINE_PREFS)
  })

  it('宽度越界与小数：收敛到 180–400 并四舍五入', () => {
    expect(clampOutlineWidth(999)).toBe(OUTLINE_WIDTH_MAX)
    expect(clampOutlineWidth(10)).toBe(OUTLINE_WIDTH_MIN)
    expect(clampOutlineWidth(236.6)).toBe(237)
    expect(clampOutlineWidth(Number.NaN)).toBe(OUTLINE_WIDTH_DEFAULT)

    localStorage.setItem(OUTLINE_PREFS_KEY, JSON.stringify({ open: false, width: 999 }))
    expect(loadOutlinePrefs()).toEqual({ open: false, width: OUTLINE_WIDTH_MAX })
  })

  it('保存后可原样读回，写入前先 clamp', () => {
    saveOutlinePrefs({ open: false, width: 300 })
    expect(loadOutlinePrefs()).toEqual({ open: false, width: 300 })

    saveOutlinePrefs({ open: true, width: 1000 })
    expect(loadOutlinePrefs()).toEqual({ open: true, width: OUTLINE_WIDTH_MAX })
  })

  it('存储写入异常不抛出', () => {
    const spy = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('quota exceeded')
    })
    expect(() => saveOutlinePrefs({ open: true, width: 240 })).not.toThrow()
    spy.mockRestore()
  })
})
