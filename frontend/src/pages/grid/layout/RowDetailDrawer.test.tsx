/**
 * RowDetailDrawer 组件测试 —— 行详情抽屉.
 *
 * 覆盖：空行不渲染 / 字段表单回显 / 操作历史（空与有数据）/ 反向引用 / 保存提交
 *      / 新建行模式（initialValues 预填、创建提交、onCreated 回调、新建态不请求行级数据）。
 */

import { describe, expect, it, vi } from 'vitest'
import { http, HttpResponse } from 'msw'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import RowDetailDrawer from './RowDetailDrawer'
import { renderProviders } from '@/test/render-providers'
import { server } from '@/test/msw'
import { makeField } from '@/test/fixtures'
import type { Field, RowResponse, RowValues } from '@/api'

const FIELDS: Field[] = [
    makeField({ id: 1, name: '姓名', field_type: 'text' }),
    makeField({ id: 2, name: '年龄', field_type: 'number' }),
    makeField({ id: 3, name: '状态', field_type: 'select', config: { options: ['高', '中', '低'] } }),
    // link 字段：无 target_table_id 以禁用目标行下拉查询（本用例只验证值归一化）
    makeField({ id: 4, name: '部门', field_type: 'link' }),
]

const ROW: RowResponse = { id: 5, 姓名: '张三', 年龄: 20, 状态: '高', 部门: [{ id: 7, value: '研发部' }, { id: 8, value: '产品部' }] }

/** audit / references 默认空数据，特殊用例用 server.use 覆盖 */
function setup(audit: unknown[] = [], references: unknown[] = []) {
    server.use(
        http.get('/api/v1/workspaces/10/tables/20/audit', () => HttpResponse.json(audit)),
        http.get('/api/v1/workspaces/10/tables/20/records/5/references', () => HttpResponse.json(references)),
    )
}

interface RenderDrawerProps {
    open?: boolean
    row?: RowResponse | null
    initialValues?: RowValues
    onCreated?: () => void
    onClose?: () => void
}

function renderDrawer(props: RenderDrawerProps = {}) {
    return renderProviders(
        <RowDetailDrawer
            open={props.open ?? true}
            row={props.row !== undefined ? props.row : ROW}
            fields={FIELDS}
            wid="10"
            tid="20"
            onClose={props.onClose ?? (() => { })}
            initialValues={props.initialValues}
            onCreated={props.onCreated}
        />,
    )
}

describe('RowDetailDrawer 行详情抽屉', () => {
    it('row 为 null 时进入新建行模式，不渲染编辑态标题', () => {
        setup()
        renderDrawer({ row: null })

        expect(screen.queryByText('行详情 #5')).not.toBeInTheDocument()
    })

    it('open 渲染标题、字段 label 与表单回显', () => {
        setup()
        renderDrawer()

        expect(screen.getByText('行详情 #5')).toBeInTheDocument()
        expect(screen.getByText('字段值')).toBeInTheDocument()
        expect(screen.getByText('姓名')).toBeInTheDocument()
        expect(screen.getByText('年龄')).toBeInTheDocument()
        // 表单回显行数据
        expect(screen.getByDisplayValue('张三')).toBeInTheDocument()
    })

    it('audit 为空时显示"暂无历史记录"', async () => {
        setup()
        renderDrawer()

        expect(await screen.findByText('暂无历史记录')).toBeInTheDocument()
    })

    it('有审计日志时渲染 Timeline 条目', async () => {
        setup([
            { id: 1, action: 'update', actor_name: 'alice', created_at: '2026-01-01 10:00' },
            { id: 2, action: 'delete', actor_name: null, created_at: '2026-01-02 11:00' },
        ])
        renderDrawer()

        expect(await screen.findByText('update')).toBeInTheDocument()
        expect(screen.getByText('delete')).toBeInTheDocument()
        expect(screen.getByText(/alice · 2026-01-01 10:00/)).toBeInTheDocument()
        // actor 为空回退"系统"
        expect(screen.getByText(/系统 · 2026-01-02 11:00/)).toBeInTheDocument()
    })

    it('有反向引用时渲染"被引用"区块', async () => {
        setup([], [{ table_id: 2, row_id: 9, table_name: '订单表', row_summary: '订单 #9' }])
        renderDrawer()

        expect(await screen.findByText('被引用 (1)')).toBeInTheDocument()
        expect(screen.getByText('订单表')).toBeInTheDocument()
        expect(screen.getByText('订单 #9')).toBeInTheDocument()
    })

    it('修改字段值后保存：提交 PATCH 并提示成功', async () => {
        setup()
        const patchSpy = vi.fn(() => HttpResponse.json({ id: 5, 姓名: '李四' }))
        server.use(http.patch('/api/v1/workspaces/10/tables/20/records/5', patchSpy))
        renderDrawer()

        const nameInput = screen.getByDisplayValue('张三')
        fireEvent.change(nameInput, { target: { value: '李四' } })
        // 按钮带 SaveOutlined 图标（aria-label="save"），accessible name 前缀含 "save"
        fireEvent.click(screen.getByRole('button', { name: /保\s*存$/ }))

        await waitFor(() => expect(patchSpy).toHaveBeenCalledTimes(1))
        expect(await screen.findByText('已保存')).toBeInTheDocument()
    })

    it('编辑保存：link 字段的 [{id,value}] 摘要归一化为目标行 id 列表再提交', async () => {
        setup()
        let patchBody: Record<string, unknown> = {}
        server.use(http.patch('/api/v1/workspaces/10/tables/20/records/5', async ({ request }) => {
            patchBody = await request.clone().json() as Record<string, unknown>
            return HttpResponse.json({ id: 5 })
        }))
        renderDrawer()

        // 不触碰 link 字段，仅触发一次其他字段编辑后保存
        const nameInput = screen.getByDisplayValue('张三')
        fireEvent.change(nameInput, { target: { value: '李四' } })
        fireEvent.click(screen.getByRole('button', { name: /保\s*存$/ }))

        await waitFor(() => expect(patchBody.values).toBeDefined())
        const values = (patchBody as { values: Record<string, unknown> }).values
        expect(values.部门).toEqual([7, 8])
    })
})

// ─────────────── 新建行模式（看板新增卡片入口，row=null）───────────────

describe('RowDetailDrawer 新建行模式', () => {
    it('渲染「新建行」标题与「创建」按钮，不渲染操作历史与被引用区块', () => {
        setup()
        renderDrawer({ row: null })

        expect(screen.getByText('新建行')).toBeInTheDocument()
        expect(screen.getByRole('button', { name: /创\s*建$/ })).toBeInTheDocument()
        expect(screen.queryByText(/操作历史/)).not.toBeInTheDocument()
        expect(screen.queryByText(/被引用/)).not.toBeInTheDocument()
    })

    it('initialValues 预填表单（看板分组字段）', () => {
        setup()
        renderDrawer({ row: null, initialValues: { 姓名: '预填同学', 年龄: 7 } })

        expect(screen.getByDisplayValue('预填同学')).toBeInTheDocument()
    })

    it('点击创建：提交 POST values、提示成功并依次回调 onClose/onCreated', async () => {
        setup()
        // msw handler 内异步读取请求体（clone 保底，避免多次读取报 Body unusable）
        const captured: Array<{ values: Record<string, unknown> }> = []
        server.use(http.post('/api/v1/workspaces/10/tables/20/records', async ({ request }) => {
            captured.push(await request.clone().json() as { values: Record<string, unknown> })
            return HttpResponse.json({ id: 9, 姓名: '预填同学' })
        }))
        const onCreated = vi.fn()
        const onClose = vi.fn()
        renderDrawer({ row: null, initialValues: { 姓名: '预填同学' }, onCreated, onClose })

        fireEvent.click(screen.getByRole('button', { name: /创\s*建$/ }))

        await waitFor(() => {
            expect(captured).toHaveLength(1)
            expect(captured[0]!.values.姓名).toBe('预填同学')
        })
        expect(await screen.findByText('已新增 1 行')).toBeInTheDocument()
        await waitFor(() => {
            expect(onClose).toHaveBeenCalledTimes(1)
            expect(onCreated).toHaveBeenCalledTimes(1)
        })
    })

    it('创建失败：提示错误且不触发回调', async () => {
        setup()
        server.use(http.post('/api/v1/workspaces/10/tables/20/records', () =>
            HttpResponse.json({ detail: '字段校验失败' }, { status: 400 })))
        const onCreated = vi.fn()
        const onClose = vi.fn()
        renderDrawer({ row: null, onCreated, onClose })

        fireEvent.click(screen.getByRole('button', { name: /创\s*建$/ }))

        expect(await screen.findByText('字段校验失败')).toBeInTheDocument()
        expect(onCreated).not.toHaveBeenCalled()
        expect(onClose).not.toHaveBeenCalled()
    })
})

// ─────────────── lookup 只读引用字段 ───────────────

describe('RowDetailDrawer lookup 只读字段', () => {
    const LOOKUP_FIELD: Field = makeField({ id: 6, name: '负责人', field_type: 'lookup' })
    const FIELDS_WITH_LOOKUP: Field[] = [...FIELDS, LOOKUP_FIELD]
    const ROW_WITH_LOOKUP: RowResponse = { ...ROW, 负责人: '李四' }

    it('lookup 字段以禁用输入框只读展示解析值', () => {
        setup()
        renderProviders(
            <RowDetailDrawer
                open
                row={ROW_WITH_LOOKUP}
                fields={FIELDS_WITH_LOOKUP}
                wid="10"
                tid="20"
                onClose={() => { }}
            />,
        )

        const input = screen.getByDisplayValue('李四')
        expect(input).toBeDisabled()
    })

    it('保存时从提交体剔除 lookup 字段（无物理列，回传值会导致后端 500）', async () => {
        setup()
        let patchBody: Record<string, unknown> = {}
        server.use(http.patch('/api/v1/workspaces/10/tables/20/records/5', async ({ request }) => {
            patchBody = await request.clone().json() as Record<string, unknown>
            return HttpResponse.json({ id: 5 })
        }))
        renderProviders(
            <RowDetailDrawer
                open
                row={ROW_WITH_LOOKUP}
                fields={FIELDS_WITH_LOOKUP}
                wid="10"
                tid="20"
                onClose={() => { }}
            />,
        )

        fireEvent.change(screen.getByDisplayValue('张三'), { target: { value: '张三改' } })
        fireEvent.click(screen.getByRole('button', { name: /保\s*存$/ }))

        await waitFor(() => expect(patchBody.values).toBeDefined())
        const values = (patchBody as { values: Record<string, unknown> }).values
        expect(values.姓名).toBe('张三改')
        expect(values).not.toHaveProperty('负责人')
    })
})
