/** gridViewSeed 单元测试 —— 命中 / 未命中 / 损坏 / 配额异常（ADR 0116 C8）. */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  GRID_VIEW_STATE_KEY,
  readGridViewSnapshot,
  writeGridViewSnapshot,
} from './gridViewSeed'

const snapshot = {
  activeViewId: 3,
  viewFilters: [{ field_name: 'status', op: '=', value: 'open' }],
  viewSortings: [{ field_name: 'created_at', direction: 'desc' as const }],
  viewFilterLogic: 'OR' as const,
  mode: 'grid' as const,
  offset: 0,
  limit: 50,
}

beforeEach(() => {
  sessionStorage.clear()
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('gridViewSeed', () => {
  it('写入后可按 wid/tid 读回', () => {
    writeGridViewSnapshot('7/12', snapshot)
    expect(readGridViewSnapshot('7/12')).toEqual(snapshot)
    expect(sessionStorage.getItem(GRID_VIEW_STATE_KEY)).toBeTruthy()
  })

  it('未命中返回 null', () => {
    expect(readGridViewSnapshot('7/12')).toBeNull()
    writeGridViewSnapshot('7/12', snapshot)
    expect(readGridViewSnapshot('7/13')).toBeNull()
  })

  it('损坏 JSON / 结构不符返回 null 且不抛错', () => {
    sessionStorage.setItem(GRID_VIEW_STATE_KEY, '{not json')
    expect(readGridViewSnapshot('7/12')).toBeNull()
    sessionStorage.setItem(GRID_VIEW_STATE_KEY, JSON.stringify({ '7/12': { mode: 'grid' } }))
    expect(readGridViewSnapshot('7/12')).toBeNull()
  })

  it('sessionStorage 写入抛错（隐私模式 / 配额满）时静默退化', () => {
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new DOMException('QuotaExceededError')
    })
    expect(() => writeGridViewSnapshot('7/12', snapshot)).not.toThrow()
  })

  it('最多保留 20 张表，超出时淘汰最早条目', () => {
    for (let i = 0; i < 25; i += 1) writeGridViewSnapshot(`w/${i}`, snapshot)
    const keys = Object.keys(JSON.parse(sessionStorage.getItem(GRID_VIEW_STATE_KEY)!))
    expect(keys).toHaveLength(20)
    expect(keys).not.toContain('w/0')
    expect(keys).toContain('w/24')
  })
})
