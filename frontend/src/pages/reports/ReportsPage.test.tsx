/**
 * ReportsPage 页面组件测试 —— 报告模板列表页.
 *
 * 覆盖：加载态 / 列表渲染 / 空态 / 新建模板弹窗 / 删除确认回调查询 / 未关联表渲染禁用
 * + 渲染下载（无参数直渲 / 参数弹窗回填与提交 / 额外表 / 失败提示）/ 编辑模板回填与保存.
 * 注：组件用 useParams 取 wid，必须包在 Routes 内渲染。
 */

import { afterEach, describe, expect, it, vi } from 'vitest'
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
    theme: 'minimal',
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

// ─────────────── 渲染下载 / 编辑保存流程 ───────────────

const originalCreateObjectURL = URL.createObjectURL
const originalRevokeObjectURL = URL.revokeObjectURL

/** stub 下载链路：createObjectURL / revokeObjectURL / a.click（jsdom 不支持，且避免导航报错）
 *  注意：不能整体替换 URL（会破坏 new URL()），只赋值缺失的静态方法 */
function stubDownload() {
    URL.createObjectURL = vi.fn(() => 'blob:mock-url')
    URL.revokeObjectURL = vi.fn()
    return vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => { })
}

afterEach(() => {
    URL.createObjectURL = originalCreateObjectURL
    URL.revokeObjectURL = originalRevokeObjectURL
    vi.restoreAllMocks()
})

/** 渲染接口拦截：记录请求体并返回二进制 Blob */
function useRenderHandler(id: number, bodies: Record<string, unknown>[]) {
    server.use(
        http.post(`/api/v1/reports/${id}/render`, async ({ request }) => {
            bodies.push(await request.json() as Record<string, unknown>)
            return new HttpResponse(new Blob(['doc-bytes']), {
                headers: { 'Content-Type': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' },
            })
        }),
    )
}

const TPL_WITH_PARAMS: ReportTemplateSummary = {
    ...TPL,
    id: 3,
    name: '含参数模板',
    parameters: [
        { name: '月份', type: 'string', default: '2026-09', required: true },
        { name: '含税', type: 'boolean', required: false },
    ],
}

describe('ReportsPage 渲染下载', () => {
    it('无参数模板点击渲染下载直接发起渲染并触发下载', async () => {
        const anchorClick = stubDownload()
        const bodies: Record<string, unknown>[] = []
        server.use(http.get('/api/v1/reports', () => HttpResponse.json([{ ...TPL, id: 5, parameters: [] }])))
        useRenderHandler(5, bodies)
        renderPage()

        fireEvent.click(await screen.findByRole('button', { name: /渲\s*染\s*下\s*载/ }))
        await waitFor(() => expect(bodies).toHaveLength(1))
        expect(bodies[0]).toMatchObject({ table_id: 100, params: {} })
        expect(URL.createObjectURL).toHaveBeenCalledOnce()
        expect(anchorClick).toHaveBeenCalledOnce()
        expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:mock-url')
    })

    it('带参数模板打开渲染参数弹窗，默认值回填并随渲染提交', async () => {
        stubDownload()
        const bodies: Record<string, unknown>[] = []
        server.use(http.get('/api/v1/reports', () => HttpResponse.json([TPL_WITH_PARAMS])))
        useRenderHandler(3, bodies)
        renderPage()

        fireEvent.click(await screen.findByRole('button', { name: /渲\s*染\s*下\s*载/ }))
        expect(await screen.findByText('渲染模板：含参数模板')).toBeInTheDocument()
        // 默认值回填后用户改为 2026-10
        const monthInput = screen.getByDisplayValue('2026-09')
        fireEvent.change(monthInput, { target: { value: '2026-10' } })
        fireEvent.click(screen.getByRole('button', { name: '生成报告' }))

        await waitFor(() => expect(bodies).toHaveLength(1))
        expect(bodies[0]).toMatchObject({ table_id: 100, params: { 月份: '2026-10' } })
    })

    it('渲染参数弹窗选择额外引用表后随请求提交 extra_table_ids', async () => {
        stubDownload()
        const bodies: Record<string, unknown>[] = []
        server.use(
            http.get('/api/v1/reports', () => HttpResponse.json([TPL_WITH_PARAMS])),
            http.get('/api/v1/workspaces/10/tables', () =>
                HttpResponse.json([{ id: 101, name: '订单表', record_count: 0, field_count: 0, view_count: 0 }]),
            ),
        )
        useRenderHandler(3, bodies)
        renderPage()

        fireEvent.click(await screen.findByRole('button', { name: /渲\s*染\s*下\s*载/ }))
        await screen.findByText('渲染模板：含参数模板')
        // 打开额外引用表下拉（弹窗内第一个 combobox 即额外引用表选择器）并选择「订单表」
        const combos = screen.getAllByRole('combobox')
        fireEvent.mouseDown(combos[0])
        fireEvent.click(await screen.findByText('订单表'))
        fireEvent.click(screen.getByRole('button', { name: '生成报告' }))

        await waitFor(() => expect(bodies).toHaveLength(1))
        expect(bodies[0]).toMatchObject({ table_id: 100, extra_table_ids: [101] })
    })

    it('渲染失败时弹出错误提示', async () => {
        stubDownload()
        server.use(
            http.get('/api/v1/reports', () => HttpResponse.json([{ ...TPL, id: 6, name: '失败模板', parameters: [] }])),
            http.post('/api/v1/reports/6/render', () => HttpResponse.json({ detail: 'boom' }, { status: 500 })),
        )
        renderPage()

        fireEvent.click(await screen.findByRole('button', { name: /渲\s*染\s*下\s*载/ }))
        // client.ts 拦截器会把 blob 错误响应中的 detail 归一化进 err.message，toast 显示后端文案
        expect(await screen.findByText('boom')).toBeInTheDocument()
    })
})

describe('ReportsPage 编辑与新建保存', () => {
    it('编辑模板：详情回填表单，保存发起 PUT 更新', async () => {
        const putBodies: Record<string, unknown>[] = []
        server.use(
            http.get('/api/v1/reports', () => HttpResponse.json([TPL])),
            http.get('/api/v1/reports/1', () => HttpResponse.json({ ...TPL, template_content: 'Hello {{ table_name }}' })),
            http.put('/api/v1/reports/1', async ({ request }) => {
                putBodies.push(await request.json() as Record<string, unknown>)
                return HttpResponse.json({})
            }),
        )
        renderPage()

        fireEvent.mouseEnter(await screen.findByRole('button', { name: 'more' }))
        fireEvent.click(await screen.findByText('编辑'))
        expect(await screen.findByText(/编辑模板「月度销售汇总」/)).toBeInTheDocument()
        fireEvent.click(screen.getByRole('button', { name: /^保\s*存$/ }))

        await waitFor(() => expect(putBodies).toHaveLength(1))
        expect(putBodies[0]).toMatchObject({ name: '月度销售汇总', template_content: 'Hello {{ table_name }}' })
    })

    it('新建模板：填写名称保存后发起 POST 创建并关闭弹窗', async () => {
        const postBodies: Record<string, unknown>[] = []
        server.use(
            http.get('/api/v1/reports', () => HttpResponse.json([])),
            http.post('/api/v1/reports', async ({ request }) => {
                postBodies.push(await request.json() as Record<string, unknown>)
                return HttpResponse.json({ id: 9 })
            }),
        )
        renderPage()

        fireEvent.click((await screen.findAllByRole('button', { name: /新\s*建\s*模\s*板/ }))[0])
        await waitFor(() => expect(document.querySelector('.ant-modal-title')).toHaveTextContent('新建模板'))
        fireEvent.change(screen.getByPlaceholderText('例如：月度销售汇总'), { target: { value: '销售月报' } })
        fireEvent.click(screen.getByRole('button', { name: /^创\s*建$/ }))

        await waitFor(() => expect(postBodies).toHaveLength(1))
        expect(postBodies[0]).toMatchObject({ name: '销售月报', output_format: 'docx' })
        expect(postBodies[0].template_content).toContain('{{ table_name }}')
        expect(await screen.findByText('模板已创建')).toBeInTheDocument()
    })

    it('新建模板：跨工作区引入额外表后随保存提交 extra_table_ids', async () => {
        const postBodies: Record<string, unknown>[] = []
        server.use(
            http.get('/api/v1/reports', () => HttpResponse.json([])),
            http.get('/api/v1/workspaces', () =>
                HttpResponse.json([
                    { id: 10, name: '销售工作区' },
                    { id: 20, name: '科研工作区' },
                ]),
            ),
            http.get('/api/v1/workspaces/10/tables', () =>
                HttpResponse.json([{ id: 100, name: '客户表', record_count: 0, field_count: 0, view_count: 0 }]),
            ),
            http.get('/api/v1/workspaces/20/tables', () =>
                HttpResponse.json([{ id: 200, name: '科研经费表', record_count: 0, field_count: 0, view_count: 0 }]),
            ),
            http.post('/api/v1/reports', async ({ request }) => {
                postBodies.push(await request.json() as Record<string, unknown>)
                return HttpResponse.json({ id: 9 })
            }),
        )
        renderPage()

        fireEvent.click((await screen.findAllByRole('button', { name: /新\s*建\s*模\s*板/ }))[0])
        await waitFor(() => expect(document.querySelector('.ant-modal-title')).toHaveTextContent('新建模板'))

        // 等跨工作区级联行渲染（workspaces query 就绪后出现）
        await waitFor(() => expect(document.querySelector('.report-crossws-row')).not.toBeNull())
        const rowCombo = () => screen.getAllByRole('combobox').find(c => c.closest('.report-crossws-row'))!
        // 先点源工作区按钮（不是下拉），设 importWsId → 触发源表 query
        fireEvent.click(screen.getByText('科研工作区'))
        // 等 React Query 状态更新 + options prop 填充，再 mouseDown 打开下拉
        await waitFor(() => { fireEvent.mouseDown(rowCombo()) })
        expect(await screen.findByText('科研经费表')).toBeInTheDocument()
        fireEvent.click(screen.getByText('科研经费表'))
        fireEvent.click(screen.getByRole('button', { name: /^引\s*入$/ }))

        fireEvent.change(screen.getByPlaceholderText('例如：月度销售汇总'), { target: { value: '跨区报表' } })
        fireEvent.click(screen.getByRole('button', { name: /^创\s*建$/ }))

        await waitFor(() => expect(postBodies).toHaveLength(1))
        expect(postBodies[0].extra_table_ids).toEqual([200])
        expect(await screen.findByText('模板已创建')).toBeInTheDocument()
    })

    it('编辑旧模板 output_format/theme 为 null 时回显默认值并随 PUT 提交 docx/minimal', async () => {
        const putBodies: Record<string, unknown>[] = []
        server.use(
            http.get('/api/v1/reports', () =>
                HttpResponse.json([{ ...TPL, output_format: null, theme: null }])),
            http.get('/api/v1/reports/1', () =>
                HttpResponse.json({ ...TPL, output_format: null, theme: null, template_content: 'Hello' })),
            http.put('/api/v1/reports/1', async ({ request }) => {
                putBodies.push(await request.json() as Record<string, unknown>)
                return HttpResponse.json({})
            }),
        )
        renderPage()

        fireEvent.mouseEnter(await screen.findByRole('button', { name: 'more' }))
        fireEvent.click(await screen.findByText('编辑'))
        await waitFor(() => expect(document.querySelector('.ant-modal-title')).toHaveTextContent('编辑模板'))
        // 输出格式 / 主题风格不为空，回显默认项
        const themeRow = document.querySelector('.report-theme-row')
        expect(themeRow?.textContent).toContain('简约')
        expect(screen.getAllByText('Word (.docx)').length).toBeGreaterThan(0)
        fireEvent.click(screen.getByRole('button', { name: /^保\s*存$/ }))

        await waitFor(() => expect(putBodies).toHaveLength(1))
        expect(putBodies[0].output_format).toBe('docx')
        expect(putBodies[0].theme).toBe('minimal')
    })

    it('编辑模板重复打开（先建后改）下拉默认值不残留为空', async () => {
        const putBodies: Record<string, unknown>[] = []
        server.use(
            http.get('/api/v1/reports', () => HttpResponse.json([{ ...TPL, output_format: null, theme: null }])),
            http.get('/api/v1/reports/1', () =>
                HttpResponse.json({ ...TPL, output_format: null, theme: null, template_content: 'Hello' })),
            http.put('/api/v1/reports/1', async ({ request }) => {
                putBodies.push(await request.json() as Record<string, unknown>)
                return HttpResponse.json({})
            }),
        )
        renderPage()

        // 第一次打开编辑弹窗再关闭
        fireEvent.mouseEnter(await screen.findByRole('button', { name: 'more' }))
        fireEvent.click(await screen.findByText('编辑'))
        await waitFor(() => expect(document.querySelector('.ant-modal-title')).toHaveTextContent('编辑模板'))
        fireEvent.click(await screen.findByRole('button', { name: /^取\s*消$/ }))

        // 再次打开，输出格式 / 主题风格仍回显默认项（preserve=false + destroyOnHidden 场景）
        fireEvent.mouseEnter(screen.getByRole('button', { name: 'more' }))
        fireEvent.click(await screen.findByText('编辑'))
        await waitFor(() => expect(document.querySelector('.ant-modal-title')).toHaveTextContent('编辑模板'))
        await waitFor(() => expect(document.querySelector('.report-theme-row')?.textContent).toContain('简约'))
        fireEvent.click(screen.getByRole('button', { name: /^保\s*存$/ }))

        await waitFor(() => expect(putBodies).toHaveLength(1))
        expect(putBodies[0].output_format).toBe('docx')
        expect(putBodies[0].theme).toBe('minimal')
    })
})

describe('ReportsPage 主题风格', () => {
    /** 打开编辑器弹窗内"主题风格"下拉的 combobox */
    const themeCombo = () => {
        const row = document.querySelector('.report-theme-row')
        expect(row).not.toBeNull()
        const combo = row!.querySelector('.ant-select-selector')
        expect(combo).not.toBeNull()
        return combo!
    }

    it('新建模板主题默认简约，保存时随 payload 提交 theme=minimal', async () => {
        const postBodies: Record<string, unknown>[] = []
        server.use(
            http.get('/api/v1/reports', () => HttpResponse.json([])),
            http.post('/api/v1/reports', async ({ request }) => {
                postBodies.push(await request.json() as Record<string, unknown>)
                return HttpResponse.json({ id: 9 })
            }),
        )
        renderPage()

        fireEvent.click((await screen.findAllByRole('button', { name: /新\s*建\s*模\s*板/ }))[0])
        await waitFor(() => expect(document.querySelector('.ant-modal-title')).toHaveTextContent('新建模板'))

        // 主题选择入口存在且默认显示"简约"
        await waitFor(() => expect(themeCombo().textContent).toContain('简约'))
        // 下拉含全部五类主题
        fireEvent.mouseDown(themeCombo())
        expect(await screen.findByRole('option', { name: '商务' })).toBeInTheDocument()
        expect(screen.getByRole('option', { name: '现代' })).toBeInTheDocument()
        expect(screen.getByRole('option', { name: '工程' })).toBeInTheDocument()
        expect(screen.getByRole('option', { name: '学术' })).toBeInTheDocument()
        fireEvent.click(screen.getByRole('option', { name: '简约' }))

        fireEvent.change(screen.getByPlaceholderText('例如：月度销售汇总'), { target: { value: '简约月报' } })
        fireEvent.click(screen.getByRole('button', { name: /^创\s*建$/ }))

        await waitFor(() => expect(postBodies).toHaveLength(1))
        expect(postBodies[0].theme).toBe('minimal')
    })

    it('新建模板选择商务主题后随保存提交 theme=business', async () => {
        const postBodies: Record<string, unknown>[] = []
        server.use(
            http.get('/api/v1/reports', () => HttpResponse.json([])),
            http.post('/api/v1/reports', async ({ request }) => {
                postBodies.push(await request.json() as Record<string, unknown>)
                return HttpResponse.json({ id: 9 })
            }),
        )
        renderPage()

        fireEvent.click((await screen.findAllByRole('button', { name: /新\s*建\s*模\s*板/ }))[0])
        await waitFor(() => expect(document.querySelector('.ant-modal-title')).toHaveTextContent('新建模板'))

        fireEvent.mouseDown(themeCombo())
        fireEvent.click(await screen.findByRole('option', { name: '商务' }))
        await waitFor(() => expect(themeCombo().textContent).toContain('商务'))

        fireEvent.change(screen.getByPlaceholderText('例如：月度销售汇总'), { target: { value: '商务月报' } })
        fireEvent.click(screen.getByRole('button', { name: /^创\s*建$/ }))

        await waitFor(() => expect(postBodies).toHaveLength(1))
        expect(postBodies[0].theme).toBe('business')
    })

    it('编辑模板：已有主题回显，保存时随 PUT 提交', async () => {
        const putBodies: Record<string, unknown>[] = []
        server.use(
            http.get('/api/v1/reports', () => HttpResponse.json([{ ...TPL, theme: 'academic' }])),
            http.get('/api/v1/reports/1', () =>
                HttpResponse.json({ ...TPL, theme: 'academic', template_content: 'Hello' })),
            http.put('/api/v1/reports/1', async ({ request }) => {
                putBodies.push(await request.json() as Record<string, unknown>)
                return HttpResponse.json({})
            }),
        )
        renderPage()

        fireEvent.mouseEnter(await screen.findByRole('button', { name: 'more' }))
        fireEvent.click(await screen.findByText('编辑'))
        await waitFor(() => expect(document.querySelector('.ant-modal-title')).toHaveTextContent('编辑模板'))
        // 回显为学术主题
        await waitFor(() => expect(themeCombo().textContent).toContain('学术'))
        fireEvent.click(screen.getByRole('button', { name: /^保\s*存$/ }))

        await waitFor(() => expect(putBodies).toHaveLength(1))
        expect(putBodies[0].theme).toBe('academic')
    })
})
