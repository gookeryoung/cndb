/**
 * FormRunnerPage 页面组件测试 —— 表单运行器（填写 / 行列表 / 编辑 / 删除）.
 *
 * 覆盖：meta 加载态 / 行列表渲染 / 无权隐藏操作 / 新增提交链路 / 行编辑回填与保存 /
 * 删除确认链路 / 失效字段警告 / meta 加载失败提示.
 * 注：组件用 useParams 取 wid/formId，必须包在 Routes 内渲染。
 */

import { describe, expect, it } from 'vitest'
import { delay, http, HttpResponse } from 'msw'
import { Routes, Route } from 'react-router-dom'
import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import FormRunnerPage from './FormRunnerPage'
import { renderProviders } from '@/test/render-providers'
import { server, mockFormMeta } from '@/test/msw'

function renderPage() {
    return renderProviders(
        <Routes>
            <Route path="/w/:wid/forms/:formId" element={<FormRunnerPage />} />
        </Routes>,
        { route: '/w/10/forms/1' },
    )
}

describe('FormRunnerPage 表单运行器', () => {
    it('meta 请求未返回时显示加载态', async () => {
        server.use(
            http.get('/api/v1/workspaces/10/forms/1/meta', async () => {
                await delay('infinite')
                return HttpResponse.json(mockFormMeta)
            }),
        )
        renderPage()

        await waitFor(() => expect(document.querySelector('.ant-spin-spinning')).toBeInTheDocument())
    })

    it('渲染表单头部与行列表（字段列 + 数据值）', async () => {
        renderPage()

        expect(await screen.findByRole('heading', { name: '客户信息录入' })).toBeInTheDocument()
        expect(screen.getByText('客户表')).toBeInTheDocument()
        expect(screen.getByText('张三')).toBeInTheDocument()
        expect(screen.getByText('李四')).toBeInTheDocument()
        expect(screen.getByText('20')).toBeInTheDocument()
        // 分页组件存在（rows.total 驱动）
        expect(document.querySelector('.ant-pagination')).toBeInTheDocument()
    })

    it('can_submit=false 时不显示新增数据按钮，can_edit=false 时隐藏编辑入口', async () => {
        server.use(
            http.get('/api/v1/workspaces/10/forms/1/meta', () => HttpResponse.json({
                ...mockFormMeta,
                can_submit: false,
                can_edit: false,
                can_delete: false,
            })),
        )
        renderPage()

        expect(await screen.findByText('张三')).toBeInTheDocument()
        expect(screen.queryByRole('button', { name: /新\s*增\s*数\s*据/ })).not.toBeInTheDocument()
        expect(screen.queryByRole('button', { name: /编\s*辑/ })).not.toBeInTheDocument()
        expect(screen.queryByRole('button', { name: /删\s*除\s*第/ })).not.toBeInTheDocument()
    })

    it('新增数据：Drawer 填写后提交，发出 POST rows 请求', async () => {
        const bodies: unknown[] = []
        server.use(
            http.post('/api/v1/workspaces/10/forms/1/rows', async ({ request }) => {
                bodies.push(await request.json())
                return HttpResponse.json({ id: 9 }, { status: 201 })
            }),
        )
        renderPage()

        fireEvent.click(await screen.findByRole('button', { name: /新\s*增\s*数\s*据/ }))
        const drawer = await screen.findByRole('dialog')

        // 姓名（text 输入框）
        fireEvent.change(within(drawer).getByLabelText('姓名'), { target: { value: '王五' } })
        // 年龄（number 输入框）
        fireEvent.change(within(drawer).getByLabelText('年龄'), { target: { value: '25' } })
        fireEvent.click(within(drawer).getByRole('button', { name: /提\s*交/ }))

        expect(await screen.findByText('提交成功')).toBeInTheDocument()
        expect(bodies).toHaveLength(1)
        expect(bodies[0]).toMatchObject({ values: { 姓名: '王五', 年龄: 25 } })
    })

    it('行编辑：Drawer 回填行值，保存后发出 PATCH 请求', async () => {
        const bodies: unknown[] = []
        server.use(
            http.patch('/api/v1/workspaces/10/forms/1/rows/1', async ({ request }) => {
                bodies.push(await request.json())
                return HttpResponse.json({ id: 1 })
            }),
        )
        renderPage()

        fireEvent.click((await screen.findAllByRole('button', { name: /编\s*辑/ }))[0])
        const drawer = await screen.findByRole('dialog')

        // 回填断言
        expect(within(drawer).getByLabelText('姓名')).toHaveValue('张三')
        fireEvent.change(within(drawer).getByLabelText('姓名'), { target: { value: '张三三' } })
        fireEvent.click(within(drawer).getByRole('button', { name: /保\s*存/ }))

        expect(await screen.findByText('已保存')).toBeInTheDocument()
        expect(bodies).toHaveLength(1)
        expect(bodies[0]).toMatchObject({ values: { 姓名: '张三三' } })
    })

    it('删除行：二次确认后发出 DELETE 请求并提示', async () => {
        const deleted: string[] = []
        server.use(
            http.delete('/api/v1/workspaces/10/forms/1/rows/:rid', ({ params }) => {
                deleted.push(String(params.rid))
                return HttpResponse.json({ ok: true })
            }),
        )
        renderPage()

        fireEvent.click(await screen.findByRole('button', { name: '删除第 1 行' }))
        const dialog = await screen.findByRole('dialog')
        fireEvent.click(within(dialog).getByRole('button', { name: /删\s*除/ }))

        expect(await screen.findByText('已删除')).toBeInTheDocument()
        expect(deleted).toEqual(['1'])
    })

    it('invalid_fields 非空时渲染警告 Alert', async () => {
        server.use(
            http.get('/api/v1/workspaces/10/forms/1/meta', () => HttpResponse.json({
                ...mockFormMeta,
                invalid_fields: ['已删除字段'],
            })),
        )
        renderPage()

        expect(await screen.findByText(/以下字段已失效/)).toBeInTheDocument()
        expect(screen.getByText(/已删除字段/)).toBeInTheDocument()
    })

    it('meta 请求失败时显示错误提示', async () => {
        server.use(
            http.get('/api/v1/workspaces/10/forms/1/meta', () =>
                HttpResponse.json({ detail: '无权访问' }, { status: 403 })),
        )
        renderPage()

        expect(await screen.findByText('表单不存在或无权访问')).toBeInTheDocument()
    })

    it('绑定审批流：头部显示提交需审批标记，提交返回审批响应时不落库', async () => {
        const bodies: unknown[] = []
        server.use(
            http.get('/api/v1/workspaces/10/forms/1/meta', () => HttpResponse.json({
                ...mockFormMeta,
                approval_workflow_id: 5,
            })),
            http.post('/api/v1/workspaces/10/forms/1/rows', async ({ request }) => {
                bodies.push(await request.json())
                return HttpResponse.json({
                    approval: {
                        id: 71, workflow_id: 5, workflow_name: '请假审批',
                        status: 'pending', current_approver_role: 'editor',
                    },
                })
            }),
        )
        renderPage()

        expect(await screen.findByText('提交需审批')).toBeInTheDocument()

        fireEvent.click(await screen.findByRole('button', { name: /新\s*增\s*数\s*据/ }))
        const drawer = await screen.findByRole('dialog')
        fireEvent.change(within(drawer).getByLabelText('姓名'), { target: { value: '王五' } })
        fireEvent.click(within(drawer).getByRole('button', { name: /提\s*交/ }))

        expect(await screen.findByText('已提交审批（请假审批），等待审批人处理')).toBeInTheDocument()
        expect(bodies).toHaveLength(1)
        // 不显示直接落库的成功提示
        expect(screen.queryByText('提交成功')).not.toBeInTheDocument()
    })

    it('控件覆盖：text 字段配置 widget=select 后渲染下拉并提交选项值', async () => {
        const bodies: unknown[] = []
        server.use(
            http.get('/api/v1/workspaces/10/forms/1/meta', () => HttpResponse.json({
                ...mockFormMeta,
                fields: [
                    {
                        field_name: '姓名', editable: true, visible: true, required: true,
                        field_type: 'text', widget: 'select',
                        widget_config: { options: [{ value: '甲', label: '甲等' }, { value: '乙', label: '乙等' }] },
                    },
                    { field_name: '年龄', editable: true, visible: true, field_type: 'number' },
                ],
            })),
            http.post('/api/v1/workspaces/10/forms/1/rows', async ({ request }) => {
                bodies.push(await request.json())
                return HttpResponse.json({ id: 9 }, { status: 201 })
            }),
        )
        renderPage()

        fireEvent.click(await screen.findByRole('button', { name: /新\s*增\s*数\s*据/ }))
        const drawer = await screen.findByRole('dialog')

        // 姓名 字段渲染为 Select 覆盖控件而非文本输入
        const select = within(drawer).getByLabelText('姓名')
        expect(select.getAttribute('class')).toContain('ant-select')
        fireEvent.mouseDown(select)
        fireEvent.click(await screen.findByText('甲等'))

        fireEvent.change(within(drawer).getByLabelText('年龄'), { target: { value: '30' } })
        fireEvent.click(within(drawer).getByRole('button', { name: /提\s*交/ }))

        expect(await screen.findByText('提交成功')).toBeInTheDocument()
        expect(bodies[0]).toMatchObject({ values: { 姓名: '甲', 年龄: 30 } })
    })

    it('控件覆盖：number 字段配置 widget=rate 后渲染评分控件', async () => {
        server.use(
            http.get('/api/v1/workspaces/10/forms/1/meta', () => HttpResponse.json({
                ...mockFormMeta,
                fields: [
                    { field_name: '评分', editable: true, visible: true, field_type: 'number', widget: 'rate' },
                ],
            })),
        )
        renderPage()

        fireEvent.click(await screen.findByRole('button', { name: /新\s*增\s*数\s*据/ }))
        const drawer = await screen.findByRole('dialog')

        // Rate 渲染为评分控件而非数字输入
        expect(within(drawer).getByText('评分')).toBeInTheDocument()
        expect(drawer.querySelector('.ant-rate')).toBeInTheDocument()
        expect(within(drawer).queryByRole('spinbutton')).not.toBeInTheDocument()
    })
})
