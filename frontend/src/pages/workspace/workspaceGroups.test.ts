import { describe, expect, it } from 'vitest'

import {
  filterWorkspacesByScope, flattenGroupedOrder, groupWorkspacesByTeam, hasTeamGrouping,
  scopeOptions,
} from './workspaceGroups'

const teams = [
  { id: 2, name: '市场部', updated_at: '2026-01-01T00:00:00Z' },
  { id: 1, name: '研发部', updated_at: '2026-02-01T00:00:00Z' },
]

const ws = (id: number, team_id: number | null, extra: Record<string, unknown> = {}) => ({
  id, name: `w${id}`, team_id, ...extra,
})

describe('groupWorkspacesByTeam', () => {
  it('团队组按 updated_at 倒序，个人组固定最后', () => {
    const groups = groupWorkspacesByTeam(
      [ws(1, null), ws(2, 1), ws(3, 2), ws(4, 1)],
      teams,
    )
    expect(groups.map(g => g.key)).toEqual(['team-1', 'team-2', 'personal'])
    expect(groups[0].workspaces.map(w => w.id)).toEqual([2, 4])
    expect(groups[2].isPersonal).toBe(true)
  })

  it('已收藏不进入团队组（由顶部收藏组单独承载）', () => {
    const groups = groupWorkspacesByTeam([ws(1, 1, { pinned: true }), ws(2, 1)], teams)
    expect(groups).toHaveLength(1)
    expect(groups[0].workspaces.map(w => w.id)).toEqual([2])
  })

  it('空团队不产生分组；归属团队不在列表时用工作区自带 team 摘要兜底', () => {
    const groups = groupWorkspacesByTeam(
      [ws(1, 9, { team: { id: 9, name: '外部团队' } })],
      [],
    )
    expect(groups).toHaveLength(1)
    expect(groups[0].title).toBe('外部团队')
    expect(groups[0].teamId).toBe(9)
  })

  it('全部为已收藏时没有分组', () => {
    expect(groupWorkspacesByTeam([ws(1, 1, { pinned: true })], teams)).toEqual([])
  })
})

describe('scope 过滤 / chips / 排序拼接', () => {
  const list = [ws(1, null), ws(2, 1), ws(3, 2)]

  it('按全部 / 个人 / 团队收窄', () => {
    expect(filterWorkspacesByScope(list, 'all')).toHaveLength(3)
    expect(filterWorkspacesByScope(list, 'personal').map(w => w.id)).toEqual([1])
    expect(filterWorkspacesByScope(list, 1).map(w => w.id)).toEqual([2])
  })

  it('chips 计数与团队顺序一致', () => {
    const chips = scopeOptions(teams, list)
    expect(chips.map(c => [c.value, c.count])).toEqual([
      ['all', 3],
      ['personal', 1],
      [2, 1],
      [1, 1],
    ])
  })

  it('扁平化顺序 = 已收藏 + 分组内顺序', () => {
    const groups = groupWorkspacesByTeam([ws(2, 1), ws(3, 1), ws(4, null)], teams)
    expect(flattenGroupedOrder([ws(1, 1)], groups)).toEqual([1, 2, 3, 4])
  })

  it('无团队归属时不启用团队层级', () => {
    expect(hasTeamGrouping([], [ws(1, null)])).toBe(false)
    expect(hasTeamGrouping(teams, [ws(1, null)])).toBe(false)
    expect(hasTeamGrouping(teams, [ws(1, 1)])).toBe(true)
  })
})
