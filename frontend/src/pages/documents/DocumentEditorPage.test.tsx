/**
 * 文档编辑器测试 —— 数据表动态引用闭环 + 大纲面板：
 * 编辑器插入引用辅助（选表弹窗 → 光标位置插入占位符）/ 预览侧动态渲染 /
 * 大纲抽屉实时解析标题并点击定位预览锚点。
 */

import { describe, expect, it, beforeEach, vi } from 'vitest'
import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { Routes, Route, useLocation } from 'react-router-dom'
import { http, HttpResponse } from 'msw'
import { message } from 'antd'
import DocumentEditorPage from './DocumentEditorPage'
import { renderProviders } from '@/test/render-providers'
import { mockDocuments, mockUser, server } from '@/test/msw'

function renderEditor(route = '/w/10/documents/2') {
    return renderProviders(
        <Routes>
            <Route path="/w/:wid/documents/:docId" element={<DocumentEditorPage />} />
        </Routes>,
        { route, initialAuth: { user: mockUser, token: 'fake-token' } },
    )
}

/** 位置探针：展示当前 pathname 供跳转断言 */
function LocationProbe() {
    const loc = useLocation()
    return <div data-testid="editor-location">{loc.pathname}</div>
}

/** 带位置探针的编辑器渲染：跳转类用例（双链 / 反链）断言 URL 变化 */
function renderEditorWithProbe(route = '/w/10/documents/2') {
    return renderProviders(
        <Routes>
            <Route
                path="/w/:wid/documents/:docId"
                element={
                    <>
                        <DocumentEditorPage />
                        <LocationProbe />
                    </>
                }
            />
        </Routes>,
        { route, initialAuth: { user: mockUser, token: 'fake-token' } },
    )
}

describe('DocumentEditorPage 数据表动态引用', () => {
    beforeEach(() => {
        server.resetHandlers()
    })

    it('插入辅助：选表弹窗 → 插入占位符到光标处，预览侧动态渲染', async () => {
        renderEditor()

        // 初始内容加载（msw content：# 需求说明）
        expect(await screen.findByText('需求说明')).toBeInTheDocument()

        // 打开插入弹窗
        fireEvent.click(screen.getByRole('button', { name: /插入表格引用/ }))
        expect(await screen.findByText('选择要引用的数据表')).toBeInTheDocument()

        // 选择「客户表」（下拉选项）：等表列表 query 就绪后打开下拉
        const combo = await screen.findByRole('combobox')
        fireEvent.mouseDown(combo)
        fireEvent.click(await screen.findByText('客户表'))

        // 确认插入（「插入」按钮）
        fireEvent.click(screen.getByRole('button', { name: /^插\s*入$/ }))

        // 编辑区出现占位符且独占段落（前后为行首/文首与空行/文末）
        await waitFor(() => {
            const ta = document.querySelector<HTMLTextAreaElement>('textarea')
            expect(ta?.value).toMatch(/(^|\n\n)\{\{table:100\}\}(\n\n|$)/)
        })

        // 预览侧动态渲染数据表（行数据出现即视为渲染成功；表名与 Select 选项重名不唯一）
        expect(await screen.findByText('张三')).toBeInTheDocument()
        expect(screen.getByText('李四')).toBeInTheDocument()
    })

    it('未选择表时插入按钮禁用', async () => {
        renderEditor()
        expect(await screen.findByText('需求说明')).toBeInTheDocument()

        fireEvent.click(screen.getByRole('button', { name: /插入表格引用/ }))
        const okBtn = await screen.findByRole('button', { name: /^插\s*入$/ })
        expect(okBtn).toBeDisabled()
    })
})

describe('DocumentEditorPage 大纲面板', () => {
    beforeEach(() => {
        server.resetHandlers()
        // 多级标题文档：大纲与预览锚点的数据源
        server.use(
            http.get('/api/v1/workspaces/:wid/documents/:docId/content', () =>
                HttpResponse.json({
                    ...mockDocuments[1],
                    content: '# 需求说明\n\n## 背景\n\n正文。\n\n## 目标\n\n### 细分\n',
                    version_number: 1,
                })),
        )
    })

    it('大纲抽屉：实时解析标题层级，点击定位预览锚点', async () => {
        // jsdom 无 scrollIntoView，mock 捕获调用
        const scrollIntoView = vi.fn()
        Element.prototype.scrollIntoView = scrollIntoView as unknown as typeof Element.prototype.scrollIntoView
        renderEditor()

        // 顶栏大纲按钮显示条目数（4 个标题）
        expect(await screen.findByRole('button', { name: /大纲\s*\(4\)/ })).toBeInTheDocument()

        // 打开抽屉：层级条目齐备
        fireEvent.click(screen.getByRole('button', { name: /大纲/ }))
        expect(await screen.findByTestId('doc-outline-item-0')).toHaveTextContent('需求说明')
        expect(screen.getByTestId('doc-outline-item-1')).toHaveTextContent('背景')
        expect(screen.getByTestId('doc-outline-item-3')).toHaveTextContent('细分')

        // 预览侧锚点已渲染（同 id 算法）
        expect(document.getElementById('doc-h-目标')).toBeInTheDocument()

        // 点击「目标」：滚动定位到对应锚点
        fireEvent.click(screen.getByTestId('doc-outline-item-2'))
        await waitFor(() => {
            expect(scrollIntoView).toHaveBeenCalled()
        })
    })

    it('编辑输入实时更新大纲（未保存也生效）', async () => {
        renderEditor()
        expect(await screen.findByRole('button', { name: /大纲\s*\(4\)/ })).toBeInTheDocument()

        const ta = document.querySelector<HTMLTextAreaElement>('textarea')!
        fireEvent.change(ta, { target: { value: '# 新标题\n\n正文' } })
        await waitFor(() => {
            expect(screen.getByRole('button', { name: /大纲\s*\(1\)/ })).toBeInTheDocument()
        })

        fireEvent.click(screen.getByRole('button', { name: /大纲/ }))
        expect(await screen.findByTestId('doc-outline-item-0')).toHaveTextContent('新标题')
    })
})

describe('DocumentEditorPage 反向链接', () => {
    beforeEach(() => {
        server.resetHandlers()
    })

    it('反链抽屉：列出引用了本文档的文档，点击跳转', async () => {
        renderEditorWithProbe()
        // 页面加载完成（保存按钮出现）
        expect(await screen.findByRole('button', { name: /保存/ })).toBeInTheDocument()

        fireEvent.click(screen.getByRole('button', { name: /反链/ }))
        // msw 反链 fixture：会议纪要引用了需求说明
        expect(await screen.findByTestId('doc-backlink-3')).toHaveTextContent('会议纪要')

        fireEvent.click(screen.getByTestId('doc-backlink-3'))
        await waitFor(() => {
            expect(screen.getByTestId('editor-location')).toHaveTextContent('/w/10/documents/3')
        })
    })
})

describe('DocumentEditorPage 出链与断链修复', () => {
    beforeEach(() => {
        server.resetHandlers()
    })

    it('出链抽屉：区分已解析与断链，可跳转目标文档', async () => {
        renderEditorWithProbe()
        expect(await screen.findByRole('button', { name: /保存/ })).toBeInTheDocument()

        fireEvent.click(screen.getByTestId('doc-links-open'))
        expect(await screen.findByTestId('doc-link-需求说明')).toHaveTextContent('已解析')
        expect(screen.getByTestId('doc-link-不存在的文档')).toHaveTextContent('断链')
        expect(screen.getByText('1 条断链')).toBeInTheDocument()

        fireEvent.click(screen.getByTestId('doc-link-open-需求说明'))
        await waitFor(() => {
            expect(screen.getByTestId('editor-location')).toHaveTextContent('/w/10/documents/2')
        })
    })

    it('选择目标文档后修复断链：提交 repairs 并提示修复结果', async () => {
        // stub 静态 message：断言调用即可，同时避免污染全局 setup 清理掉的 message 容器
        const successSpy = vi
            .spyOn(message, 'success')
            .mockImplementation((() => {}) as unknown as typeof message.success)
        const bodies: unknown[] = []
        server.use(
            http.post('/api/v1/workspaces/:wid/documents/:docId/links/repair', async ({ request }) => {
                bodies.push(await request.json())
                return HttpResponse.json({
                    document_id: 2,
                    version_number: 2,
                    repaired: [{ title: '不存在的文档', new_title: '会议纪要', document_id: 3, count: 1 }],
                    replaced: 1,
                    document: mockDocuments[1],
                })
            }),
        )
        renderEditor()
        await screen.findByRole('button', { name: /保存/ })

        fireEvent.click(screen.getByTestId('doc-links-open'))
        const repairBtn = await screen.findByTestId('doc-link-repair')
        expect(repairBtn).toBeDisabled()

        fireEvent.mouseDown(
            within(screen.getByTestId('doc-link-target-不存在的文档')).getByRole('combobox'),
        )
        fireEvent.click(await screen.findByText(/会议纪要/))

        await waitFor(() => {
            expect(screen.getByTestId('doc-link-repair')).toBeEnabled()
        })
        fireEvent.click(screen.getByTestId('doc-link-repair'))

        await waitFor(() => {
            expect(bodies).toEqual([
                { repairs: [{ title: '不存在的文档', target_document_id: 3 }] },
            ])
        })
        await waitFor(() => {
            expect(successSpy).toHaveBeenCalledWith(expect.stringContaining('已修复 1 处链接'))
        })
    })
})

describe('DocumentEditorPage 双向链接跳转', () => {
    beforeEach(() => {
        server.resetHandlers()
        // 正文含双链；文档树中存在标题匹配的非文件夹文档 id=5
        server.use(
            http.get('/api/v1/workspaces/:wid/documents/:docId/content', () =>
                HttpResponse.json({
                    ...mockDocuments[1],
                    content: '参见 [[客户需求]] 文档。\n',
                    version_number: 1,
                })),
            http.get('/api/v1/workspaces/:wid/documents/tree', () =>
                HttpResponse.json({
                    items: [
                        ...mockDocuments,
                        { ...mockDocuments[1], id: 5, title: '客户需求', parent_id: null, sort_order: 2 },
                    ],
                })),
        )
    })

    it('点击预览中的 [[标题]]：按标题定位文档树并跳转', async () => {
        renderEditorWithProbe()

        const link = await screen.findByTestId('doc-wikilink')
        expect(link).toHaveTextContent('客户需求')

        fireEvent.click(link)
        await waitFor(() => {
            expect(screen.getByTestId('editor-location')).toHaveTextContent('/w/10/documents/5')
        })
    })

    it('双链目标不存在：提示未找到且不跳转', async () => {
        // 树中不含「客户需求」标题的文档
        server.use(
            http.get('/api/v1/workspaces/:wid/documents/tree', () =>
                HttpResponse.json({ items: mockDocuments })),
        )
        renderEditorWithProbe()

        fireEvent.click(await screen.findByTestId('doc-wikilink'))
        await waitFor(() => {
            expect(screen.getByText(/未找到文档/)).toBeInTheDocument()
        })
        expect(screen.getByTestId('editor-location')).toHaveTextContent('/w/10/documents/2')
    })
})

describe('DocumentEditorPage 文档导出', () => {
    beforeEach(() => {
        server.resetHandlers()
    })

    it('导出 Word：请求 export 端点并触发浏览器下载', async () => {
        const createSpy = vi.fn(() => 'blob:mock-doc')
        const revokeSpy = vi.fn()
        Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: createSpy })
        Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: revokeSpy })

        let requestedUrl = ''
        server.use(
            http.get('/api/v1/workspaces/:wid/documents/:docId/export', ({ request }) => {
                requestedUrl = request.url
                return new HttpResponse(new Blob(['PK']), { status: 200 })
            }),
        )

        renderEditor()
        expect(await screen.findByText('需求说明')).toBeInTheDocument()

        fireEvent.click(screen.getByTestId('doc-export-btn'))
        fireEvent.click(await screen.findByText('导出 Word (.docx)'))

        await waitFor(() => {
            expect(requestedUrl).toContain('/documents/2/export')
            expect(requestedUrl).toContain('format=docx')
        })
        await waitFor(() => expect(createSpy).toHaveBeenCalled())
        expect(revokeSpy).toHaveBeenCalled()
    })

    it('导出 Markdown：请求 format=md', async () => {
        let requestedUrl = ''
        server.use(
            http.get('/api/v1/workspaces/:wid/documents/:docId/export', ({ request }) => {
                requestedUrl = request.url
                return new HttpResponse('# 需求说明', { status: 200 })
            }),
        )

        renderEditor()
        expect(await screen.findByText('需求说明')).toBeInTheDocument()

        fireEvent.click(screen.getByTestId('doc-export-btn'))
        fireEvent.click(await screen.findByText('导出 Markdown (.md)'))

        await waitFor(() => {
            expect(requestedUrl).toContain('format=md')
        })
    })
})
