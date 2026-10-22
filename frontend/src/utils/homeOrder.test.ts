/** 主页自定义顺序纯函数测试（ADR 0021 D3）——分组优先级 / 自定义排名 / 未登记兜底. */

import { describe, expect, it } from 'vitest'
import { buildRankMap, flattenWorkspaceOrder, sortWorkspaces } from './homeOrder'

interface Ws {
  id: number
  pinned?: boolean
}

const ws = (id: number, pinned = false): Ws => ({ id, pinned })

describe('buildRankMap', () => {
  it('按首次出现顺序建立名次，重复 id 不改名次', () => {
    const rank = buildRankMap([11, 10, 11, 12])
    expect(rank.get(11)).toBe(0)
    expect(rank.get(10)).toBe(1)
    expect(rank.get(12)).toBe(2)
  })

  it('丢弃非正整数与非法值', () => {
    const rank = buildRankMap([0, -1, 'abc', 3.5, 7])
    expect([...rank.keys()]).toEqual([7])
  })

  it('空值 / undefined 返回空映射', () => {
    expect(buildRankMap(null).size).toBe(0)
    expect(buildRankMap(undefined).size).toBe(0)
  })
})

describe('sortWorkspaces', () => {
  it('已收藏分组优先，组内再按自定义顺序', () => {
    const list = [ws(10), ws(11), ws(12, true), ws(13, true)]
    const sorted = sortWorkspaces(list, [13, 10, 12])
    expect(sorted.map(w => w.id)).toEqual([13, 12, 10, 11])
  })

  it('未登记 id 排在已登记项之后，按原 id 升序兜底', () => {
    const sorted = sortWorkspaces([ws(10), ws(11), ws(12)], [12])
    expect(sorted.map(w => w.id)).toEqual([12, 10, 11])
  })

  it('自定义顺序不改变 pinned 分组优先级', () => {
    const sorted = sortWorkspaces([ws(10), ws(11, true)], [10, 11])
    expect(sorted.map(w => w.id)).toEqual([11, 10])
  })

  it('返回新数组，不修改入参', () => {
    const list = [ws(10), ws(11)]
    const sorted = sortWorkspaces(list, [11])
    expect(sorted).not.toBe(list)
    expect(list.map(w => w.id)).toEqual([10, 11])
  })
})

describe('flattenWorkspaceOrder', () => {
  it('按「已收藏组 + 其他组」扁平化为数字 id 列表', () => {
    expect(flattenWorkspaceOrder(['12', 10], ['13', 11])).toEqual([12, 10, 13, 11])
  })
})
