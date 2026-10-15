/**
 * 文档编辑器测试 —— 数据表动态引用闭环 + 大纲面板：
 * 编辑器插入引用辅助（选表弹窗 → 光标位置插入占位符）/ 预览侧动态渲染 /
 * 大纲抽屉实时解析标题并点击定位预览锚点。
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { Routes, Route, useLocation } from 'react-router-dom'
import { http, HttpResponse } from 'msw'
import { message } from 'antd'
import { documentsApi } from '@/api/documents'
import DocumentEditorPage from './DocumentEditorPage'
import { renderProviders } from '@/test/render-providers'
import { mockDocuments, mockUser, server } from '@/test/msw'
import type { ResponsiveState } from '@/hooks/useResponsive'

// 可控 useResponsive mock：默认桌面端，窄屏用例在其内部切换
let responsiveState: ResponsiveState = {
    deviceType: 'desktop', isMobile: false, isTablet: false, isDesktop: true,
    width: 1280, height: 800,
}
vi.mock('@/hooks/useResponsive', async () => {
    const actual = await vi.importActual<typeof import('@/hooks/useResponsive')>('@/hooks/useResponsive')
    return { ...actual, useResponsive: () => responsiveState }
})

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

describe('DocumentEditorPage 修改申请（双轨制保存）', () => {
    beforeEach(() => {
        server.resetHandlers()
    })

    it('无直编资格时保存转为修改申请：提示已提交而非已保存', async () => {
        const putBodies: Record<string, unknown>[] = []
        server.use(
            http.put('/api/v1/workspaces/:wid/documents/:docId/content', async ({ request }) => {
                putBodies.push(await request.json() as Record<string, unknown>)
                return HttpResponse.json(
                    {
                        change_request: { id: 7, status: 'open', document_id: 2, title: '修改文档《需求说明》' },
                        message: '已提交修改申请 #7，审核通过后生效',
                    },
                    { status: 202 },
                )
            }),
        )
        renderEditor()
        expect(await screen.findByText('需求说明')).toBeInTheDocument()

        fireEvent.click(screen.getByRole('button', { name: /保\s*存/ }))

        expect(await screen.findByTestId('doc-cr-notice')).toHaveTextContent('已提交修改申请 #7')
        expect(screen.queryByText(/已保存 v/)).toBeNull()
        // 提交时携带内容基准版本号，供后端判定基准漂移
        expect(putBodies[0]?.base_version_number).toBe(1)
    })

    it('「修改申请」入口打开抽屉并展示空态', async () => {
        renderEditor()
        expect(await screen.findByText('需求说明')).toBeInTheDocument()

        fireEvent.click(screen.getByTestId('doc-cr-open'))

        expect(await screen.findByText(/暂无修改申请/)).toBeInTheDocument()
    })
})

describe('DocumentEditorPage 窄屏工具栏', () => {
    beforeEach(() => {
        responsiveState = {
            deviceType: 'mobile', isMobile: true, isTablet: false, isDesktop: false,
            width: 390, height: 844,
        }
        // 文档详情/正文沿用 msw.ts 默认 handler（其 fixture 字段完整）
    })

    afterEach(() => {
        responsiveState = {
            deviceType: 'desktop', isMobile: false, isTablet: false, isDesktop: true,
            width: 1280, height: 800,
        }
    })

    it('只保留大纲 / 更多 / 保存，其余入口收进更多菜单并可触发', async () => {
        renderEditor()
        expect(await screen.findByText('需求说明')).toBeInTheDocument()

        // 窄屏：桌面常显的次级入口不直接渲染
        expect(screen.queryByTestId('doc-cr-open')).toBeNull()
        expect(screen.queryByTestId('doc-links-open')).toBeNull()
        expect(screen.queryByTestId('doc-export-btn')).toBeNull()
        expect(screen.getByText(/大\s*纲/)).toBeInTheDocument()
        expect(screen.getByTestId('doc-save-btn')).toBeInTheDocument()
        expect(screen.getByTestId('doc-more-actions')).toBeInTheDocument()

        // 更多菜单承载次级入口（含导出子菜单）
        fireEvent.click(screen.getByTestId('doc-more-actions'))
        for (const label of ['反向链接', '文档链接', '插入表格引用', '标签', '修改申请', '版本', '导出']) {
            // 标签/修改申请/版本可能带数量后缀，用前缀正则匹配
            expect(await screen.findByText(new RegExp(`^${label}`))).toBeInTheDocument()
        }
    })

    it('更多菜单里的「文档链接」打开链接抽屉', async () => {
        server.use(
            http.get('/api/v1/workspaces/10/documents/2/links', () =>
                HttpResponse.json({
                    items: [{ title: '销售运营手册', document_id: 3, exists: true, broken: false }],
                    total: 1,
                    broken: 0,
                })),
        )
        renderEditor()
        expect(await screen.findByText('需求说明')).toBeInTheDocument()

        fireEvent.click(screen.getByTestId('doc-more-actions'))
        fireEvent.click(await screen.findByText('文档链接'))

        await waitFor(() => expect(screen.getAllByText('文档链接').length).toBeGreaterThan(0))
        expect(await screen.findByText('已解析')).toBeInTheDocument()
    })

    it('窄屏用「编辑 / 预览」页签切换面板，不再左右分栏', async () => {
        renderEditor()
        expect(await screen.findByText('需求说明')).toBeInTheDocument()

        // 窄屏：页签切换 + 单面板（无 Splitter）
        const sw = screen.getByTestId('doc-mobile-pane-switch')
        expect(sw).toBeInTheDocument()
        expect(document.querySelector('.ant-splitter')).toBeNull()
        // 默认编辑面板
        expect(document.querySelector('textarea')).toBeInTheDocument()
        expect(document.querySelector('.doc-md-preview')).toBeNull()

        fireEvent.click(screen.getByText('预览'))
        await waitFor(() => expect(document.querySelector('.doc-md-preview')).toBeInTheDocument())
        expect(document.querySelector('textarea')).toBeNull()

        fireEvent.click(screen.getByText('编辑'))
        await waitFor(() => expect(document.querySelector('textarea')).toBeInTheDocument())
    })

    it('桌面端保持左右分栏，不渲染窄屏页签', async () => {
        responsiveState = {
            deviceType: 'desktop', isMobile: false, isTablet: false, isDesktop: true,
            width: 1280, height: 800,
        }
        renderEditor()
        expect(await screen.findByText('需求说明')).toBeInTheDocument()

        expect(screen.queryByTestId('doc-mobile-pane-switch')).toBeNull()
        expect(document.querySelector('.ant-splitter')).toBeTruthy()
        expect(document.querySelector('textarea')).toBeInTheDocument()
    })

    it('大纲点击锚点时窄屏先切到预览面板', async () => {
        renderEditor()
        expect(await screen.findByText('需求说明')).toBeInTheDocument()

        // 打开大纲抽屉并点击一个标题
        fireEvent.click(screen.getByText(/大\s*纲/))
        fireEvent.click(await screen.findByText('需求说明', { selector: '.ant-drawer *' }))

        await waitFor(() => expect(document.querySelector('.doc-md-preview')).toBeInTheDocument())
    })

    it('桌面端保持全部按钮常显，不渲染更多入口', async () => {
        responsiveState = {
            deviceType: 'desktop', isMobile: false, isTablet: false, isDesktop: true,
            width: 1280, height: 800,
        }
        renderEditor()
        expect(await screen.findByText('需求说明')).toBeInTheDocument()

        expect(screen.getByTestId('doc-links-open')).toBeInTheDocument()
        expect(screen.getByTestId('doc-cr-open')).toBeInTheDocument()
        expect(screen.getByTestId('doc-export-btn')).toBeInTheDocument()
        expect(screen.queryByTestId('doc-more-actions')).toBeNull()
    })

describe('DocumentEditorPage Markdown 快捷工具', () => {
    it('点击工具栏「加粗」把选中文本包裹为 **…** 并保留选区', async () => {
        renderEditor()
        const ta = (await screen.findByPlaceholderText('输入 Markdown 内容…')) as HTMLTextAreaElement
        const original = ta.value
        ta.setSelectionRange(0, 2)

        fireEvent.click(screen.getByTestId('md-toolbar-bold'))

        await waitFor(() => expect(ta.value.startsWith(`**${original.slice(0, 2)}**`)).toBe(true))
        // 光标恢复到文字上（不是跳到末尾）
        await waitFor(() => {
            expect(ta.selectionStart).toBe(2)
            expect(ta.selectionEnd).toBe(4)
        })
    })

    it('Ctrl+B / Ctrl+I / Ctrl+K 快捷键生效', async () => {
        renderEditor()
        const ta = (await screen.findByPlaceholderText('输入 Markdown 内容…')) as HTMLTextAreaElement

        ta.setSelectionRange(0, 1)
        fireEvent.keyDown(ta, { key: 'b', ctrlKey: true })
        await waitFor(() => expect(ta.value.startsWith('**')).toBe(true))

        const afterBold = ta.value
        // 文本域先于文档内容渲染：先等内容加载完再改标题，
        // 否则标题操作作用在空内容上（CI 上曾因此偶发 "expected false to be true"）
        await waitFor(() => expect(ta.value.length).toBeGreaterThan(0))
        ta.setSelectionRange(0, 0)
        fireEvent.keyDown(ta, { key: 'i', ctrlKey: true })
        await waitFor(() => expect(ta.value).not.toBe(afterBold))

        ta.setSelectionRange(0, 3)
        fireEvent.keyDown(ta, { key: 'k', ctrlKey: true })
        await waitFor(() => expect(ta.value).toContain('](https://)'))
    })

    it('列表 / 引用 / 代码块按钮作用于整行', async () => {
        renderEditor()
        const ta = (await screen.findByPlaceholderText('输入 Markdown 内容…')) as HTMLTextAreaElement
        // 文本域先于文档内容渲染：先等内容加载完再改标题，
        // 否则标题操作作用在空内容上（CI 上曾因此偶发 "expected false to be true"）
        await waitFor(() => expect(ta.value.length).toBeGreaterThan(0))
        ta.setSelectionRange(0, 0)

        fireEvent.click(screen.getByTestId('md-toolbar-ul'))
        await waitFor(() => expect(ta.value.startsWith('- ')).toBe(true))

        fireEvent.click(screen.getByTestId('md-toolbar-codeblock'))
        await waitFor(() => expect(ta.value).toContain('```'))
    })
})
})

describe('DocumentEditorPage 查找与替换', () => {
    // mock 正文为 '# 需求说明\n\n正文段落。\n'
    it('Ctrl+F 打开查找条并实时统计匹配数', async () => {
        renderEditor()
        const ta = (await screen.findByPlaceholderText('输入 Markdown 内容…')) as HTMLTextAreaElement

        expect(screen.queryByTestId('doc-find-bar')).toBeNull()
        fireEvent.keyDown(ta, { key: 'f', ctrlKey: true })

        expect(await screen.findByTestId('doc-find-bar')).toBeInTheDocument()
        fireEvent.change(screen.getByTestId('doc-find-input'), { target: { value: '正文' } })
        await waitFor(() => expect(screen.getByTestId('doc-find-count')).toHaveTextContent('1/1'))

        fireEvent.change(screen.getByTestId('doc-find-input'), { target: { value: '不存在的词' } })
        await waitFor(() => expect(screen.getByTestId('doc-find-count')).toHaveTextContent('无结果'))
    })

    it('「下一个」定位匹配：textarea 选区落到匹配文字上', async () => {
        renderEditor()
        const ta = (await screen.findByPlaceholderText('输入 Markdown 内容…')) as HTMLTextAreaElement
        fireEvent.keyDown(ta, { key: 'f', ctrlKey: true })
        await screen.findByTestId('doc-find-bar')
        fireEvent.change(screen.getByTestId('doc-find-input'), { target: { value: '正文' } })

        fireEvent.click(screen.getByTestId('doc-find-next'))
        await waitFor(() => {
            expect(ta.value.slice(ta.selectionStart, ta.selectionEnd)).toBe('正文')
        })
    })

    it('全部替换改写正文并提示处数，Esc 关闭查找条', async () => {
        renderEditor()
        const ta = (await screen.findByPlaceholderText('输入 Markdown 内容…')) as HTMLTextAreaElement
        fireEvent.keyDown(ta, { key: 'f', ctrlKey: true })
        await screen.findByTestId('doc-find-bar')
        fireEvent.change(screen.getByTestId('doc-find-input'), { target: { value: '段落' } })
        fireEvent.change(screen.getByTestId('doc-find-replacement'), { target: { value: '内容' } })

        const before = ta.value
        expect(before).toContain('段落')
        fireEvent.click(screen.getByTestId('doc-find-replace-all'))

        await waitFor(() => expect(ta.value).not.toBe(before))
        expect(ta.value).toContain('正文内容')
        expect(ta.value).not.toContain('段落')
        // 正文被改动 → 出现未保存提示
        expect(screen.getByText('未保存')).toBeInTheDocument()

        fireEvent.keyDown(ta, { key: 'Escape' })
        await waitFor(() => expect(screen.queryByTestId('doc-find-bar')).toBeNull())
    })

    it('「查找」按钮打开查找条；区分大小写开关影响匹配数', async () => {
        renderEditor()
        const ta = (await screen.findByPlaceholderText('输入 Markdown 内容…')) as HTMLTextAreaElement

        fireEvent.click(screen.getByTestId('doc-find-open'))
        await screen.findByTestId('doc-find-bar')
        // 写入混合大小写文本，便于验证大小写开关
        fireEvent.change(ta, { target: { value: 'Alpha alpha ALPHA' } })
        fireEvent.change(screen.getByTestId('doc-find-input'), { target: { value: 'alpha' } })
        await waitFor(() => expect(screen.getByTestId('doc-find-count')).toHaveTextContent('1/3'))

        fireEvent.click(screen.getByTestId('doc-find-case'))
        await waitFor(() => expect(screen.getByTestId('doc-find-count')).toHaveTextContent('1/1'))
    })
})

describe('DocumentEditorPage 路径面包屑', () => {
    function renderWithListProbe(route = '/w/10/documents/2') {
        function Probe() {
            const loc = useLocation()
            return <div data-testid="list-location">{loc.pathname + loc.search}</div>
        }
        return renderProviders(
            <Routes>
                <Route path="/w/:wid/documents" element={<Probe />} />
                <Route path="/w/:wid/documents/:docId" element={<DocumentEditorPage />} />
            </Routes>,
            { route, initialAuth: { user: mockUser, token: 'fake-token' } },
        )
    }

    it('展示祖先路径（文档 / 文件夹），点击文件夹跳到该文件夹列表', async () => {
        renderWithListProbe()

        const crumb = await screen.findByTestId('doc-path-crumb')
        expect(crumb).toHaveTextContent('文档')
        expect(crumb).toHaveTextContent('产品文档')

        fireEvent.click(within(crumb).getByText('产品文档'))
        await waitFor(() => expect(screen.getByTestId('list-location')).toHaveTextContent('/w/10/documents?parent=1'))
    })

    it('点击「文档」回到总览（不带 parent 参数）', async () => {
        renderWithListProbe()

        const crumb = await screen.findByTestId('doc-path-crumb')
        fireEvent.click(within(crumb).getByText('文档'))
        await waitFor(() => {
            const loc = screen.getByTestId('list-location')
            expect(loc).toHaveTextContent('/w/10/documents')
            expect(loc.textContent).not.toContain('parent=')
        })
    })
})

describe('DocumentEditorPage 插入图片', () => {
    it('选择图片后上传到工作区文件存储，并在光标处插入站内引用', async () => {
        const hits: string[] = []
        server.use(
            http.post('/api/v1/workspaces/10/files', ({ request }) => {
                hits.push(request.url)
                return HttpResponse.json(
                    { file_key: 'abc123.png', filename: 'arch.png', size: 4, mime_type: 'image/png' },
                    { status: 201 },
                )
            }),
        )
        renderEditor()
        const ta = (await screen.findByPlaceholderText('输入 Markdown 内容…')) as HTMLTextAreaElement
        // 光标放到正文末尾
        ta.setSelectionRange(ta.value.length, ta.value.length)

        const input = screen.getByTestId('doc-image-input') as HTMLInputElement
        const file = new File([new Uint8Array([137, 80, 78, 71])], 'arch.png', { type: 'image/png' })
        // jsdom 中 input.files 只读：注入后触发 change（与真实选择文件同一条链路）
        Object.defineProperty(input, 'files', { value: [file], configurable: true })
        fireEvent.change(input)

        await waitFor(() => expect(hits).toHaveLength(1))
        await waitFor(() => expect(ta.value).toContain('![arch.png](file:abc123.png)'))
        // 插入后标记为未保存
        expect(screen.getByText('未保存')).toBeInTheDocument()
    })

    it('上传失败时不改动正文（请求已发起但不插入引用）', async () => {
        const hits: string[] = []
        server.use(
            http.post('/api/v1/workspaces/10/files', ({ request }) => {
                hits.push(request.url)
                return new HttpResponse(null, { status: 500 })
            }),
        )
        renderEditor()
        const ta = (await screen.findByPlaceholderText('输入 Markdown 内容…')) as HTMLTextAreaElement
        const before = ta.value

        const input = screen.getByTestId('doc-image-input') as HTMLInputElement
        const file = new File([new Uint8Array([137, 80, 78, 71])], 'x.png', { type: 'image/png' })
        Object.defineProperty(input, 'files', { value: [file], configurable: true })
        fireEvent.change(input)

        await waitFor(() => expect(hits).toHaveLength(1))
        // 失败路径不得改动正文、不得出现未保存标记
        expect(ta.value).toBe(before)
        expect(screen.queryByText('未保存')).toBeNull()
    })

describe('DocumentEditorPage 粘贴图片与状态栏', () => {
    /** 构造带图片文件的剪贴板事件（jsdom 无 ClipboardEvent 构造器，手工拼 payload） */
    function pasteImage(ta: HTMLTextAreaElement, files: File[], plain = '') {
        const items = files.map(f => ({
            kind: 'file',
            type: f.type,
            getAsFile: () => f,
        }))
        // jsdom 的 ClipboardEvent.clipboardData 为只读，手工构造事件后挂载 payload
        const event = new Event('paste', { bubbles: true, cancelable: true })
        Object.defineProperty(event, 'clipboardData', {
            value: {
                items,
                getData: () => plain,
                types: files.length > 0 ? ['Files'] : ['text/plain'],
            },
        })
        fireEvent(ta, event)
    }

    it('粘贴图片：直接上传并插入站内引用', async () => {
        const hits: string[] = []
        server.use(
            http.post('/api/v1/workspaces/10/files', ({ request }) => {
                hits.push(request.url)
                return HttpResponse.json(
                    { file_key: 'paste-1.png', filename: 'pasted.png', size: 4, mime_type: 'image/png' },
                    { status: 201 },
                )
            }),
        )
        renderEditor()
        const ta = (await screen.findByPlaceholderText('输入 Markdown 内容…')) as HTMLTextAreaElement
        ta.setSelectionRange(ta.value.length, ta.value.length)

        const file = new File([new Uint8Array([137, 80, 78, 71])], 'pasted.png', { type: 'image/png' })
        pasteImage(ta, [file])

        await waitFor(() => expect(hits).toHaveLength(1))
        await waitFor(() => expect(ta.value).toContain('![pasted.png](file:paste-1.png)'))
    })

    it('粘贴纯文本：不上传、不拦截默认行为', async () => {
        let hits = 0
        server.use(
            http.post('/api/v1/workspaces/10/files', () => {
                hits += 1
                return HttpResponse.json({ file_key: 'x.png', filename: 'x.png' }, { status: 201 })
            }),
        )
        renderEditor()
        const ta = (await screen.findByPlaceholderText('输入 Markdown 内容…')) as HTMLTextAreaElement

        pasteImage(ta, [], '普通文本')

        await new Promise(r => setTimeout(r, 200))
        expect(hits).toBe(0)
    })

    it('一次粘贴多张图片：按顺序上传并插入多条引用', async () => {
        const keys = ['a1.png', 'b2.png']
        let seq = 0
        server.use(
            http.post('/api/v1/workspaces/10/files', () => {
                const key = keys[Math.min(seq, keys.length - 1)]
                seq += 1
                return HttpResponse.json({ file_key: key, filename: key, size: 4, mime_type: 'image/png' }, { status: 201 })
            }),
        )
        renderEditor()
        const ta = (await screen.findByPlaceholderText('输入 Markdown 内容…')) as HTMLTextAreaElement
        ta.setSelectionRange(ta.value.length, ta.value.length)

        const f1 = new File([new Uint8Array([1])], 'a.png', { type: 'image/png' })
        const f2 = new File([new Uint8Array([2])], 'b.png', { type: 'image/png' })
        pasteImage(ta, [f1, f2])

        await waitFor(() => expect(ta.value).toContain('![a.png](file:a1.png)'))
        await waitFor(() => expect(ta.value).toContain('![b.png](file:b2.png)'))
        // 两条引用都在（函数式插入不会互相覆盖）
        expect(ta.value.indexOf('![a.png]')).toBeLessThan(ta.value.indexOf('![b.png]'))
    })

    it('状态栏实时展示字数 / 行数', async () => {
        renderEditor()
        const ta = (await screen.findByPlaceholderText('输入 Markdown 内容…')) as HTMLTextAreaElement
        const stats = await screen.findByTestId('doc-stats')
        // 初始正文 '# 需求说明\n\n正文段落。\n'
        expect(stats.textContent).toMatch(/\d+ 字 · \d+ 行/)

        fireEvent.change(ta, { target: { value: '第一行\n第二行' } })
        await waitFor(() => expect(screen.getByTestId('doc-stats')).toHaveTextContent('7 字 · 2 行'))
    })
})

describe('DocumentEditorPage 最近打开记录', () => {
    it('打开文档后写入本地最近打开历史', async () => {
        window.localStorage.removeItem('cndb_recent_docs_v1:10')
        renderEditor()
        await screen.findByPlaceholderText('输入 Markdown 内容…')

        await waitFor(() => {
            const raw = window.localStorage.getItem('cndb_recent_docs_v1:10')
            expect(raw).toBeTruthy()
            expect(JSON.parse(raw as string)[0]).toMatchObject({ id: 2, title: '需求说明' })
        })
    })
})

describe('DocumentEditorPage 表格骨架与标题层级', () => {
    it('工具栏表格下拉：按预设插入 Markdown 表格骨架到光标处', async () => {
        renderEditor()
        const ta = (await screen.findByPlaceholderText('输入 Markdown 内容…')) as HTMLTextAreaElement
        ta.setSelectionRange(ta.value.length, ta.value.length)

        fireEvent.click(screen.getByTestId('md-toolbar-table'))
        fireEvent.click(await screen.findByText('2 列 × 2 行'))

        await waitFor(() => expect(ta.value).toContain('| 列 1 | 列 2 |'))
        expect(ta.value).toContain('| --- | --- |')
        expect(ta.value.split('\n').filter(l => l.startsWith('| \u00a0')).length).toBe(2)
        // 插入后标记未保存
        expect(screen.getByText('未保存')).toBeInTheDocument()
    })

    it('工具栏标题下拉：所选行变为三级标题', async () => {
        renderEditor()
        const ta = (await screen.findByPlaceholderText('输入 Markdown 内容…')) as HTMLTextAreaElement
        // 光标放在第一行（# 需求说明）
        // 文本域先于文档内容渲染：先等内容加载完再改标题，
        // 否则标题操作作用在空内容上（CI 上曾因此偶发 "expected false to be true"）
        await waitFor(() => expect(ta.value.length).toBeGreaterThan(0))
        ta.setSelectionRange(0, 0)

        fireEvent.click(screen.getByTestId('md-toolbar-heading'))
        fireEvent.click(await screen.findByText('三级标题'))

        await waitFor(() => expect(ta.value.startsWith('### 需求说明')).toBe(true))
    })

    it('工具栏标题下拉「正文」：取消已有标题', async () => {
        renderEditor()
        const ta = (await screen.findByPlaceholderText('输入 Markdown 内容…')) as HTMLTextAreaElement
        // 文本域先于文档内容渲染：先等内容加载完再改标题，
        // 否则标题操作作用在空内容上（CI 上曾因此偶发 "expected false to be true"）
        await waitFor(() => expect(ta.value.length).toBeGreaterThan(0))
        ta.setSelectionRange(0, 0)

        fireEvent.click(screen.getByTestId('md-toolbar-heading'))
        fireEvent.click(await screen.findByText('正文'))

        await waitFor(() => expect(ta.value.startsWith('需求说明')).toBe(true))
    })
})
})

describe('段落锁提示与跳转', () => {
  it('他人锁定段落时展示跳转按钮，点击后光标移到该段起点', async () => {
    // 覆盖默认 mock：返回一条他人持有的第 3 段锁
    server.use(
      http.get('/api/v1/workspaces/:wid/documents/:docId/paragraph-locks', () =>
        HttpResponse.json({
          locks: [
            { document_id: 2, key: 'p3', user_id: 99, username: 'bob', elapsed_seconds: 3 },
          ],
        }),
      ),
    )

    const { container } = renderEditor()
    await screen.findByTestId('doc-paragraph-locks')

    const jump = await screen.findByTestId('para-jump-p3')
    expect(jump).toHaveTextContent('跳转到第 3 段')
    expect(jump).toHaveTextContent('bob')

    fireEvent.click(jump)

    const textarea = container.querySelector('textarea') as HTMLTextAreaElement
    expect(textarea).toBeTruthy()
    // 光标落在第 3 段起点：该偏移之前的段落数是 2
    const before = textarea.value.slice(0, textarea.selectionStart)
    expect(before.split('\n\n').filter((part) => part.trim()).length).toBe(2)
  })
})

describe('草稿发布控件', () => {
  it('草稿显示「发布」按钮，点击后 PATCH status=published 并提示', async () => {
    const bodies: unknown[] = []
    server.use(
      http.patch('/api/v1/workspaces/:wid/documents/:docId', async ({ request }) => {
        bodies.push(await request.json())
        return HttpResponse.json({ ...mockDocuments[0], status: 'published' })
      }),
    )

    const successSpy = vi.spyOn(message, 'success').mockImplementation((() => {}) as never)

    renderEditor()
    const toggle = await screen.findByTestId('doc-publish-toggle')
    // 草稿态：按钮文案为「发布」，标签提示仅自己可见
    expect(toggle).toHaveTextContent(/发\s*布/)
    expect(await screen.findByText('草稿（仅自己可见）')).toBeInTheDocument()

    fireEvent.click(toggle)

    await waitFor(() => expect(bodies.length).toBe(1))
    expect(bodies[0]).toMatchObject({ status: 'published' })
    await waitFor(() =>
      expect(successSpy).toHaveBeenCalledWith('已发布：工作区成员现在可以看到这份文档'),
    )
  })
})

describe('协作者入口（桌面端）', () => {
    it('桌面工具栏可打开协作者弹窗并拉取名单', async () => {
        const listSpy = vi.spyOn(documentsApi, 'listPermissions').mockResolvedValue([])
        renderEditor()

        // 等正文加载完成（编辑器用原生 textarea）
        await waitFor(() => {
            const ta = document.querySelector<HTMLTextAreaElement>('textarea')
            expect(ta?.value.length ?? 0).toBeGreaterThan(0)
        })

        fireEvent.click(screen.getByTestId('doc-collaborators-open'))
        expect(await screen.findByTestId('doc-collaborators-modal')).toBeInTheDocument()
        await waitFor(() => expect(listSpy).toHaveBeenCalledWith(10, 2))
    })
})
