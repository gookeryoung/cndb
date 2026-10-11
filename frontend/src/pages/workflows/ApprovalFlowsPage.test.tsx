/**
 * ApprovalFlowsPage 页面组件测试 —— 审批流配置 + 待我审批 / 我提交的.
 *
 * 覆盖：审批流列表与链摘要渲染 / 新建 Drawer 创建链（线性 start→approval→end 载荷）/
 * 编辑回填 / 待我审批列表与通过动作 / 驳回二次确认 / 我提交的落库展示.
 * 注：组件用 useParams 取 wid，必须包在 Routes 内渲染。
 */

import { describe, expect, it } from 'vitest'
import { http, HttpResponse } from 'msw'
import { Routes, Route } from 'react-router-dom'
import { fireEvent, screen, within } from '@testing-library/react'
import ApprovalFlowsPage from './ApprovalFlowsPage'
import { renderProviders } from '@/test/render-providers'
import { server, mockWorkflowDetail, mockPendingApprovals } from '@/test/msw'

function renderPage() {
    return renderProviders(
        <Routes>
            <Route path="/w/:wid/approvals" element={<ApprovalFlowsPage />} />
        </Routes>,
        { route: '/w/10/approvals' },
    )
}

describe('ApprovalFlowsPage 审批流页', () => {
    it('渲染审批流列表与审批链摘要（按角色标签）', async () => {
        renderPage()

        expect(await screen.findByText('请假审批')).toBeInTheDocument()
        expect(screen.getByText('两级审批')).toBeInTheDocument()
        // 链摘要：懒加载详情后展示步骤标签
        expect(await screen.findByText('主管审批 · editor')).toBeInTheDocument()
        expect(screen.getByText('经理审批 · admin')).toBeInTheDocument()
    })

    it('空列表显示空态提示', async () => {
        server.use(http.get('/api/v1/workspaces/10/workflows', () => HttpResponse.json([])))
        renderPage()

        expect(await screen.findByText('还没有审批流，点击右上角新建')).toBeInTheDocument()
    })

    it('新建审批流：默认一个审批节点，创建时生成线性链载荷', async () => {
        const bodies: unknown[] = []
        server.use(
            http.post('/api/v1/workspaces/10/workflows', async ({ request }) => {
                bodies.push(await request.json())
                return HttpResponse.json(mockWorkflowDetail, { status: 201 })
            }),
        )
        renderPage()

        fireEvent.click(await screen.findByRole('button', { name: /新\s*建\s*审\s*批\s*流/ }))
        const drawer = await screen.findByRole('dialog')

        // 默认步骤：主管审批（editor）
        expect(within(drawer).getByLabelText('第 1 级审批名称')).toHaveValue('主管审批')

        // 添加第二个节点并调整角色
        fireEvent.click(within(drawer).getByRole('button', { name: /添\s*加\s*审\s*批\s*节\s*点/ }))
        expect(within(drawer).getByLabelText('第 2 级审批名称')).toHaveValue('审批 2')

        fireEvent.change(within(drawer).getByLabelText('审批流名称'), { target: { value: '采购审批' } })
        fireEvent.click(within(drawer).getByRole('button', { name: /创\s*建/ }))

        expect(await screen.findByText('审批流已创建')).toBeInTheDocument()
        expect(bodies).toHaveLength(1)
        const payload = bodies[0] as { name: string; nodes: Array<{ key: string; node_type: string }>; edges: Array<{ source: string; target: string }> }
        expect(payload.name).toBe('采购审批')
        // 线性链：start → a1 → a2 → end
        expect(payload.nodes.map(n => n.node_type)).toEqual(['start', 'approval', 'approval', 'end'])
        expect(payload.edges).toEqual([
            { source: 's', target: 'a1' },
            { source: 'a1', target: 'a2' },
            { source: 'a2', target: 'e' },
        ])
    })

    it('编辑审批流：Drawer 回填名称与步骤', async () => {
        renderPage()

        fireEvent.click(await screen.findByRole('button', { name: /编\s*辑/ }))
        const drawer = await screen.findByRole('dialog')

        expect(await within(drawer).findByLabelText('审批流名称')).toHaveValue('请假审批')
        expect(within(drawer).getByLabelText('第 1 级审批名称')).toHaveValue('主管审批')
        expect(within(drawer).getByLabelText('第 2 级审批名称')).toHaveValue('经理审批')
    })

    it('待我审批：渲染提交数据与当前节点，通过后发出 approve 请求', async () => {
        const bodies: unknown[] = []
        server.use(
            http.post('/api/v1/workspaces/10/approvals/71/approve', async ({ request }) => {
                bodies.push(await request.json())
                return HttpResponse.json({ ...mockPendingApprovals[0], status: 'approved' })
            }),
        )
        renderPage()

        // 默认 Tab 为审批流配置，切换到待我审批
        fireEvent.click(screen.getByRole('tab', { name: '待我审批' }))
        expect(await screen.findByText('姓名: 王五；年龄: 25')).toBeInTheDocument()
        expect(screen.getByText('bob')).toBeInTheDocument()
        expect(screen.getByText('主管审批')).toBeInTheDocument()

        fireEvent.click(screen.getByRole('button', { name: '批准 客户信息录入' }))
        expect(await screen.findByText('已通过，数据已落库')).toBeInTheDocument()
        expect(bodies).toHaveLength(1)
    })

    it('驳回需二次确认，确认后发出 reject 请求', async () => {
        const bodies: unknown[] = []
        server.use(
            http.post('/api/v1/workspaces/10/approvals/71/reject', async ({ request }) => {
                bodies.push(await request.json())
                return HttpResponse.json({ ...mockPendingApprovals[0], status: 'rejected' })
            }),
        )
        renderPage()

        fireEvent.click(screen.getByRole('tab', { name: '待我审批' }))
        fireEvent.click(await screen.findByRole('button', { name: '驳回 客户信息录入' }))

        const confirmModal = await screen.findByRole('dialog')
        expect((await within(confirmModal).findAllByText('驳回这条提交？')).length).toBeGreaterThan(0)
        fireEvent.click(within(confirmModal).getByRole('button', { name: /驳\s*回/ }))

        expect(await screen.findByText('已驳回')).toBeInTheDocument()
        expect(bodies).toHaveLength(1)
    })

    it('我提交的：展示已通过状态与落库行号', async () => {
        renderPage()

        fireEvent.click(screen.getByRole('tab', { name: '我提交的' }))
        expect(await screen.findByText('已通过')).toBeInTheDocument()
        expect(screen.getByText('#9')).toBeInTheDocument()
        // 我提交的 Tab 不显示操作按钮
        expect(screen.queryByRole('button', { name: /批准/ })).not.toBeInTheDocument()
    })
})
