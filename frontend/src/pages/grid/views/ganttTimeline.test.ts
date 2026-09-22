/** ganttTimeline 纯函数单元测试 — 天数计算/区间扩展/双层分段/稀疏化/档位选择 */
import { describe, it, expect } from 'vitest'
import {
  daysBetween, computeTimeRange, fmtWithTemplate,
  buildCurrentSegments, buildAnchorSegments,
  markCurrentAnchors, sparseCurrentLabels,
  buildDualTimeline, selectZoomLevelForScale, autoAdjustLevel,
  ZOOM_LEVELS,
  type GanttTask, type TimelineSegment,
} from './ganttTimeline'

/** 快捷构造甘特任务（日期用本地时区，避免 UTC 偏移干扰断言） */
function makeTask(start: Date, end: Date, title = '任务'): GanttTask {
  return { row: { id: 1 }, start, end, title, progress: 0 }
}

describe('daysBetween', () => {
  it('同一天返回 1（含当天）', () => {
    expect(daysBetween(new Date(2026, 2, 10), new Date(2026, 2, 10))).toBe(1)
  })

  it('相邻两天返回 2', () => {
    expect(daysBetween(new Date(2026, 2, 10), new Date(2026, 2, 11))).toBe(2)
  })

  it('跨月计算正确', () => {
    // 2026-02-28 → 2026-03-02：diff 2 天 + 1 = 3
    expect(daysBetween(new Date(2026, 1, 28), new Date(2026, 2, 2))).toBe(3)
  })

  it('倒序传入时至少为 1（Math.max 保护）', () => {
    expect(daysBetween(new Date(2026, 2, 10), new Date(2026, 2, 1))).toBe(1)
  })
})

describe('computeTimeRange', () => {
  it('空任务列表返回 null', () => {
    expect(computeTimeRange([])).toBeNull()
  })

  it('单任务前后扩展 7/21 天', () => {
    const range = computeTimeRange([makeTask(new Date(2026, 2, 10), new Date(2026, 2, 20))])
    expect(range).not.toBeNull()
    expect(range!.min.getTime()).toBe(new Date(2026, 2, 3).getTime())
    expect(range!.max.getTime()).toBe(new Date(2026, 3, 10).getTime())
  })

  it('多任务取整体最早开始/最晚结束', () => {
    const range = computeTimeRange([
      makeTask(new Date(2026, 2, 10), new Date(2026, 2, 12)),
      makeTask(new Date(2026, 1, 1), new Date(2026, 2, 25)),
    ])
    expect(range!.min.getTime()).toBe(new Date(2026, 0, 25).getTime())
    expect(range!.max.getTime()).toBe(new Date(2026, 3, 15).getTime())
  })
})

describe('fmtWithTemplate', () => {
  it('替换 ${y}/${m}/${d} 占位符', () => {
    expect(fmtWithTemplate('${y}/${m}/${d}', new Date(2026, 2, 5))).toBe('2026/3/5')
  })

  it('计算季度 ${q}（3 月 → Q1，4 月 → Q2）', () => {
    expect(fmtWithTemplate('Q${q}', new Date(2026, 2, 15))).toBe('Q1')
    expect(fmtWithTemplate('Q${q}', new Date(2026, 3, 15))).toBe('Q2')
  })

  it('无占位符时原样返回', () => {
    expect(fmtWithTemplate('固定文本', new Date(2026, 2, 5))).toBe('固定文本')
  })
})

describe('buildCurrentSegments', () => {
  it('day 粒度：逐天分段，left 累积，showLabel 初始 false', () => {
    const segs = buildCurrentSegments(
      { min: new Date(2026, 2, 1), max: new Date(2026, 2, 5) },
      'day', 18, '${m}/${d}',
    )
    expect(segs).toHaveLength(5)
    expect(segs.map(s => s.label)).toEqual(['3/1', '3/2', '3/3', '3/4', '3/5'])
    expect(segs.map(s => s.left)).toEqual([0, 18, 36, 54, 72])
    expect(segs.every(s => s.width === 18 && s.days === 1 && !s.showLabel)).toBe(true)
  })

  it('week 粒度：对齐到周一（周日历头），每段固定 7 天', () => {
    // 2026-03-04 是周三 → 首段对齐到 03-01（周日）
    const segs = buildCurrentSegments(
      { min: new Date(2026, 2, 4), max: new Date(2026, 2, 20) },
      'week', 10, '${m}/${d}',
    )
    expect(segs).toHaveLength(3)
    expect(segs.map(s => s.label)).toEqual(['3/1', '3/8', '3/15'])
    expect(segs.every(s => s.days === 7 && s.width === 70)).toBe(true)
    expect(segs[1].left).toBe(70)
  })

  it('month 粒度：按自然月分段，首尾段按 range 裁剪天数，全部显示', () => {
    const segs = buildCurrentSegments(
      { min: new Date(2026, 2, 10), max: new Date(2026, 3, 5) },
      'month', 4, '${m}月',
    )
    expect(segs).toHaveLength(2)
    expect(segs.map(s => s.label)).toEqual(['3月', '4月'])
    expect(segs.map(s => s.days)).toEqual([22, 5]) // 03-10~03-31 / 04-01~04-05
    expect(segs.every(s => s.showLabel)).toBe(true)
  })

  it('quarter 粒度：对齐季度首月，label 为 Q1/Q2/Q3', () => {
    const segs = buildCurrentSegments(
      { min: new Date(2026, 0, 15), max: new Date(2026, 6, 2) },
      'quarter', 2, 'Q${q}',
    )
    expect(segs).toHaveLength(3)
    expect(segs.map(s => s.label)).toEqual(['Q1', 'Q2', 'Q3'])
    expect(segs.map(s => s.days)).toEqual([76, 91, 2]) // 01-15~03-31 / 04-01~06-30 / 07-01~07-02
    expect(segs[2].left).toBe(152 + 182)
  })
})

describe('buildAnchorSegments', () => {
  it('year 锚定层：按自然年分段，label 带 ${y}年，全部 showLabel', () => {
    const segs = buildAnchorSegments(
      { min: new Date(2026, 2, 10), max: new Date(2027, 1, 20) },
      'year', 1.5, '${y}年',
    )
    expect(segs).toHaveLength(2)
    expect(segs.map(s => s.label)).toEqual(['2026年', '2027年'])
    expect(segs.map(s => s.days)).toEqual([297, 51]) // 03-10~12-31 / 01-01~02-20
    expect(segs.every(s => s.showLabel)).toBe(true)
  })

  it('month 锚定层：按自然月分段，首段裁剪到 range.min', () => {
    const segs = buildAnchorSegments(
      { min: new Date(2026, 2, 10), max: new Date(2026, 3, 5) },
      'month', 10, '${y}年${m}月',
    )
    expect(segs).toHaveLength(2)
    expect(segs.map(s => s.label)).toEqual(['2026年3月', '2026年4月'])
    expect(segs.map(s => s.days)).toEqual([22, 5])
  })
})

describe('markCurrentAnchors', () => {
  it('day 粒度：仅每月 1 号标记为锚点', () => {
    const segs: TimelineSegment[] = [
      { label: '3/1', date: new Date(2026, 2, 1), width: 18, days: 1, left: 0, showLabel: false },
      { label: '3/2', date: new Date(2026, 2, 2), width: 18, days: 1, left: 18, showLabel: false },
    ]
    markCurrentAnchors(segs, 'day')
    expect(segs.map(s => s.showLabel)).toEqual([true, false])
  })

  it('week 粒度：每段本身是周一，全部标记', () => {
    const segs: TimelineSegment[] = [
      { label: 'a', date: new Date(2026, 2, 1), width: 70, days: 7, left: 0, showLabel: false },
      { label: 'b', date: new Date(2026, 2, 8), width: 70, days: 7, left: 70, showLabel: false },
    ]
    markCurrentAnchors(segs, 'week')
    expect(segs.every(s => s.showLabel)).toBe(true)
  })

  it('month/quarter 粒度：不做修改（已在 build 阶段全部显示）', () => {
    const segs: TimelineSegment[] = [
      { label: 'a', date: new Date(2026, 2, 1), width: 10, days: 5, left: 0, showLabel: false },
    ]
    markCurrentAnchors(segs, 'month')
    expect(segs[0].showLabel).toBe(false)
  })
})

describe('sparseCurrentLabels', () => {
  it('空数组原样返回', () => {
    expect(sparseCurrentLabels([], 36)).toHaveLength(0)
  })

  it('minGapPx=0 时全部显示（month/quarter 刻度）', () => {
    const segs: TimelineSegment[] = [
      { label: 'a', date: new Date(2026, 2, 1), width: 10, days: 5, left: 0, showLabel: false },
      { label: 'b', date: new Date(2026, 2, 2), width: 10, days: 5, left: 10, showLabel: false },
    ]
    sparseCurrentLabels(segs, 0)
    expect(segs.every(s => s.showLabel)).toBe(true)
  })

  it('过近的锚点被第一轮去掉，远锚点保留', () => {
    // 锚点 left 0/100/200，minGap 150 → 100 被去掉，200 保留
    const segs: TimelineSegment[] = [0, 100, 200].map((left, i) => (
      { label: `s${i}`, date: new Date(2026, 2, 1 + i), width: 50, days: 5, left, showLabel: true }
    ))
    sparseCurrentLabels(segs, 150)
    expect(segs.map(s => s.showLabel)).toEqual([true, false, true])
  })

  it('锚点之间的空位按中心间距填充，间距不足则跳过', () => {
    // 仅 seg0 是锚点，minGap 180：seg1 中心 150 不足；seg2 中心 250 够；seg3 中心 350 距上一次 250 只有 100 不够
    const segs: TimelineSegment[] = [0, 100, 200, 300].map((left, i) => (
      { label: `s${i}`, date: new Date(2026, 2, 1 + i), width: 100, days: 5, left, showLabel: i === 0 }
    ))
    sparseCurrentLabels(segs, 180)
    expect(segs.map(s => s.showLabel)).toEqual([true, false, true, false])
  })
})

describe('buildDualTimeline', () => {
  const yearRange = { min: new Date(2026, 0, 1), max: new Date(2026, 11, 31) }

  it('正常档位：返回档位定义、锚定层全显、下层稀疏化', () => {
    const { anchorSegments, currentSegments, pxPerDay, levelDef } = buildDualTimeline(yearRange, 5)
    expect(pxPerDay).toBe(18)
    expect(levelDef).toBe(ZOOM_LEVELS[5])
    expect(anchorSegments).toHaveLength(12) // 2026 年 12 个月
    expect(anchorSegments.every(s => s.showLabel)).toBe(true)
    // day 层 365 段，稀疏化后约每 2 天显示一个（minGap 36px / 18px 每格），12 个"每月 1 号"锚点全部保留
    expect(currentSegments).toHaveLength(365)
    const shown = currentSegments.filter(s => s.showLabel)
    expect(shown.length).toBeGreaterThanOrEqual(12)
    expect(shown.length).toBeLessThan(200)
  })

  it('越界档位回退到 ZOOM_LEVELS[2]（月-双周）', () => {
    const { pxPerDay, levelDef } = buildDualTimeline(yearRange, 99)
    expect(pxPerDay).toBe(7)
    expect(levelDef).toBe(ZOOM_LEVELS[2])
  })
})

describe('selectZoomLevelForScale', () => {
  it('day 粒度 30 天：选总宽度落入 [600,3000] 的最小偏离档位（月-日 18px）', () => {
    expect(selectZoomLevelForScale('day', 30)).toBe(6)
  })

  it('day 粒度 10 天：跨度太短，选最大像素档（日-细 40px）', () => {
    expect(selectZoomLevelForScale('day', 10)).toBe(7)
  })

  it('day 粒度 200 天：跨度长，选较小像素档（月-半周 14px）', () => {
    expect(selectZoomLevelForScale('day', 200)).toBe(4)
  })

  it('week 粒度 100 天：两个候选都落区间，取第一个（月-双周 7px）', () => {
    expect(selectZoomLevelForScale('week', 100)).toBe(2)
  })

  it('quarter 粒度 365 天：唯一候选年-季度档', () => {
    expect(selectZoomLevelForScale('quarter', 365)).toBe(0)
  })
})

describe('autoAdjustLevel', () => {
  it('总宽度已在视口区间内时保持档位不变', () => {
    // 30 天 * 18px = 540 ∈ [480, 1600]
    expect(autoAdjustLevel(5, 30, 800)).toBe(5)
  })

  it('总宽度太窄时逐级升档直到进入区间', () => {
    // 30 天从 1.5px=45px 开始升档，到 18px=540px 进入 [480,1600]
    expect(autoAdjustLevel(0, 30, 800)).toBe(5)
  })

  it('总宽度太宽时逐级降档直到进入区间', () => {
    // 365 天从 40px=14600px 降档，到 4px=1460px 进入 [480,1600]
    expect(autoAdjustLevel(7, 365, 800)).toBe(1)
  })

  it('已到最大档仍太窄时停在最大档', () => {
    // 5 天 * 40px = 200 < 600，档位 7 已是最大无法再升
    expect(autoAdjustLevel(7, 5, 1000)).toBe(7)
  })
})
