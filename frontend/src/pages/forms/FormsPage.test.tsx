/**
 * FormsPage 页面组件测试 —— 表单管理页.
 *
 * 覆盖：加载态 / 列表渲染（权限阈值）/ 空态 / 删除确认链路 / 新建 Drawer 字段编排挂载.
 * 注：组件用 useParams 取 wid，必须包在 Routes 内渲染。
 */

import { describe, expect, it } from 'vitest'
import { delay, http, HttpResponse } from 'msw'
import { Routes, Route } from 'react-router-dom'
import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import FormsPage from './FormsPage'
import { renderProviders } from '@/test/render-providers'
import { server } from '@/test/msw'

function renderPage() {
    return renderProviders(
        <Routes>
            <Route path="/w/:wid/forms" element={<FormsPage />} />
        </Routes>,
        { route: '/w/10/forms' },
    )
}

describe('FormsPage 表单管理页', () => {
    it('列表请求未返回时表格显示加载态', async () => {
        server.use(
            http.get('/api/v1/workspaces/10/forms', async () => {
                await delay('infinite')
                return HttpResponse.json([])
            }),
        )
        renderPage()

        await waitFor(() => expect(document.querySelector('.ant-spin-spinning')).toBeInTheDocument())
    })

    it('渲染表单列表（名称 / 所属表 / 权限阈值标签）', async () => {
        renderPage()

        expect(await screen.findByText('客户信息录入')).toBeInTheDocument()
        expect(screen.getByText('客户表')).toBeInTheDocument()
        expect(screen.getByText('使用:viewer')).toBeInTheDocument()
        expect(screen.getByText('编辑:editor')).toBeInTheDocument()
        expect(screen.getByText('删除:表级')).toBeInTheDocument()
    })

    it('空列表显示空态提示与新建入口', async () => {
        server.use(http.get('/api/v1/workspaces/10/forms', () => HttpResponse.json([])))
        renderPage()

        expect(await screen.findByText('还没有表单，先新建一个吧')).toBeInTheDocument()
        // 页头 + 空态内各有一个新建表单按钮
        expect(screen.getAllByRole('button', { name: /新\s*建\s*表\s*单/ })).toHaveLength(2)
    })

    it('删除需二次确认，确认后发出 DELETE 请求并提示成功', async () => {
        const deleted: string[] = []
        server.use(
            http.delete('/api/v1/workspaces/10/forms/:fid', ({ params }) => {
                deleted.push(String(params.fid))
                return HttpResponse.json({ ok: true })
            }),
        )
        renderPage()

        fireEvent.click(await screen.findByRole('button', { name: 'delete' }))
        // 二次确认弹窗
        const dialog = await screen.findByRole('dialog')
        fireEvent.click(within(dialog).getByRole('button', { name: /删\s*除/ }))

        expect(await screen.findByText('表单已删除')).toBeInTheDocument()
        expect(deleted).toEqual(['1'])
    })

    it('新建 Drawer 打开后选择数据表，字段编排挂载字段行', async () => {
        renderPage()

        fireEvent.click((await screen.findAllByRole('button', { name: /新\s*建\s*表\s*单/ }))[0])
        const drawer = await screen.findByRole('dialog')

        // 选择所属数据表（默认 handlers 返回 mockTable：客户表 id=100）
        fireEvent.mouseDown(within(drawer).getAllByRole('combobox')[0]!)
        fireEvent.click(await screen.findByText('客户表', { selector: '.ant-select-item-option-content' }))

        // 字段编排区出现字段行（fields handler 返回 mockField：姓名 / text）
        expect(await screen.findByTestId('field-row-姓名')).toBeInTheDocument()
        expect(within(drawer).getByText('text')).toBeInTheDocument()
    })
})
