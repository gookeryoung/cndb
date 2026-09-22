/**
 * WbsView 组件测试 —— WBS 工作分解结构视图.
 *
 * 覆盖：空态（缺 parent_field / 无数据）/ 默认展开第一层与进度汇总 / 折叠-展开交互 /
 * expand_all 全展开与层级编号 / 状态·负责人·日期徽章 / 进度父节点汇总 /
 * 点击行回调 / link 类型父字段建树。
 */

import { describe, expect, it, vi } from 'vitest'
import dayjs from 'dayjs'
import { fireEvent, screen } from '@testing-library/react'
import WbsView from './WbsView'
import { renderProviders } from '@/test/render-providers'
import { makeField } from '@/test/fixtures'
import type { Field, RowResponse, View } from '@/api'

const FIELDS: Field[] = [
    makeField({ id: 1, name: '名称', field_type: 'text', is_primary: true }),
    makeField({ id: 2, name: '父任务', field_type: 'text' }),
    makeField({ id: 3, name: '进度', field_type: 'number' }),
    makeField({ id: 4, name: '状态', field_type: 'select', config: { options: ['进行中', '已完成'] } }),
    makeField({ id: 5, name: '负责人', field_type: 'text' }),
    makeField({ id: 6, name: '开始日期', field_type: 'date' }),
    makeField({ id: 7, name: '结束日期', field_type: 'date' }),
    makeField({ id: 8, name: '父链接', field_type: 'link' }),
]

const offsetDate = (days: number) => dayjs().add(days, 'day').format('YYYY-MM-DD')

/** 项目A → (任务A1 → 子任务A1a, 任务A2)，父任务用文本存父行名称 */
const ROWS: RowResponse[] = [
    { id: 1, 名称: '项目A', 父任务: null, 进度: null, 状态: '进行中', 负责人: 'alice', 开始日期: offsetDate(-10), 结束日期: offsetDate(10) },
    { id: 2, 名称: '任务A1', 父任务: '项目A', 进度: 40, 状态: '进行中', 负责人: 'bob', 开始日期: offsetDate(-5), 结束日期: offsetDate(5) },
    { id: 3, 名称: '任务A2', 父任务: '项目A', 进度: 80, 状态: '已完成', 负责人: 'carol' },
    { id: 4, 名称: '子任务A1a', 父任务: '任务A1', 进度: null },
]

const VIEW_OPTIONS = {
    parent_field: '父任务',
    progress_field: '进度',
    status_field: '状态',
    assignee_field: '负责人',
    start_date_field: '开始日期',
    end_date_field: '结束日期',
}

function makeView(overrides?: Record<string, unknown>): View {
    return {
        id: 1,
        name: 'WBS',
        view_type: 'wbs',
        is_default: true,
        view_options: { ...VIEW_OPTIONS, ...overrides },
    } as View
}

function renderWbs(props?: {
    rows?: RowResponse[]
    view?: View
    onRowClick?: (r: RowResponse) => void
}) {
    return renderProviders(
        <WbsView
            rows={props?.rows ?? ROWS}
            fields={FIELDS}
            view={props?.view ?? makeView()}
            density="comfortable"
            onRowClick={props?.onRowClick}
        />,
    )
}

describe('WbsView WBS 工作分解结构视图', () => {
    it('未配置 parent_field 时显示配置引导空态', () => {
        renderWbs({ view: makeView({ parent_field: undefined }) })

        expect(screen.getByText(/需要配置 parent_field/)).toBeInTheDocument()
    })

    it('无数据显示暂无数据空态', () => {
        renderWbs({ rows: [] })

        // antd Empty 的 SVG <title> 与 description 文本重复，需限定 selector
        expect(screen.getByText('暂无数据', { selector: '.ant-empty-description' })).toBeInTheDocument()
    })

    it('默认展开第一层并显示节点统计与父节点进度汇总', () => {
        renderWbs()

        // 根节点默认展开：第二层可见、第三层折叠
        expect(screen.getByText('项目A')).toBeInTheDocument()
        expect(screen.getByText('任务A1')).toBeInTheDocument()
        expect(screen.getByText('任务A2')).toBeInTheDocument()
        expect(screen.queryByText('子任务A1a')).not.toBeInTheDocument()
        expect(screen.getByText('4 个节点 · 1 个根')).toBeInTheDocument()
        // 父节点无进度时按子节点平均汇总：(40 + 80) / 2 = 60
        expect(screen.getByText('60%')).toBeInTheDocument()
    })

    it('点击三角折叠/展开子节点', () => {
        renderWbs()

        // 折叠根节点后子树整体隐藏
        fireEvent.click(screen.getAllByTestId('wbs-toggle')[0])
        expect(screen.queryByText('任务A1')).not.toBeInTheDocument()

        // 重新展开根节点
        fireEvent.click(screen.getAllByTestId('wbs-toggle')[0])
        expect(screen.getByText('任务A1')).toBeInTheDocument()
        expect(screen.getByText('任务A2')).toBeInTheDocument()

        // 展开"任务A1"，孙节点带 1.1.1 编号
        fireEvent.click(screen.getAllByTestId('wbs-toggle')[1])
        expect(screen.getByText('子任务A1a')).toBeInTheDocument()
        expect(screen.getByText('1.1.1.')).toBeInTheDocument()

        // 再折叠"任务A1"，孙节点隐藏
        fireEvent.click(screen.getAllByTestId('wbs-toggle')[1])
        expect(screen.queryByText('子任务A1a')).not.toBeInTheDocument()
    })

    it('expand_all 时默认全部展开并显示层级编号', () => {
        renderWbs({ view: makeView({ expand_all: true }) })

        expect(screen.getByText('全部展开')).toBeInTheDocument()
        expect(screen.getByText('任务A1')).toBeInTheDocument()
        expect(screen.getByText('子任务A1a')).toBeInTheDocument()
        expect(screen.getByText('1.1.')).toBeInTheDocument()
        expect(screen.getByText('1.1.1.')).toBeInTheDocument()
    })

    it('渲染状态徽章、负责人与日期区间', () => {
        renderWbs({ view: makeView({ expand_all: true }) })

        // 状态徽章：项目A/任务A1 进行中，任务A2 已完成
        expect(screen.getAllByText('进行中').length).toBeGreaterThanOrEqual(2)
        expect(screen.getByText('已完成')).toBeInTheDocument()
        // 负责人
        expect(screen.getByText('alice')).toBeInTheDocument()
        expect(screen.getByText('bob')).toBeInTheDocument()
        expect(screen.getByText('carol')).toBeInTheDocument()
        // 项目A 的日期区间
        expect(screen.getByText(`${offsetDate(-10)} — ${offsetDate(10)}`)).toBeInTheDocument()
    })

    it('点击行回调对应行', () => {
        const onRowClick = vi.fn()
        renderWbs({ view: makeView({ expand_all: true }), onRowClick })

        fireEvent.click(screen.getByText('任务A1'))

        expect(onRowClick).toHaveBeenCalledTimes(1)
        expect(onRowClick.mock.calls[0][0].id).toBe(2)
    })

    it('link 类型父字段按父行 id 构建层级树', () => {
        const rows: RowResponse[] = [
            { id: 1, 名称: '项目A' },
            { id: 2, 名称: '任务B1', 父链接: [{ id: 1, value: '项目A' }] },
        ]
        renderWbs({ rows, view: makeView({ parent_field: '父链接' }) })

        expect(screen.getByText('2 个节点 · 1 个根')).toBeInTheDocument()
        // 根节点默认展开，子节点带 1.1 编号
        expect(screen.getByText('任务B1')).toBeInTheDocument()
        expect(screen.getByText('1.1.')).toBeInTheDocument()
    })
})
