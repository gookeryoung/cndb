/**
 * ApprovalFlowsSettings 组件测试 —— 工作区设置内的审批流定义配置.
 *
 * 覆盖：审批流列表与链摘要渲染 / 空态 / 新建 Drawer 创建链（线性 start→approval→end 载荷）/
 * 编辑回填。wid 为 prop 传入，无需路由包装。
 */

import { describe, expect, it } from 'vitest'
import { http, HttpResponse } from 'msw'
import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import ApprovalFlowsSettings from './ApprovalFlowsSettings'
import { renderProviders } from '@/test/render-providers'
import { server, mockWorkflowDetail } from '@/test/msw'

function renderSettings() {
    return renderProviders(<ApprovalFlowsSettings wid="10" />)
}

describe('ApprovalFlowsSettings 工作区设置-审批流', () => {
    it('渲染审批流列表与审批链摘要（按角色标签）', async () => {
        renderSettings()

        expect(await screen.findByText('请假审批')).toBeInTheDocument()
        expect(screen.getByText('两级审批')).toBeInTheDocument()
        // 链摘要：懒加载详情后展示步骤标签
        expect(await screen.findByText('主管审批 · editor')).toBeInTheDocument()
        expect(screen.getByText('经理审批 · admin')).toBeInTheDocument()
    })

    it('空列表显示空态提示', async () => {
        server.use(http.get('/api/v1/workspaces/10/workflows', () => HttpResponse.json([])))
        renderSettings()

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
        renderSettings()

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
        renderSettings()

        fireEvent.click(await screen.findByRole('button', { name: /编\s*辑/ }))
        const drawer = await screen.findByRole('dialog')

        expect(await within(drawer).findByLabelText('审批流名称')).toHaveValue('请假审批')
        expect(within(drawer).getByLabelText('第 1 级审批名称')).toHaveValue('主管审批')
        expect(within(drawer).getByLabelText('第 2 级审批名称')).toHaveValue('经理审批')
    })

    it('引导文案指向工作区设置与审批中心', async () => {
        renderSettings()

        expect(await screen.findByText(/提交与审批记录见顶部「审批中心」/)).toBeInTheDocument()
        await waitFor(() => {
            expect(screen.getByText(/并在表单中绑定/)).toBeInTheDocument()
        })
    })
})
