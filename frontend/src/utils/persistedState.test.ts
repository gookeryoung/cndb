/** usePersistedState / readPersisted / writePersisted —— 页面状态记忆的基础工具. */

import { act, renderHook } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { readPersisted, usePersistedState, writePersisted } from './persistedState'

describe('readPersisted / writePersisted', () => {
  it('未命中时返回 fallback，写入后可读回', () => {
    expect(readPersisted('cndb_test_key', { a: 1 })).toEqual({ a: 1 })
    writePersisted('cndb_test_key', { a: 2 })
    expect(readPersisted('cndb_test_key', { a: 1 })).toEqual({ a: 2 })
  })

  it('数据损坏时静默回落 fallback', () => {
    localStorage.setItem('cndb_test_broken', '{not json')
    expect(readPersisted('cndb_test_broken', 'fallback')).toBe('fallback')
  })

  it('session 与 local 互不干扰', () => {
    writePersisted('cndb_test_kind', 'local-value', 'local')
    writePersisted('cndb_test_kind', 'session-value', 'session')
    expect(readPersisted('cndb_test_kind', '', 'local')).toBe('local-value')
    expect(readPersisted('cndb_test_kind', '', 'session')).toBe('session-value')
  })
})

describe('usePersistedState', () => {
  it('更新即写入指定 storage，并支持函数式更新', () => {
    const { result } = renderHook(() => usePersistedState('cndb_test_state', 0, 'session'))

    act(() => result.current[1](prev => prev + 1))
    act(() => result.current[1](prev => prev + 1))

    expect(result.current[0]).toBe(2)
    expect(sessionStorage.getItem('cndb_test_state')).toBe('2')
    expect(localStorage.getItem('cndb_test_state')).toBeNull()
  })

  it('key 变化时重读对应工作区的值', () => {
    writePersisted('cndb_test_ws:1', '工作区一')
    writePersisted('cndb_test_ws:2', '工作区二')

    const { result, rerender } = renderHook(
      ({ wid }) => usePersistedState(`cndb_test_ws:${wid}`, ''),
      { initialProps: { wid: 1 } },
    )
    expect(result.current[0]).toBe('工作区一')

    rerender({ wid: 2 })
    expect(result.current[0]).toBe('工作区二')
  })
})
