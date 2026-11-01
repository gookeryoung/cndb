/** dashboard 只读分享链接与展示态解析测试（ADR 0077 P1）.
 *
 * 重点锁定：链接参数稳定、展示态不回落到默认视图、非 dashboard 视图拒绝展示、
 * 剪贴板写入的是当前页面路径 + 目标视图 id。
 */

import { describe, expect, it, vi, afterEach } from 'vitest'

import type { View } from '@/api'
import {
  buildDashboardShareUrl,
  copyDashboardShareLink,
  resolvePresentTarget,
} from './dashboardShare'

function makeView(id: number, view_type: string, name = `视图 ${id}`): View {
  return { id, name, view_type, is_default: false } as unknown as View
}

const VIEWS: View[] = [
  makeView(10, 'grid'),
  makeView(11, 'dashboard', '销售画布'),
  makeView(12, 'kanban'),
]

describe('buildDashboardShareUrl', () => {
  it('拼接 origin + pathname，只带 view / mode=dashboard / present=1', () => {
    expect(buildDashboardShareUrl({ origin: 'https://cndb.example', pathname: '/w/3/tables/9', viewId: 11 }))
      .toBe('https://cndb.example/w/3/tables/9?view=11&mode=dashboard&present=1')
  })

  it('数字与字符串 id 产出相同链接', () => {
    const input = { origin: 'https://cndb.example', pathname: '/w/3/tables/9' }
    expect(buildDashboardShareUrl({ ...input, viewId: '11' })).toBe(buildDashboardShareUrl({ ...input, viewId: 11 }))
  })
})

describe('resolvePresentTarget', () => {
  it('非展示态保持既有回落逻辑（normal）', () => {
    expect(resolvePresentTarget(VIEWS, null, false)).toEqual({ kind: 'normal' })
    expect(resolvePresentTarget(VIEWS, '99', false)).toEqual({ kind: 'normal' })
  })

  it('缺 view 参数 → missing_view', () => {
    expect(resolvePresentTarget(VIEWS, null, true)).toEqual({ kind: 'invalid', reason: 'missing_view' })
    expect(resolvePresentTarget(VIEWS, '   ', true)).toEqual({ kind: 'invalid', reason: 'missing_view' })
  })

  it('视图不在可见列表 → not_visible，且不回落到默认视图', () => {
    expect(resolvePresentTarget(VIEWS, '99', true)).toEqual({ kind: 'invalid', reason: 'not_visible' })
  })

  it('目标不是 dashboard → not_dashboard', () => {
    expect(resolvePresentTarget(VIEWS, '10', true)).toEqual({ kind: 'invalid', reason: 'not_dashboard' })
  })

  it('命中可见 dashboard 视图 → present', () => {
    const target = resolvePresentTarget(VIEWS, '11', true)
    expect(target.kind).toBe('present')
    expect(target.kind === 'present' && target.view.name).toBe('销售画布')
  })
})

describe('copyDashboardShareLink', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('把当前页面路径 + 目标视图的只读链接写入剪贴板', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } })
    vi.spyOn(window, 'location', 'get').mockReturnValue({
      ...window.location, origin: 'https://cndb.example', pathname: '/w/3/tables/9',
    } as Location)

    const url = await copyDashboardShareLink(11)

    expect(writeText).toHaveBeenCalledWith(
      'https://cndb.example/w/3/tables/9?view=11&mode=dashboard&present=1',
    )
    expect(url).toBe('https://cndb.example/w/3/tables/9?view=11&mode=dashboard&present=1')
  })
})
