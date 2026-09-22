/**
 * GanttView 组件测试 —— 甘特图视图.
 *
 * 覆盖：缺配置/空数据/无效日期空态 / 甘特条与进度渲染 / 今日标线开关 /
 * 分组 WBS 头 / 甘特条点击回调 / 时间刻度切换。
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import dayjs from 'dayjs'
import { fireEvent, screen, within } from '@testing-library/react'
import GanttView from './GanttView'
import { renderProviders } from '@/test/render-providers'
import { makeField } from '@/test/fixtures'
import type { Field, RowResponse, View } from '@/api'

const FIELDS: Field[] = [
    makeField({ id: 1, name: '名称', field_type: 'text' }),
    makeField({ id: 2, name: '开始', field_type: 'date' }),
    makeField({ id: 3, name: '结束', field_type: 'date' }),
    makeField({ id: 4, name: '进度', field_type: 'number' }),
    makeField({ id: 5, name: '状态', field_type: 'select', config: { options: ['进行中', '已完成'] } }),
]

/** 今天往前/往后偏移 N 天的日期串 */
const offsetDate = (days: number) => dayjs().add(days, 'day').format('YYYY-MM-DD')

function makeView(opts: Record<string, unknown> = {}): View {
    return {
        id: 1, name: '甘特', view_type: 'gantt', is_default: false,
        view_options: { start_date_field: '开始', end_date_field: '结束', ...opts },
    }
}

/** 任务A 跨约 100 天（含今天）；任务B 16 天带进度；任务C 结束早于开始应被跳过 */
const ROWS: RowResponse[] = [
    { id: 1, 名称: '任务A', 开始: offsetDate(-50), 结束: offsetDate(50), 进度: null, 状态: '进行中' },
    { id: 2, 名称: '任务B', 开始: offsetDate(-5), 结束: offsetDate(10), 进度: 50, 状态: '进行中' },
    { id: 3, 名称: '任务C', 开始: offsetDate(10), 结束: offsetDate(-5), 进度: null, 状态: '已完成' },
]

function renderGantt(props?: {
    rows?: RowResponse[]
    view?: View
    onRowClick?: (r: RowResponse) => void
}) {
    return renderProviders(
        <GanttView
            rows={props?.rows ?? ROWS}
            fields={FIELDS}
            view={props?.view ?? makeView({ title_field: '名称', progress_field: '进度' })}
            density="comfortable"
            onRowClick={props?.onRowClick}
        />,
    )
}

describe('GanttView 甘特图视图', () => {
    // jsdom 无布局引擎，滚动元素视口高度为 0，react-virtual 会直接返回空窗口；
    // 用「observe 时立即以 600px 高度回调」的 ResizeObserver 替身模拟真实视口
    beforeEach(() => {
        vi.stubGlobal(
            'ResizeObserver',
            class {
                constructor(private readonly cb: ResizeObserverCallback) { }
                observe = (el: Element) => {
                    this.cb(
                        [
                            { target: el, borderBoxSize: [{ inlineSize: 1000, blockSize: 600 }] },
                        ] as unknown as ResizeObserverEntry[],
                        this as unknown as ResizeObserver,
                    )
                }
                unobserve = () => { }
                disconnect = () => { }
            },
        )
    })

    afterEach(() => {
        vi.unstubAllGlobals()
    })

    it('缺 start/end 字段配置时显示配置引导空态', () => {
        renderProviders(
            <GanttView rows={ROWS} fields={FIELDS} view={{ id: 1, name: '甘特', view_type: 'gantt' } as View} density="comfortable" />,
        )

        expect(screen.getByText(/甘特图视图需要配置/)).toBeInTheDocument()
    })

    it('无数据时显示"暂无数据"空态', () => {
        renderGantt({ rows: [] })

        // antd Empty 的 svg <title> 与描述文案同名，限定描述节点
        expect(screen.getByText('暂无数据', { selector: '.ant-empty-description' })).toBeInTheDocument()
    })

    it('全部行日期无效时显示无有效任务空态', () => {
        renderGantt({
            rows: [{ id: 1, 名称: '任务X', 开始: '不是日期', 结束: offsetDate(1), 进度: null, 状态: '进行中' }],
        })

        expect(screen.getByText(/没有有效任务/)).toBeInTheDocument()
    })

    it('正常渲染甘特条、任务标题、任务计数与进度文本', () => {
        renderGantt()

        // 任务C 结束早于开始被跳过，只剩 A/B 两条
        expect(screen.getAllByTestId('gantt-bar')).toHaveLength(2)
        expect(screen.getByText('任务A')).toBeInTheDocument()
        expect(screen.getByText('任务B')).toBeInTheDocument()
        expect(screen.queryByText('任务C')).not.toBeInTheDocument()
        expect(screen.getByText(/共 2 个任务/)).toBeInTheDocument()
        // 进度 50 > 20 阈值，甘特条上显示百分比文本
        expect(screen.getByText('50%')).toBeInTheDocument()
    })

    it('显示今日标线与底部时间范围（前后各扩展 7/21 天）', () => {
        renderGantt()

        expect(screen.getByTestId('gantt-today-line')).toBeInTheDocument()
        // 任务A 为 -50 ~ +50，扩展后范围 -57 ~ +71
        expect(screen.getByText(`${offsetDate(-57)} ~ ${offsetDate(71)}`)).toBeInTheDocument()
    })

    it('show_today_line=false 时不渲染今日标线', () => {
        renderGantt({ view: makeView({ title_field: '名称', progress_field: '进度', show_today_line: false }) })

        expect(screen.queryByTestId('gantt-today-line')).not.toBeInTheDocument()
    })

    it('配置分组字段后左侧显示 WBS 分解头与分组标签', () => {
        renderGantt({ view: makeView({ title_field: '名称', group_field: '状态' }) })

        expect(screen.getByText('WBS 分解')).toBeInTheDocument()
        expect(screen.getByText('进行中')).toBeInTheDocument()
        // 组序号 + 组内计数
        expect(screen.getByText('G1')).toBeInTheDocument()
        expect(screen.getByText('(2)')).toBeInTheDocument()
    })

    it('点击甘特条回调对应行且不冒泡触发父行', () => {
        const onRowClick = vi.fn()
        renderGantt({ onRowClick })

        const bar = document.querySelector('[data-testid="gantt-bar"][data-row-id="1"]')
        expect(bar).not.toBeNull()
        fireEvent.click(bar!)

        expect(onRowClick).toHaveBeenCalledTimes(1)
        expect(onRowClick.mock.calls[0][0].id).toBe(1)
    })

    it('切换时间刻度为"天"后缩放档位随之重选', async () => {
        renderGantt()

        const info = screen.getByTestId('gantt-scale-info')
        // 129 天跨度 + month 刻度 → 初始档位「月-双周」
        expect(within(info).getByText('月-双周')).toBeInTheDocument()

        fireEvent.click(screen.getByRole('radio', { name: '天' }))

        // day 刻度自动选中更高像素档位「月-半周」，旧档位名消失
        expect(await screen.findByText('月-半周')).toBeInTheDocument()
        expect(screen.queryByText('月-双周')).not.toBeInTheDocument()
    })

    // ── 纵向虚拟化（非 grid 视图数据上限 2000 条，全量渲染会产生海量 DOM）──
    const BIG_ROWS: RowResponse[] = Array.from({ length: 200 }, (_, i) => ({
        id: 1000 + i,
        名称: `大任务${String(i + 1).padStart(3, '0')}`,
        开始: offsetDate(-10),
        结束: offsetDate(10),
        进度: null,
        状态: '进行中',
    }))

    it('大数据量时仅渲染滚动窗口（含 overscan）内的任务行', () => {
        renderGantt({ rows: BIG_ROWS })

        // 600px 视口 ≈ 13 行 + 两端 overscan 8，远小于 200
        const bars = screen.getAllByTestId('gantt-bar')
        expect(bars.length).toBeGreaterThan(0)
        expect(bars.length).toBeLessThan(30)
        // 总高度按 200 行 × 44px（comfortable 行高）撑开滚动条
        const body = screen.getByTestId('gantt-body')
        expect(body.querySelector('[aria-hidden="true"]')).toHaveStyle({ height: '8800px' })
        expect(screen.queryByText('大任务200')).not.toBeInTheDocument()
    })

    it('纵向滚动后窗口切片移动到对应区间', () => {
        renderGantt({ rows: BIG_ROWS })

        const body = screen.getByTestId('gantt-body')
        // jsdom 无布局引擎，scrollTop 会被 clamp 为 0；覆盖 accessor 模拟滚到第 180 行
        const top = 180 * 44
        Object.defineProperty(body, 'scrollTop', {
            configurable: true,
            get: () => top,
        })
        fireEvent.scroll(body)

        // 第 180 行进入窗口（含左列标题），首行离开窗口
        expect(screen.getByText('大任务180')).toBeInTheDocument()
        expect(screen.queryByText('大任务001')).not.toBeInTheDocument()
    })
})
