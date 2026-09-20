/**
 * RowDetailDrawer 组件测试 —— 行详情抽屉.
 *
 * 覆盖：空行不渲染 / 字段表单回显 / 操作历史（空与有数据）/ 反向引用 / 保存提交。
 */

import { describe, expect, it, vi } from 'vitest'
import { http, HttpResponse } from 'msw'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import RowDetailDrawer from './RowDetailDrawer'
import { renderProviders } from '@/test/render-providers'
import { server } from '@/test/msw'
import { makeField } from '@/test/fixtures'
import type { Field, RowResponse } from '@/api'

const FIELDS: Field[] = [
    makeField({ id: 1, name: '姓名', field_type: 'text' }),
    makeField({ id: 2, name: '年龄', field_type: 'number' }),
    makeField({ id: 3, name: '状态', field_type: 'select', config: { options: ['高', '中', '低'] } }),
]

const ROW: RowResponse = { id: 5, 姓名: '张三', 年龄: 20, 状态: '高' }

/** audit / references 默认空数据，特殊用例用 server.use 覆盖 */
function setup(audit: unknown[] = [], references: unknown[] = []) {
    server.use(
        http.get('/api/v1/workspaces/10/tables/20/audit', () => HttpResponse.json(audit)),
        http.get('/api/v1/workspaces/10/tables/20/records/5/references', () => HttpResponse.json(references)),
    )
}

function renderDrawer(props?: { open?: boolean; row?: RowResponse | null }) {
    return renderProviders(
        <RowDetailDrawer
            open={props?.open ?? true}
            row={props?.row !== undefined ? props.row : ROW}
            fields={FIELDS}
            wid="10"
            tid="20"
            onClose={() => { }}
        />,
    )
}

describe('RowDetailDrawer 行详情抽屉', () => {
    it('row 为 null 时不渲染任何内容', () => {
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
})
