/**
 * TreeView 组件测试 —— 通用层级树视图.
 *
 * 覆盖：空态（缺 parent_field / 无数据 / 无法成树）/ 默认全部展开与节点统计 /
 * expand_all 关闭只展开第一层 / 折叠-展开交互 / show_numbering 层级编号 /
 * 状态·负责人徽章与子节点数量 / 点击行回调 / link 类型父字段建树 / 标题字段自动推断。
 */

import { describe, expect, it, vi } from 'vitest'
import { fireEvent, screen } from '@testing-library/react'
import TreeView from './TreeView'
import { renderProviders } from '@/test/render-providers'
import { makeField } from '@/test/fixtures'
import type { Field, RowResponse, View } from '@/api'

const FIELDS: Field[] = [
    makeField({ id: 1, name: '名称', field_type: 'text' }),
    makeField({ id: 2, name: '父节点', field_type: 'text' }),
    makeField({ id: 3, name: '状态', field_type: 'select', config: { options: ['启用', '停用'] } }),
    makeField({ id: 4, name: '负责人', field_type: 'text' }),
    makeField({ id: 5, name: '父链接', field_type: 'link' }),
]

/** 目录A → (子目录A1 → 文件A1a, 子目录A2)，父节点用文本存父行名称 */
const ROWS: RowResponse[] = [
    { id: 1, 名称: '目录A', 父节点: null, 状态: '启用', 负责人: 'alice' },
    { id: 2, 名称: '子目录A1', 父节点: '目录A', 状态: '启用', 负责人: 'bob' },
    { id: 3, 名称: '子目录A2', 父节点: '目录A', 状态: '停用', 负责人: 'carol' },
    { id: 4, 名称: '文件A1a', 父节点: '子目录A1' },
]

const VIEW_OPTIONS = {
    parent_field: '父节点',
    status_field: '状态',
    assignee_field: '负责人',
}

function makeView(overrides?: Record<string, unknown>): View {
    return {
        id: 1,
        name: '树',
        view_type: 'tree',
        is_default: true,
        view_options: { ...VIEW_OPTIONS, ...overrides },
    } as View
}

function renderTree(props?: {
    rows?: RowResponse[]
    fields?: Field[]
    view?: View
    onRowClick?: (r: RowResponse) => void
}) {
    return renderProviders(
        <TreeView
            rows={props?.rows ?? ROWS}
            fields={props?.fields ?? FIELDS}
            view={props?.view ?? makeView()}
            density="comfortable"
            onRowClick={props?.onRowClick}
        />,
    )
}

describe('TreeView 通用层级树视图', () => {
    it('未配置 parent_field 时显示配置引导空态', () => {
        renderTree({ view: makeView({ parent_field: undefined }) })

        expect(screen.getByText(/需要配置父节点关联字段/)).toBeInTheDocument()
    })

    it('无数据显示暂无数据空态', () => {
        renderTree({ rows: [] })

        expect(screen.getByText('暂无数据', { selector: '.ant-empty-description' })).toBeInTheDocument()
    })

    it('父节点互相引用无法成树时显示引导空态', () => {
        const cyclic: RowResponse[] = [
            { id: 1, 名称: '甲', 父节点: '2' },
            { id: 2, 名称: '乙', 父节点: '1' },
        ]
        renderTree({ rows: cyclic })

        expect(screen.getByText(/当前数据无法构建层级树/)).toBeInTheDocument()
    })

    it('默认全部展开并显示节点统计、子节点数量与徽章', () => {
        renderTree()

        expect(screen.getByTestId('tree-view')).toBeInTheDocument()
        // 三级节点全部可见（expand_all 默认 true）
        expect(screen.getByText('目录A')).toBeInTheDocument()
        expect(screen.getByText('子目录A1')).toBeInTheDocument()
        expect(screen.getByText('子目录A2')).toBeInTheDocument()
        expect(screen.getByText('文件A1a')).toBeInTheDocument()
        expect(screen.getByText('4 个节点 · 1 个根')).toBeInTheDocument()
        // 子节点数量：目录A 2 个、子目录A1 1 个
        expect(screen.getByText('2 子项')).toBeInTheDocument()
        expect(screen.getByText('1 子项')).toBeInTheDocument()
        // 状态徽章与负责人
        expect(screen.getAllByText('启用').length).toBeGreaterThanOrEqual(2)
        expect(screen.getByText('停用')).toBeInTheDocument()
        expect(screen.getByText('alice')).toBeInTheDocument()
    })

    it('expand_all 关闭时只展开第一层', () => {
        renderTree({ view: makeView({ expand_all: false }) })

        expect(screen.getByText('点击三角展开/折叠')).toBeInTheDocument()
        // 根展开 → 第二层可见；第三层折叠不可见
        expect(screen.getByText('子目录A1')).toBeInTheDocument()
        expect(screen.queryByText('文件A1a')).not.toBeInTheDocument()
    })

    it('点击三角折叠/展开子节点', () => {
        renderTree()

        // 折叠根节点 → 整棵子树隐藏
        fireEvent.click(screen.getAllByTestId('tree-toggle')[0])
        expect(screen.queryByText('子目录A1')).not.toBeInTheDocument()

        // 重新展开根节点
        fireEvent.click(screen.getAllByTestId('tree-toggle')[0])
        expect(screen.getByText('子目录A1')).toBeInTheDocument()

        // 折叠"子目录A1" → 孙节点隐藏
        fireEvent.click(screen.getAllByTestId('tree-toggle')[1])
        expect(screen.queryByText('文件A1a')).not.toBeInTheDocument()
    })

    it('show_numbering 开启时显示层级编号', () => {
        renderTree({ view: makeView({ show_numbering: true }) })

        expect(screen.getByText('1.')).toBeInTheDocument()
        expect(screen.getByText('1.1.')).toBeInTheDocument()
        expect(screen.getByText('1.1.1.')).toBeInTheDocument()
    })

    it('点击行回调对应行', () => {
        const onRowClick = vi.fn()
        renderTree({ onRowClick })

        fireEvent.click(screen.getByText('子目录A2'))

        expect(onRowClick).toHaveBeenCalledTimes(1)
        expect(onRowClick.mock.calls[0][0].id).toBe(3)
    })

    it('link 类型父字段按父行 id 构建层级树', () => {
        const rows: RowResponse[] = [
            { id: 1, 名称: '目录A' },
            { id: 2, 名称: '子目录B1', 父链接: [{ id: 1, value: '目录A' }] },
        ]
        renderTree({ rows, view: makeView({ parent_field: '父链接' }) })

        expect(screen.getByText('2 个节点 · 1 个根')).toBeInTheDocument()
        expect(screen.getByText('子目录B1')).toBeInTheDocument()
        expect(screen.getByText('1 子项')).toBeInTheDocument()
    })

    it('未配置 title_field 时自动推断第一个文本字段作为标题', () => {
        renderTree({ view: makeView({ title_field: undefined }) })

        // 名称（第一个 text 字段）作为节点标题
        expect(screen.getByText('目录A')).toBeInTheDocument()
    })
})
