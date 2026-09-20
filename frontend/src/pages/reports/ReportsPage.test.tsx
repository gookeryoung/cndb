/**
 * ReportsPage 页面组件测试 —— 报告模板列表页.
 *
 * 覆盖：加载态 / 列表渲染 / 空态 / 新建模板弹窗 / 删除确认回调查询 / 未关联表渲染禁用.
 * 注：组件用 useParams 取 wid，必须包在 Routes 内渲染。
 */

import { describe, expect, it } from 'vitest'
import { delay, http, HttpResponse } from 'msw'
import { Routes, Route } from 'react-router-dom'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import ReportsPage from './ReportsPage'
import { renderProviders } from '@/test/render-providers'
import { server } from '@/test/msw'
import type { ReportTemplateSummary } from '@/api'

const TPL: ReportTemplateSummary = {
    id: 1,
    table_id: 100,
    name: '月度销售汇总',
    description: '按月汇总销售数据',
    output_format: 'docx',
    parameters: [{ name: '月份', type: 'string', required: true }],
    extra_table_ids: [],
}

function renderPage() {
    return renderProviders(
        <Routes>
            <Route path="/w/:wid/reports" element={<ReportsPage />} />
        </Routes>,
        { route: '/w/10/reports' },
    )
}

describe('ReportsPage 报表模板页', () => {
    it('模板请求未返回时表格显示加载态', async () => {
        server.use(
            http.get('/api/v1/reports', async () => {
                await delay('infinite')
                return HttpResponse.json([])
            }),
        )
        renderPage()

        await waitFor(() => expect(document.querySelector('.ant-spin-spinning')).toBeInTheDocument())
    })

    it('渲染模板列表（名称 / 输出格式 / 关联表 / 参数）', async () => {
        server.use(http.get('/api/v1/reports', () => HttpResponse.json([TPL])))
        renderPage()

        expect(await screen.findByText('月度销售汇总')).toBeInTheDocument()
        expect(screen.getByText('Word (.docx)')).toBeInTheDocument()
        // 关联表列由 tables 查询映射为表名（默认 handler 的 mockTable）
        expect(screen.getByText('客户表')).toBeInTheDocument()
        // 必填参数渲染为 "参数名*"
        expect(screen.getByText('月份*')).toBeInTheDocument()
    })

    it('空列表显示空态提示与新建入口', async () => {
        server.use(http.get('/api/v1/reports', () => HttpResponse.json([])))
        renderPage()

        expect(await screen.findByText('还没有报告模板')).toBeInTheDocument()
        // 页头 + 空态内各有一个新建模板按钮
        expect(screen.getAllByRole('button', { name: /新\s*建\s*模\s*板/ })).toHaveLength(2)
    })

    it('点击新建模板打开编辑器弹窗并挂载编辑器', async () => {
        server.use(http.get('/api/v1/reports', () => HttpResponse.json([TPL])))
        renderPage()

        fireEvent.click((await screen.findAllByRole('button', { name: /新\s*建\s*模\s*板/ }))[0])

        await waitFor(() => expect(document.querySelector('.ant-modal-title')).toHaveTextContent('新建模板'))
        // CodeMirror 编辑器已挂载
        await waitFor(() => expect(document.querySelector('.cm-editor')).not.toBeNull())
    })

    it('删除模板：更多菜单确认后发起 DELETE 请求', async () => {
        let deleteCalled = false
        server.use(
            http.get('/api/v1/reports', () => HttpResponse.json([TPL])),
            http.delete('/api/v1/reports/1', () => {
                deleteCalled = true
                return HttpResponse.json({})
            }),
        )
        renderPage()

        // 打开行操作下拉菜单（默认 hover 触发）
        fireEvent.mouseEnter(await screen.findByRole('button', { name: 'more' }))
        fireEvent.click(await screen.findByText('删除'))

        // Modal.confirm 确认框（antd5 会同时渲染 aria 用的 modal-title 与 confirm-title 两个标题元素）
        expect(await screen.findAllByText(/删除模板「月度销售汇总」/)).not.toHaveLength(0)
        fireEvent.click(await screen.findByRole('button', { name: /^删\s*除$/ }))

        expect(await screen.findByText('模板已删除')).toBeInTheDocument()
        expect(deleteCalled).toBe(true)
    })

    it('未关联表的模板其渲染下载按钮禁用', async () => {
        server.use(
            http.get('/api/v1/reports', () =>
                HttpResponse.json([{ ...TPL, id: 2, name: '无关联模板', table_id: null }]),
            ),
        )
        renderPage()

        const btn = await screen.findByRole('button', { name: /渲\s*染\s*下\s*载/ })
        expect(btn).toBeDisabled()
    })
})
