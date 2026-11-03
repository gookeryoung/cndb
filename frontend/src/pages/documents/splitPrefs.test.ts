/** 文档「并排查看」本地偏好测试：默认关闭、写入 / 读取布尔、存储异常回退. */

import { afterEach, describe, expect, it, vi } from 'vitest'
import { DEFAULT_SPLIT_OPEN, loadSplitOpen, saveSplitOpen, SPLIT_PREF_KEY } from './splitPrefs'

afterEach(() => {
  vi.restoreAllMocks()
  localStorage.removeItem(SPLIT_PREF_KEY)
})

describe('splitPrefs 并排查看偏好', () => {
  it('默认关闭；写入 true / false 后可原样读回', () => {
    expect(DEFAULT_SPLIT_OPEN).toBe(false)
    expect(loadSplitOpen()).toBe(false)

    saveSplitOpen(true)
    expect(localStorage.getItem(SPLIT_PREF_KEY)).toBe('1')
    expect(loadSplitOpen()).toBe(true)

    saveSplitOpen(false)
    expect(localStorage.getItem(SPLIT_PREF_KEY)).toBe('0')
    expect(loadSplitOpen()).toBe(false)
  })

  it('非法存量值按关闭处理（不因脏数据打开并排）', () => {
    localStorage.setItem(SPLIT_PREF_KEY, 'yes')
    expect(loadSplitOpen()).toBe(false)
  })

  it('存储不可用（隐私模式）时读取 / 写入都不抛错', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('denied')
    })
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('denied')
    })
    expect(loadSplitOpen()).toBe(false)
    expect(() => saveSplitOpen(true)).not.toThrow()
  })
})
