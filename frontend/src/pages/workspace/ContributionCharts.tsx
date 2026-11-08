/** 贡献统计图表 —— GitHub 风格日历热力图 + 按月折线趋势（需求 0126）.
 *
 * - 日历：近 12 个月按天着色，行 = 星期，列 = 周；单元格用原生 title 提示，避免数百个 Tooltip 组件。
 * - 趋势：默认工作区总量，可切换单个成员；按自然月汇总 `daily`，ECharts 平滑折线 + 面积。
 * - 数据为空时仍渲染日历骨架（GitHub 同形）与空态趋势说明。
 */

import { useEffect, useMemo, useRef, useState } from 'react'
import { Empty, Select } from 'antd'
import * as echarts from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent } from 'echarts/components'
import { SVGRenderer } from 'echarts/renderers'
import type { EChartsCoreOption, EChartsType } from 'echarts/core'
import type { WorkspaceContributionItem, WorkspaceContributions } from '@/api'
import { useTheme } from '@/theme/ThemeProvider'

echarts.use([LineChart, GridComponent, TooltipComponent, SVGRenderer])

const WEEKDAY_LABELS = ['日', '一', '二', '三', '四', '五', '六']
const ALL_USERS = 'all'

interface CalendarCell {
  date: string
  count: number
  inRange: boolean
}

interface CalendarWeek {
  cells: CalendarCell[]
}

function parseDate(iso: string): Date {
  const [year, month, day] = iso.slice(0, 10).split('-').map(Number)
  return new Date(year, month - 1, day)
}

function isoDate(value: Date): string {
  const month = String(value.getMonth() + 1).padStart(2, '0')
  const day = String(value.getDate()).padStart(2, '0')
  return `${value.getFullYear()}-${month}-${day}`
}

/** 列 = 周（周日起），行 = 星期；窗口外补齐的格子置灰不展示计数 */
function buildCalendar(
  startIso: string,
  endIso: string,
  counts: Map<string, number>,
): { weeks: CalendarWeek[]; monthLabels: Array<string | null> } {
  const start = parseDate(startIso)
  const end = parseDate(endIso)
  const cursor = new Date(start)
  cursor.setDate(start.getDate() - start.getDay())
  const gridEnd = new Date(end)
  gridEnd.setDate(end.getDate() + (6 - end.getDay()))

  const weeks: CalendarWeek[] = []
  const monthLabels: Array<string | null> = []
  let lastMonth = -1
  while (cursor <= gridEnd) {
    const cells: CalendarCell[] = []
    for (let index = 0; index < 7; index += 1) {
      const day = new Date(cursor)
      const inRange = day >= start && day <= end
      const iso = isoDate(day)
      cells.push({ date: iso, count: inRange ? (counts.get(iso) ?? 0) : 0, inRange })
      cursor.setDate(cursor.getDate() + 1)
    }
    const firstDay = parseDate(cells[0].date)
    const month = firstDay.getMonth()
    monthLabels.push(month !== lastMonth ? `${month + 1}月` : null)
    lastMonth = month
    weeks.push({ cells })
  }
  return { weeks, monthLabels }
}

/** 非零日按最大值四分位分档（0 无贡献，1-4 逐级加深） */
function buildLevels(counts: Map<string, number>): (count: number) => number {
  let max = 0
  for (const count of counts.values()) {
    if (count > max) max = count
  }
  return (count: number): number => {
    if (count <= 0 || max <= 0) return 0
    const ratio = count / max
    if (ratio <= 0.25) return 1
    if (ratio <= 0.5) return 2
    if (ratio <= 0.75) return 3
    return 4
  }
}

/** 按自然月汇总窗口内的计数 */
function buildMonthly(
  startIso: string,
  endIso: string,
  counts: Map<string, number>,
): { labels: string[]; values: number[] } {
  const start = parseDate(startIso)
  const end = parseDate(endIso)
  const cursor = new Date(start.getFullYear(), start.getMonth(), 1)
  const labels: string[] = []
  const values: number[] = []
  while (cursor <= end) {
    const year = cursor.getFullYear()
    const month = cursor.getMonth()
    let total = 0
    const daysInMonth = new Date(year, month + 1, 0).getDate()
    for (let day = 1; day <= daysInMonth; day += 1) {
      const iso = isoDate(new Date(year, month, day))
      if (iso < startIso || iso > endIso) continue
      total += counts.get(iso) ?? 0
    }
    labels.push(`${month + 1}月`)
    values.push(total)
    cursor.setMonth(cursor.getMonth() + 1)
  }
  return { labels, values }
}

function readCssVar(name: string, fallback: string): string {
  if (typeof document === 'undefined') return fallback
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  return value || fallback
}

function memberName(item: WorkspaceContributionItem): string {
  return item.nickname?.trim() || item.username?.trim() || `用户 ${item.user_id}`
}

function TrendChart({ labels, values }: { labels: string[]; values: number[] }) {
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<EChartsType | null>(null)
  const { isDark } = useTheme()

  const option = useMemo<EChartsCoreOption>(() => {
    const text = readCssVar('--cn-text-secondary', '#6b7280')
    const border = readCssVar('--cn-border-soft', '#d1d5db')
    return {
      grid: { left: 8, right: 12, top: 16, bottom: 8, containLabel: true },
      tooltip: { trigger: 'axis', valueFormatter: (value: unknown) => `${value} 次` },
      xAxis: {
        type: 'category',
        boundaryGap: false,
        data: labels,
        axisLine: { lineStyle: { color: border } },
        axisTick: { show: false },
        axisLabel: { color: text },
      },
      yAxis: {
        type: 'value',
        minInterval: 1,
        axisLabel: { color: text },
        splitLine: { lineStyle: { color: border, type: 'dashed' } },
      },
      series: [
        {
          type: 'line',
          smooth: true,
          showSymbol: false,
          data: values,
          lineStyle: { width: 2, color: '#2da44e' },
          itemStyle: { color: '#2da44e' },
          areaStyle: { color: isDark ? 'rgba(45, 164, 78, 0.22)' : 'rgba(45, 164, 78, 0.12)' },
        },
      ],
    }
  }, [labels, values, isDark])

  useEffect(() => {
    if (!containerRef.current) return
    const chart = echarts.init(containerRef.current, undefined, { renderer: 'svg' })
    chartRef.current = chart
    const resizeObserver = new ResizeObserver(() => chart.resize())
    resizeObserver.observe(containerRef.current)
    return () => {
      resizeObserver.disconnect()
      chart.dispose()
      chartRef.current = null
    }
  }, [])

  useEffect(() => {
    chartRef.current?.setOption(option, true)
  }, [option])

  return <div ref={containerRef} data-testid="ws-contribution-trend-chart" style={{ height: 220 }} />
}

export default function ContributionCharts({
  data,
  items,
}: {
  data?: WorkspaceContributions
  items: WorkspaceContributionItem[]
}) {
  const [scope, setScope] = useState<string>(ALL_USERS)

  const startIso = data?.timeline_start ?? ''
  const endIso = data?.timeline_end ?? ''

  const { allCounts, userCounts } = useMemo(() => {
    const all = new Map<string, number>()
    const byUser = new Map<string, Map<string, number>>()
    for (const entry of data?.daily ?? []) {
      all.set(entry.date, (all.get(entry.date) ?? 0) + entry.count)
      const key = String(entry.user_id)
      const dailyOfUser = byUser.get(key) ?? new Map<string, number>()
      dailyOfUser.set(entry.date, (dailyOfUser.get(entry.date) ?? 0) + entry.count)
      byUser.set(key, dailyOfUser)
    }
    return { allCounts: all, userCounts: byUser }
  }, [data?.daily])

  const emptyCounts = useMemo(() => new Map<string, number>(), [])
  const calendarCounts = useMemo(
    () => (scope === ALL_USERS ? allCounts : (userCounts.get(scope) ?? emptyCounts)),
    [scope, allCounts, userCounts, emptyCounts],
  )
  const calendar = useMemo(
    () => (startIso && endIso ? buildCalendar(startIso, endIso, calendarCounts) : { weeks: [], monthLabels: [] }),
    [startIso, endIso, calendarCounts],
  )
  const levelOf = useMemo(() => buildLevels(calendarCounts), [calendarCounts])
  const monthly = useMemo(
    () => (startIso && endIso ? buildMonthly(startIso, endIso, calendarCounts) : { labels: [], values: [] }),
    [startIso, endIso, calendarCounts],
  )
  const hasActivity = calendarCounts.size > 0

  return (
    <div className="cn-contrib-charts">
      <section className="cn-ws-stats-section" data-testid="ws-contribution-calendar">
        <div className="cn-ws-stats-section-title">近 12 个月贡献日历</div>
        {calendar.weeks.length === 0 ? (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无贡献数据" />
        ) : (
          <>
            <div className="cn-contrib-calendar-scroll">
              <div className="cn-contrib-months" aria-hidden="true">
                {calendar.monthLabels.map((label, index) => (
                  <span key={index} className="cn-contrib-month">{label}</span>
                ))}
              </div>
              <div className="cn-contrib-calendar-body">
                <div className="cn-contrib-weekdays" aria-hidden="true">
                  {WEEKDAY_LABELS.map((label, index) => (
                    <span key={label} className={index % 2 === 1 ? 'cn-contrib-weekday' : 'cn-contrib-weekday cn-contrib-weekday-hidden'}>
                      {label}
                    </span>
                  ))}
                </div>
                <div className="cn-contrib-weeks">
                  {calendar.weeks.map((week, weekIndex) => (
                    <div key={weekIndex} className="cn-contrib-week">
                      {week.cells.map(cell => (
                        <span
                          key={cell.date}
                          className={`cn-contrib-cell lvl-${levelOf(cell.count)}${cell.inRange ? '' : ' out-of-range'}`}
                          title={cell.inRange ? `${cell.date}：${cell.count} 次贡献` : undefined}
                          aria-label={cell.inRange ? `${cell.date} 共 ${cell.count} 次贡献` : undefined}
                        />
                      ))}
                    </div>
                  ))}
                </div>
              </div>
            </div>
            <div className="cn-contrib-legend" aria-hidden="true">
              <span>少</span>
              {[0, 1, 2, 3, 4].map(level => (
                <span key={level} className={`cn-contrib-cell lvl-${level}`} />
              ))}
              <span>多</span>
            </div>
          </>
        )}
      </section>

      <section className="cn-ws-stats-section" data-testid="ws-contribution-trend">
        <div className="cn-contrib-trend-head">
          <div className="cn-ws-stats-section-title">贡献趋势（按月）</div>
          <Select
            data-testid="ws-contribution-trend-scope"
            size="small"
            value={scope}
            onChange={setScope}
            style={{ width: 180 }}
            options={[
              { value: ALL_USERS, label: '工作区总量' },
              ...items.map(item => ({ value: String(item.user_id), label: memberName(item) })),
            ]}
          />
        </div>
        {hasActivity ? (
          <TrendChart labels={monthly.labels} values={monthly.values} />
        ) : (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="所选范围暂无贡献数据" />
        )}
      </section>
    </div>
  )
}
