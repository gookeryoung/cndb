/**
 * CalendarView 组件测试 —— 日历视图.
 *
 * 覆盖：空态（缺 start_field / 无事件）/ 月视图渲染 / 自动跳转到事件月份 /
 * 周视图 / 年视图 / 事件点击回调 / 导航（下一周期、回到今天）/ 无效日期行忽略。
 */

import { describe, expect, it, vi } from 'vitest'
import dayjs from 'dayjs'
import { fireEvent, screen } from '@testing-library/react'
import CalendarView from './CalendarView'
import { renderProviders } from '@/test/render-providers'
import { makeField } from '@/test/fixtures'
import type { Field, RowResponse, View } from '@/api'

const FIELDS: Field[] = [
  makeField({ id: 1, name: '名称', field_type: 'text', is_primary: true }),
  makeField({ id: 2, name: '截止', field_type: 'date' }),
  makeField({ id: 3, name: '类型', field_type: 'select', config: { options: ['会议', '评审'] } }),
]

/** 今天前后偏移 N 天的日期串 */
const offsetDate = (days: number) => dayjs().add(days, 'day').format('YYYY-MM-DD')

const ROWS: RowResponse[] = [
  { id: 1, 名称: '发布评审', 截止: offsetDate(0), 类型: '评审' },
  { id: 2, 名称: '周会', 截止: offsetDate(2), 类型: '会议' },
]

const VIEW_OPTIONS = {
  start_field: '截止',
  title_field: '名称',
  group_field: '类型',
  calendar_mode: 'month',
}

function makeView(overrides?: Record<string, unknown>): View {
  return {
    id: 1,
    name: '日历',
    view_type: 'calendar',
    is_default: true,
    view_options: { ...VIEW_OPTIONS, ...overrides },
  } as View
}

function renderCalendar(props?: {
  rows?: RowResponse[]
  view?: View
  onRowClick?: (r: RowResponse) => void
}) {
  return renderProviders(
    <CalendarView
      rows={props?.rows ?? ROWS}
      fields={FIELDS}
      view={props?.view ?? makeView()}
      density="comfortable"
      onRowClick={props?.onRowClick}
    />,
  )
}

/** 当前月标题，如 "2026 年 9 月" */
const currentMonthTitle = () => `${dayjs().year()} 年 ${dayjs().month() + 1} 月`

describe('CalendarView 日历视图', () => {
  it('未配置 start_field 时显示配置引导空态', () => {
    renderCalendar({ view: makeView({ start_field: undefined }) })

    expect(screen.getByText(/需要配置「开始时间字段」/)).toBeInTheDocument()
  })

  it('配置了 start_field 但无数据时显示空范围空态', () => {
    renderCalendar({ rows: [] })

    expect(screen.getByText(/当前时间范围内没有事件/)).toBeInTheDocument()
  })

  it('月视图渲染事件标题、事件总数与当月标题', () => {
    renderCalendar()

    expect(screen.getByText('发布评审')).toBeInTheDocument()
    expect(screen.getByText('周会')).toBeInTheDocument()
    expect(screen.getByText(/共 2 个事件/)).toBeInTheDocument()
    expect(screen.getByText(currentMonthTitle())).toBeInTheDocument()
    // 月视图周标题行
    expect(screen.getByText('周一')).toBeInTheDocument()
  })

  it('当前月无事件时自动跳转到首个有事件的月份', () => {
    const target = dayjs().add(2, 'month')
    const rows: RowResponse[] = [
      { id: 3, 名称: '里程碑', 截止: target.format('YYYY-MM-DD') },
    ]
    renderCalendar({ rows })

    expect(screen.getByText(`${target.year()} 年 ${target.month() + 1} 月`)).toBeInTheDocument()
    expect(screen.getByText('里程碑')).toBeInTheDocument()
  })

  it('切换周视图显示本周范围与本周事件', () => {
    renderCalendar()

    fireEvent.click(screen.getByText('周'))

    expect(screen.getByText(/本周范围：\d{4}-\d{2}-\d{2} ~ \d{4}-\d{2}-\d{2}/)).toBeInTheDocument()
    // 今天的事件落在本周内
    expect(screen.getByText('发布评审')).toBeInTheDocument()
  })

  it('切换年视图显示 12 个月与当月事件计数', () => {
    renderCalendar()

    fireEvent.click(screen.getByText('年'))

    expect(screen.getByText('12月')).toBeInTheDocument()
    expect(screen.getByText(`${dayjs().month() + 1}月`)).toBeInTheDocument()
    // 两个事件都在当月
    expect(screen.getByText('2 条')).toBeInTheDocument()
  })

  it('月视图点击事件回调对应行', () => {
    const onRowClick = vi.fn()
    renderCalendar({ onRowClick })

    fireEvent.click(screen.getByText('发布评审'))

    expect(onRowClick).toHaveBeenCalledTimes(1)
    expect(onRowClick.mock.calls[0][0].id).toBe(1)
  })

  it('下一周期切换标题且回到今天恢复当前月', () => {
    renderCalendar()
    const initialTitle = currentMonthTitle()
    expect(screen.getByText(initialTitle)).toBeInTheDocument()

    // 前进一个周期（按钮仅含图标，accessible name 为图标 aria-label "right"）
    fireEvent.click(screen.getByRole('button', { name: 'right' }))
    expect(screen.queryByText(initialTitle)).not.toBeInTheDocument()

    // 回到今天（带图标按钮名称以文本结尾，正则不锚定开头）
    fireEvent.click(screen.getByRole('button', { name: /今\s*天$/ }))
    expect(screen.getByText(initialTitle)).toBeInTheDocument()
  })

  it('无效日期行被忽略不渲染为事件', () => {
    const rows: RowResponse[] = [
      { id: 1, 名称: '正常事件', 截止: offsetDate(0) },
      { id: 2, 名称: '坏行', 截止: 'not-a-date' },
    ]
    renderCalendar({ rows })

    expect(screen.getByText('正常事件')).toBeInTheDocument()
    expect(screen.getByText(/共 1 个事件/)).toBeInTheDocument()
    expect(screen.queryByText('坏行')).not.toBeInTheDocument()
  })
})
