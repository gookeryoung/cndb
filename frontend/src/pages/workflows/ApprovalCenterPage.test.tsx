/**
 * ApprovalCenterPage 页面组件测试 —— 待我审批 / 我提交的实例处理.
 *
 * 覆盖：待我审批列表与通过动作 / 驳回二次确认 / 我提交的落库展示 /
 * 页签徽标（待我审批金色 / 我提交的按状态配色）。
 * 注：组件用 useParams 取 wid，必须包在 Routes 内渲染。
 */

import { describe, expect, it } from 'vitest'
import { http, HttpResponse } from 'msw'
import { Routes, Route } from 'react-router-dom'
import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import ApprovalCenterPage from './ApprovalCenterPage'
import { renderProviders } from '@/test/render-providers'
import { server, mockPendingApprovals } from '@/test/msw'

function renderPage() {
    return renderProviders(
        <Routes>
            <Route path="/w/:wid/approvals" element={<ApprovalCenterPage />} />
        </Routes>,
        { route: '/w/10/approvals' },
    )
}

describe('ApprovalCenterPage 审批中心页', () => {
    it('默认落在待我审批：渲染提交数据与当前节点，通过后发出 approve 请求', async () => {
        const bodies: unknown[] = []
        server.use(
            http.post('/api/v1/workspaces/10/approvals/71/approve', async ({ request }) => {
                bodies.push(await request.json())
                return HttpResponse.json({ ...mockPendingApprovals[0], status: 'approved' })
            }),
        )
        renderPage()

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

        fireEvent.click(await screen.findByRole('button', { name: '驳回 客户信息录入' }))

        const confirmModal = await screen.findByRole('dialog')
        expect((await within(confirmModal).findAllByText('驳回这条提交？')).length).toBeGreaterThan(0)
        fireEvent.click(within(confirmModal).getByRole('button', { name: /驳\s*回/ }))

        expect(await screen.findByText('已驳回')).toBeInTheDocument()
        expect(bodies).toHaveLength(1)
    })

    it('我提交的：展示已通过状态与落库行号', async () => {
        renderPage()

        fireEvent.click(screen.getByRole('tab', { name: /我提交的/ }))
        expect(await screen.findByText('已通过')).toBeInTheDocument()
        expect(screen.getByText('#9')).toBeInTheDocument()
        // 我提交的 Tab 不显示操作按钮
        expect(screen.queryByRole('button', { name: /批准/ })).not.toBeInTheDocument()
    })

    it('页签徽标：待我审批（金）/ 我提交的按状态配色（金/绿/红）', async () => {
        renderPage()

        // 待我审批 tab：待审数量以金色徽标展示（mock 1 条待审）
        const inboxTab = await screen.findByRole('tab', { name: /待我审批/ })
        await waitFor(() => {
            expect(inboxTab.querySelector('.ant-tag')).toHaveClass('ant-tag-gold')
        })

        // 我提交的 tab：按状态类别配色计数（mock 1 条已通过，其余为 0 也展示）
        const mineTab = screen.getByRole('tab', { name: /我提交的/ })
        await waitFor(() => {
            expect(mineTab).toHaveTextContent('待审批 0')
            expect(mineTab).toHaveTextContent('已通过 1')
            expect(mineTab).toHaveTextContent('已驳回 0')
        })
        const mineTags = mineTab.querySelectorAll('.ant-tag')
        expect(mineTags).toHaveLength(3)
        expect(mineTags[0]).toHaveClass('ant-tag-gold')
        expect(mineTags[1]).toHaveClass('ant-tag-green')
        expect(mineTags[2]).toHaveClass('ant-tag-red')
    })
})
