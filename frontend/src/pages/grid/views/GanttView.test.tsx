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

    it('时间轴最右边界渲染虚线（header 双层 + body grid 共 3 处）', () => {
        renderGantt()

        const lines = screen.getAllByTestId('gantt-boundary-line')
        expect(lines).toHaveLength(3) // anchor layer + current layer + body grid
    })

    it('配置分组字段后左侧显示任务分组头与分组标签', () => {
        renderGantt({ view: makeView({ title_field: '名称', group_field: '状态' }) })

        expect(screen.getByText('任务分组')).toBeInTheDocument()
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

    it('切换时间刻度为"天"后档位重选且粒度保持 day', async () => {
        renderGantt()

        const info = screen.getByTestId('gantt-scale-info')
        // 129 天跨度 + month 刻度 → 档位保持在 month 粒度（年-月），不再漂移到 week
        expect(within(info).getByText('年-月')).toBeInTheDocument()

        fireEvent.click(screen.getByRole('radio', { name: '天' }))

        // day 刻度在 day 档位范围内重选（月-半周），旧 month 档位名消失
        expect(await screen.findByText('月-半周')).toBeInTheDocument()
        expect(screen.queryByText('年-月')).not.toBeInTheDocument()
    })

    it('切换时间刻度为"周"后档位在 week 范围内（月-周）', async () => {
        renderGantt()

        fireEvent.click(screen.getByRole('radio', { name: '周' }))

        // week 粒度区间内 level 2/3 都在，取中间 level 3 = 月-周
        expect(await screen.findByText('月-周')).toBeInTheDocument()
        expect(screen.queryByText('年-月')).not.toBeInTheDocument()
    })

    it('切换时间刻度为"季"后档位保持 quarter（年-季度）', async () => {
        renderGantt()

        fireEvent.click(screen.getByRole('radio', { name: '季' }))

        // quarter 只有 level 0 一个档位，129 天显示「年-季度」
        expect(await screen.findByText('年-季度')).toBeInTheDocument()
        expect(screen.queryByText('年-月')).not.toBeInTheDocument()
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

    // ── Header 渲染结构：覆盖 month/quarter/day/week 四种粒度的标签与定位 ──

    it('month 粒度 header：双层结构，anchor 层显示年份，current 层显示月份，全部 absolute 定位', () => {
        renderGantt() // 默认 time_scale=month → level 1 (年-月)

        const headerRows = screen.getAllByTestId('gantt-header-row')
        expect(headerRows).toHaveLength(2)

        // anchor 层（上层）
        const anchorLayer = headerRows.find(r => r.getAttribute('data-layer') === 'anchor')!
        expect(anchorLayer).not.toBeNull()
        const anchorLabels = anchorLayer.querySelectorAll('[data-testid="gantt-timeline-label"]')
        expect(anchorLabels.length).toBeGreaterThanOrEqual(1)
        // anchor 层段全部 absolute 定位
        anchorLabels.forEach(lbl => {
            expect(lbl).toHaveStyle({ position: 'absolute' })
        })
        // anchor 层应该有年份标签（2025/2026）
        expect(anchorLayer.textContent).toMatch(/\d{4}年/)

        // current 层（下层）—— 这是之前 month/quarter 模式下出 bug 的层
        const currentLayer = headerRows.find(r => r.getAttribute('data-layer') === 'current')!
        expect(currentLayer).not.toBeNull()
        const currentLabels = currentLayer.querySelectorAll('[data-testid="gantt-timeline-label"]')
        expect(currentLabels.length).toBeGreaterThanOrEqual(1)
        // 关键修复：current 层段也必须是 absolute 定位（之前 month 模式下错误退回 relative 导致垂直堆叠）
        currentLabels.forEach(lbl => {
            expect(lbl).toHaveStyle({ position: 'absolute' })
        })
        // current 层应该有月份标签
        expect(currentLayer.textContent).toMatch(/\d+月/)
    })

    it('quarter 粒度 header：双层结构，current 层显示季度标签，absolute 定位不丢失', async () => {
        renderGantt()

        fireEvent.click(screen.getByRole('radio', { name: '季' }))
        await screen.findByText('年-季度')

        const headerRows = screen.getAllByTestId('gantt-header-row')
        expect(headerRows).toHaveLength(2)

        const currentLayer = headerRows.find(r => r.getAttribute('data-layer') === 'current')!
        const currentLabels = currentLayer.querySelectorAll('[data-testid="gantt-timeline-label"]')
        expect(currentLabels.length).toBeGreaterThanOrEqual(1)
        // quarter 模式下 current 层的段同样必须是 absolute
        currentLabels.forEach(lbl => {
            expect(lbl).toHaveStyle({ position: 'absolute' })
        })
        // current 层应含 Q1/Q2/Q3/Q4 中的若干
        expect(currentLayer.textContent).toMatch(/Q[1-4]/)
    })

    it('day 粒度 header：current 层稀疏化后仍正确 absolute 定位', async () => {
        renderGantt()

        fireEvent.click(screen.getByRole('radio', { name: '天' }))
        await screen.findByText('月-半周')

        const headerRows = screen.getAllByTestId('gantt-header-row')
        const currentLayer = headerRows.find(r => r.getAttribute('data-layer') === 'current')!
        const currentLabels = currentLayer.querySelectorAll('[data-testid="gantt-timeline-label"]')
        // day 粒度下标签稀疏化，应该有若干 visible label（每月 1 号锚点 + 间隔填充）
        expect(currentLabels.length).toBeGreaterThan(0)
        // 全部 absolute 定位
        currentLabels.forEach(lbl => {
            expect(lbl).toHaveStyle({ position: 'absolute' })
        })
    })

    it('week 粒度 header：current 层的段 absolute 定位 + 稀疏化', async () => {
        renderGantt()

        fireEvent.click(screen.getByRole('radio', { name: '周' }))
        await screen.findByText('月-周')

        const headerRows = screen.getAllByTestId('gantt-header-row')
        const currentLayer = headerRows.find(r => r.getAttribute('data-layer') === 'current')!
        const currentLabels = currentLayer.querySelectorAll('[data-testid="gantt-timeline-label"]')
        expect(currentLabels.length).toBeGreaterThan(0)
        currentLabels.forEach(lbl => {
            expect(lbl).toHaveStyle({ position: 'absolute' })
        })
    })
})
