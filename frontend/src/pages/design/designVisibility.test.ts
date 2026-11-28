/** 显隐状态 store 单测（需求 0193 C1 / C3 / C4）：单一来源、按设计隔离、清空恢复 */

import { describe, expect, it } from 'vitest'
import {
  clearHiddenKeys, getHiddenKeys, setHiddenKeys, toggleHiddenKey,
} from './designVisibility'

describe('designVisibility store', () => {
  it('无记录 = 全勾（空集合）', () => {
    expect(getHiddenKeys(99).size).toBe(0)
  })

  it('toggleHiddenKey：取消勾选加入、重新勾选移出', () => {
    toggleHiddenKey(1, 'design-1-0', true)
    expect(getHiddenKeys(1).has('design-1-0')).toBe(true)
    toggleHiddenKey(1, 'design-1-0', false)
    expect(getHiddenKeys(1).has('design-1-0')).toBe(false)
    clearHiddenKeys(1)
  })

  it('按设计 id 隔离（C3：侧栏树与视口共用同一 store，不串产品）', () => {
    toggleHiddenKey(2, 'design-2-0', true)
    expect(getHiddenKeys(2).has('design-2-0')).toBe(true)
    expect(getHiddenKeys(3).size).toBe(0)
    clearHiddenKeys(2)
  })

  it('setHiddenKeys 传空集合 = 全部显示（C4），记录整体删除', () => {
    toggleHiddenKey(4, 'a', true)
    setHiddenKeys(4, new Set(['b']))
    expect(getHiddenKeys(4).has('b')).toBe(true)
    setHiddenKeys(4, new Set())
    expect(getHiddenKeys(4).size).toBe(0)
  })

  it('clearHiddenKeys 清空指定设计（C4「全部显示」）', () => {
    toggleHiddenKey(5, 'a', true)
    toggleHiddenKey(5, 'b', true)
    clearHiddenKeys(5)
    expect(getHiddenKeys(5).size).toBe(0)
  })
})
