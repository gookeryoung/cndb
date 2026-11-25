/** 「最近访问」纯函数单测（需求 0160 C4）.
 *
 * 覆盖：路径规范化（丢查询串 / hash、拒绝非工作区路径）、同 wid 去重前移、上限截断、
 * 存储损坏 / 非法条目的读取兜底。
 */

import { describe, expect, it, beforeEach } from 'vitest'
import {
  RECENT_WORKSPACES_KEY, RECENT_WORKSPACES_LIMIT, normalizeRecentPath, pushRecentWorkspace,
  readRecentWorkspaces, recordRecentWorkspace, workspaceIdFromPath,
} from './recentWorkspaces'

describe('normalizeRecentPath', () => {
  it('保留工作区落地路径，丢弃查询串与 hash', () => {
    expect(normalizeRecentPath('/w/12')).toBe('/w/12')
    expect(normalizeRecentPath('/w/12/tables')).toBe('/w/12/tables')
    expect(normalizeRecentPath('/w/12/tables?view=9#row-3')).toBe('/w/12/tables')
    expect(normalizeRecentPath('/w/12/tables/')).toBe('/w/12/tables')
  })

  it('拒绝非工作区路径与非法 id', () => {
    expect(normalizeRecentPath('/w')).toBeNull()
    expect(normalizeRecentPath('/teams/500')).toBeNull()
    expect(normalizeRecentPath('/w/abc/tables')).toBeNull()
    expect(normalizeRecentPath('')).toBeNull()
    expect(normalizeRecentPath(null)).toBeNull()
  })

  it('workspaceIdFromPath 只对工作区路径给出 id', () => {
    expect(workspaceIdFromPath('/w/12/tables?x=1')).toBe('12')
    expect(workspaceIdFromPath('/teams/500')).toBeNull()
  })
})

describe('pushRecentWorkspace', () => {
  it('同一工作区去重并前移，保持最近在首', () => {
    const a = { wid: '1', path: '/w/1/tables', ts: 1 }
    const b = { wid: '2', path: '/w/2/tables', ts: 2 }
    const next = pushRecentWorkspace([a, b], { wid: '1', path: '/w/1/documents', ts: 3 })
    expect(next.map(item => item.wid)).toEqual(['1', '2'])
    expect(next[0].path).toBe('/w/1/documents')
  })

  it('超过上限时截断（默认 5 条）', () => {
    const base = Array.from({ length: RECENT_WORKSPACES_LIMIT }, (_, i) => ({
      wid: String(i), path: `/w/${i}/tables`, ts: i,
    }))
    const next = pushRecentWorkspace(base, { wid: '99', path: '/w/99/tables', ts: 99 })
    expect(next).toHaveLength(RECENT_WORKSPACES_LIMIT)
    expect(next[0].wid).toBe('99')
  })
})

describe('读写存储', () => {
  beforeEach(() => {
    window.localStorage.clear()
  })

  it('记录最多 5 条，且非法路径不写入', () => {
    for (let i = 0; i < 7; i += 1) recordRecentWorkspace(`/w/${i}/tables`, 1000 + i)
    recordRecentWorkspace('/teams/500', 2000)
    recordRecentWorkspace('/w', 2001)

    const stored = readRecentWorkspaces()
    expect(stored).toHaveLength(RECENT_WORKSPACES_LIMIT)
    expect(stored.map(item => item.wid)).toEqual(['6', '5', '4', '3', '2'])
    expect(window.localStorage.getItem(RECENT_WORKSPACES_KEY)).toContain('"wid":"6"')
  })

  it('存储损坏 / 条目非法时读取兜底为空或过滤', () => {
    window.localStorage.setItem(RECENT_WORKSPACES_KEY, 'not-json')
    expect(readRecentWorkspaces()).toEqual([])

    window.localStorage.setItem(RECENT_WORKSPACES_KEY, JSON.stringify([
      { wid: '1', path: '/w/1/tables', ts: 10 },
      { wid: 'bad', path: '/teams/9', ts: 11 },
      { path: '/w/2/documents' },
      null,
    ]))
    const stored = readRecentWorkspaces()
    expect(stored.map(item => item.wid)).toEqual(['1', '2'])
    expect(stored[1].ts).toBe(0)
  })
})
