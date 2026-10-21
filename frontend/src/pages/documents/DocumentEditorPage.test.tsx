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

/** 切到「源码」模式：既有断言基于 textarea（实时预览用 CodeMirror，无法直接读写 value） */
async function enterSourceMode() {
    fireEvent.click(await screen.findByText('源码'))
    return (await screen.findByPlaceholderText('输入 Markdown 内容…')) as HTMLTextAreaElement
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
        const ta = await enterSourceMode()
        await waitFor(() => expect(ta.value).toContain('需求说明'))

        // 打开插入弹窗
        fireEvent.click(screen.getByRole('button', { name: /插入表格引用/ }))
        expect(await screen.findByText('选择要引用的数据表')).toBeInTheDocument()

        // 选择「客户表」（下拉选项）：等表列表 query 就绪后打开下拉
        const combo = await screen.findByRole('combobox')
        fireEvent.mouseDown(combo)
        fireEvent.click(await screen.findByText('客户表'))

        // 确认插入（「插入」按钮）
        fireEvent.click(screen.getByRole('button', { name: /^插\s*入$/ }))

        // 编辑区出现占位符且独占首段（光标在文首时插到最前，随后空行分隔正文）
        await waitFor(() => {
            expect(ta.value.startsWith('{{table:100}}')).toBe(true)
        })

        // 切到查看模式：预览侧动态渲染数据表（行数据出现即视为渲染成功；表名与 Select 选项重名不唯一）
        fireEvent.click(within(screen.getByTestId('doc-mode-switch')).getByText('查看'))
        // 数据行需「表详情 → 行数据」两次串行请求后才渲染；CI 高负载下默认 1s 的 findBy
        // 等待偶发超时（曾整例顶到 10s 上限）。放宽等待窗口并给整例留出余量，消除抖动。
        expect(await screen.findByText('张三', {}, { timeout: 8000 })).toBeInTheDocument()
        expect(screen.getByText('李四')).toBeInTheDocument()
    }, 30_000)

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

        // 预览侧锚点在切到查看模式后才渲染（草稿文档默认编辑模式）
        expect(document.getElementById('doc-h-目标')).toBeNull()

        // 点击「目标」：切到查看模式并滚动定位到对应锚点
        fireEvent.click(screen.getByTestId('doc-outline-item-2'))
        await waitFor(() => {
            expect(document.getElementById('doc-h-目标')).toBeInTheDocument()
            expect(scrollIntoView).toHaveBeenCalled()
        })
    })

    it('编辑输入实时更新大纲（未保存也生效）', async () => {
        renderEditor()
        expect(await screen.findByRole('button', { name: /大纲\s*\(4\)/ })).toBeInTheDocument()

        const ta = await enterSourceMode()
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
        // 预览中才渲染 wikilink：先切到查看模式
        await screen.findByTestId('doc-mode-switch')
        fireEvent.click(within(screen.getByTestId('doc-mode-switch')).getByText('查看'))

        const link = await screen.findByTestId('doc-wikilink')
        expect(link).toHaveTextContent('客户需求')

        fireEvent.click(link)
        await waitFor(() => {
            expect(screen.getByTestId('editor-location')).toHaveTextContent('/w/10/documents/5')
        })
    })

    it('双链目标不存在：提示未找到且不跳转', async () => {
        const warningSpy = vi
            .spyOn(message, 'warning')
            .mockImplementation((() => {}) as unknown as typeof message.warning)
        // 树中不含「客户需求」标题的文档
        server.use(
            http.get('/api/v1/workspaces/:wid/documents/tree', () =>
                HttpResponse.json({ items: mockDocuments })),
        )
        renderEditorWithProbe()
        await screen.findByTestId('doc-mode-switch')
        fireEvent.click(within(screen.getByTestId('doc-mode-switch')).getByText('查看'))

        fireEvent.click(await screen.findByTestId('doc-wikilink'))
        await waitFor(() => {
            expect(warningSpy).toHaveBeenCalledWith(expect.stringContaining('未找到文档'))
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

    it('无直编资格时提交转为修改申请：正文不落库，提示待审核', async () => {
        const submitBodies: Record<string, unknown>[] = []
        server.use(
            http.get('/api/v1/workspaces/:wid/documents/:docId/content', () =>
                HttpResponse.json({
                    ...mockDocuments[1],
                    content: '# 需求说明\n\n正文段落。\n',
                    version_number: 1,
                    draft: null,
                    write_mode: 'change_request',
                })),
            http.post('/api/v1/workspaces/:wid/documents/:docId/submit', async ({ request }) => {
                submitBodies.push(await request.json() as Record<string, unknown>)
                return HttpResponse.json(
                    {
                        mode: 'change_request',
                        message: '已提交修改申请 #7，审核通过后生效',
                        change_request: { id: 7, status: 'open', document_id: 2, title: '修改文档《需求说明》' },
                    },
                    { status: 202 },
                )
            }),
        )
        renderEditor()
        const ta = await enterSourceMode()
        await waitFor(() => expect(ta.value).toContain('需求说明'))
        fireEvent.change(ta, { target: { value: '# 需求说明\n\n修改后的正文。\n' } })

        fireEvent.click(screen.getByTestId('doc-submit-btn'))
        // 修改申请模式下弹窗文案为「提交审核」
        fireEvent.click(await screen.findByRole('button', { name: /提交审核/ }))

        expect(await screen.findByTestId('doc-cr-notice')).toHaveTextContent('已提交修改申请 #7')
        // 提交携带正文、变更说明与基准版本号，供后端做段落级合并 / 基准漂移判断
        expect(submitBodies[0]).toMatchObject({
            content: '# 需求说明\n\n修改后的正文。\n',
            change_summary: '',
            base_version_number: 1,
        })
        // 修改申请待审：回到查看模式展示当前发布版
        expect(await screen.findByTestId('doc-view-mode')).toBeInTheDocument()
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

    it('窄屏用「查看 / 编辑」模式切换，单面板无左右分栏', async () => {
        renderEditor()
        await enterSourceMode()

        // 草稿文档默认编辑；窄屏不再有独立的分屏页签
        expect(screen.queryByTestId('doc-mobile-pane-switch')).toBeNull()
        expect(document.querySelector('.ant-splitter')).toBeNull()
        expect(screen.getByTestId('doc-editor-mode-switch')).toBeInTheDocument()
        expect(document.querySelector('.doc-md-preview')).toBeNull()

        fireEvent.click(within(screen.getByTestId('doc-mode-switch')).getByText('查看'))
        await waitFor(() => expect(document.querySelector('.doc-md-preview')).toBeInTheDocument())
        expect(screen.queryByTestId('doc-editor-mode-switch')).toBeNull()

        fireEvent.click(within(screen.getByTestId('doc-mode-switch')).getByText('编辑'))
        expect(await screen.findByTestId('doc-editor-mode-switch')).toBeInTheDocument()
    })

    it('桌面端同样使用模式切换，不再左右分栏', async () => {
        responsiveState = {
            deviceType: 'desktop', isMobile: false, isTablet: false, isDesktop: true,
            width: 1280, height: 800,
        }
        renderEditor()
        await enterSourceMode()

        expect(screen.queryByTestId('doc-mobile-pane-switch')).toBeNull()
        expect(document.querySelector('.ant-splitter')).toBeNull()
        expect(screen.getByTestId('doc-mode-switch')).toBeInTheDocument()
    })

    it('大纲点击锚点时先切到查看模式再定位', async () => {
        const scrollIntoView = vi.fn()
        Element.prototype.scrollIntoView = scrollIntoView as unknown as typeof Element.prototype.scrollIntoView
        renderEditor()
        await enterSourceMode()

        // 打开大纲抽屉并点击一个标题
        fireEvent.click(screen.getByText(/大\s*纲/))
        fireEvent.click(await screen.findByText('需求说明', { selector: '.ant-drawer *' }))

        await waitFor(() => expect(document.querySelector('.doc-md-preview')).toBeInTheDocument())
        await waitFor(() => expect(scrollIntoView).toHaveBeenCalled())
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
        const ta = await enterSourceMode()
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
        const ta = await enterSourceMode()

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
        const ta = await enterSourceMode()
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
        const ta = await enterSourceMode()

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
        const ta = await enterSourceMode()
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
        const ta = await enterSourceMode()
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

    it('顶部不再有「查找」按钮；Ctrl+F 打开查找条后区分大小写开关影响匹配数', async () => {
        renderEditor()
        const ta = await enterSourceMode()

        // 查找入口收敛到快捷键（顶栏「查找」按钮已移除）
        expect(screen.queryByTestId('doc-find-open')).toBeNull()
        fireEvent.keyDown(ta, { key: 'f', ctrlKey: true })
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
        const ta = await enterSourceMode()
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
        const ta = await enterSourceMode()
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
        const ta = await enterSourceMode()
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
        const ta = await enterSourceMode()

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
        const ta = await enterSourceMode()
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
        const ta = await enterSourceMode()
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
        await enterSourceMode()

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
        const ta = await enterSourceMode()
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
        const ta = await enterSourceMode()
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
        const ta = await enterSourceMode()
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

  it('已发布文档不提供「转为草稿」入口', async () => {
    server.use(
      http.get('/api/v1/workspaces/:wid/documents/:docId/content', () =>
        HttpResponse.json({
          ...mockDocuments[1],
          status: 'published',
          content: '# 已发布文档\n\n正文。\n',
          version_number: 3,
          draft: null,
          write_mode: 'direct',
        })),
    )

    renderEditor()

    expect(await screen.findByTestId('doc-view-mode')).toBeInTheDocument()
    expect(screen.queryByTestId('doc-publish-toggle')).toBeNull()
    expect(screen.queryByText('转为草稿')).toBeNull()
  })
})

describe('DocumentEditorPage 查看 / 编辑模式与草稿提交', () => {
    beforeEach(() => {
        server.resetHandlers()
    })

    it('已发布文档且无草稿：默认进入查看模式', async () => {
        server.use(
            http.get('/api/v1/workspaces/:wid/documents/:docId/content', () =>
                HttpResponse.json({
                    ...mockDocuments[1],
                    status: 'published',
                    content: '# 已发布文档\n\n正文。\n',
                    version_number: 3,
                    draft: null,
                    write_mode: 'direct',
                })),
        )
        renderEditor()

        expect(await screen.findByTestId('doc-view-mode')).toBeInTheDocument()
        expect(document.querySelector('.doc-md-preview')).toBeInTheDocument()
        expect(screen.queryByTestId('doc-editor-mode-switch')).toBeNull()
        // 无修改：保存草稿与提交修改均禁用
        expect(screen.getByTestId('doc-save-btn')).toBeDisabled()
        expect(screen.getByTestId('doc-submit-btn')).toBeDisabled()
    })

    it('本人有草稿：默认进入编辑模式并载入草稿内容', async () => {
        server.use(
            http.get('/api/v1/workspaces/:wid/documents/:docId/content', () =>
                HttpResponse.json({
                    ...mockDocuments[1],
                    status: 'published',
                    content: '# 已发布标题\n\n发布版正文。\n',
                    version_number: 2,
                    write_mode: 'direct',
                    draft: {
                        content: '# 草稿标题\n\n草稿正文。\n',
                        content_size: 18,
                        base_version_number: 2,
                        current_version_number: 2,
                        stale: false,
                        updated_at: '2026-02-01T00:00:00Z',
                    },
                })),
        )
        renderEditor()

        expect(await screen.findByTestId('doc-draft-tag')).toHaveTextContent('草稿待提交')
        const ta = await enterSourceMode()
        await waitFor(() => expect(ta.value).toContain('草稿正文'))
        // 草稿与最新版本不同 → 允许保存 / 提交
        expect(screen.getByTestId('doc-save-btn')).toBeEnabled()
        expect(screen.getByTestId('doc-submit-btn')).toBeEnabled()
    })

    it('保存草稿：只调用 /draft，不生成新版本', async () => {
        const draftBodies: Record<string, unknown>[] = []
        let submitCalls = 0
        server.use(
            http.put('/api/v1/workspaces/:wid/documents/:docId/draft', async ({ request }) => {
                const body = await request.json() as Record<string, unknown>
                draftBodies.push(body)
                const content = String(body.content ?? '')
                return HttpResponse.json({
                    draft: {
                        content,
                        content_size: content.length,
                        base_version_number: 1,
                        current_version_number: 1,
                        stale: false,
                        updated_at: '2026-02-01T00:00:00Z',
                    },
                })
            }),
            http.post('/api/v1/workspaces/:wid/documents/:docId/submit', () => {
                submitCalls += 1
                return HttpResponse.json({ mode: 'direct', message: 'x', content: '', version_number: 2 })
            }),
        )
        renderEditor()
        const ta = await enterSourceMode()
        await waitFor(() => expect(ta.value).toContain('需求说明'))
        fireEvent.change(ta, { target: { value: '# 需求说明\n\n草稿内容。\n' } })

        fireEvent.click(screen.getByTestId('doc-save-btn'))

        await waitFor(() => expect(draftBodies).toHaveLength(1))
        expect(draftBodies[0]).toMatchObject({
            content: '# 需求说明\n\n草稿内容。\n',
            base_version_number: 1,
        })
        expect(submitCalls).toBe(0)
        expect(await screen.findByTestId('doc-draft-tag')).toBeInTheDocument()
        // 保存后无未保存提示（仍是待提交草稿）
        expect(screen.queryByTestId('doc-unsaved-hint')).toBeNull()
    })

    it('切到查看模式：未保存改动自动落草稿', async () => {
        let draftCalls = 0
        server.use(
            http.put('/api/v1/workspaces/:wid/documents/:docId/draft', () => {
                draftCalls += 1
                return HttpResponse.json({ draft: null })
            }),
        )
        renderEditor()
        const ta = await enterSourceMode()
        await waitFor(() => expect(ta.value).toContain('需求说明'))
        fireEvent.change(ta, { target: { value: '# 需求说明\n\n未提交改动。\n' } })

        fireEvent.click(within(screen.getByTestId('doc-mode-switch')).getByText('查看'))

        await waitFor(() => expect(draftCalls).toBe(1))
        expect(await screen.findByTestId('doc-view-mode')).toBeInTheDocument()
    })

    it('提交修改：先弹窗确认，成功后生成新版本并回到查看模式', async () => {
        const submitBodies: Record<string, unknown>[] = []
        server.use(
            http.post('/api/v1/workspaces/:wid/documents/:docId/submit', async ({ request }) => {
                submitBodies.push(await request.json() as Record<string, unknown>)
                return HttpResponse.json({
                    mode: 'direct',
                    message: '已提交并生成 v2',
                    content: '# 需求说明\n\n提交后的正文。\n',
                    version_number: 2,
                })
            }),
        )
        renderEditor()
        const ta = await enterSourceMode()
        await waitFor(() => expect(ta.value).toContain('需求说明'))
        fireEvent.change(ta, { target: { value: '# 需求说明\n\n提交后的正文。\n' } })

        fireEvent.click(screen.getByTestId('doc-submit-btn'))
        // 弹窗出现：填写变更说明后确认提交
        expect(await screen.findByTestId('doc-submit-summary')).toBeInTheDocument()
        fireEvent.change(screen.getByTestId('doc-submit-summary'), { target: { value: '更新正文' } })
        fireEvent.click(screen.getByRole('button', { name: /确认提交/ }))

        await waitFor(() => expect(submitBodies).toHaveLength(1))
        expect(submitBodies[0]).toMatchObject({
            content: '# 需求说明\n\n提交后的正文。\n',
            change_summary: '更新正文',
            base_version_number: 1,
        })
        // 提交成功后回到查看模式，且与最新版本一致 → 按钮重新禁用
        expect(await screen.findByTestId('doc-view-mode')).toBeInTheDocument()
        expect(screen.getByTestId('doc-submit-btn')).toBeDisabled()
    })

    it('无修改时保存 / 提交按钮禁用，不会产生请求', async () => {
        let draftCalls = 0
        let submitCalls = 0
        server.use(
            http.put('/api/v1/workspaces/:wid/documents/:docId/draft', () => {
                draftCalls += 1
                return HttpResponse.json({ draft: null })
            }),
            http.post('/api/v1/workspaces/:wid/documents/:docId/submit', () => {
                submitCalls += 1
                return HttpResponse.json({ mode: 'direct', message: 'x', content: '', version_number: 2 })
            }),
        )
        renderEditor()
        await enterSourceMode()
        expect(screen.getByTestId('doc-save-btn')).toBeDisabled()
        expect(screen.getByTestId('doc-submit-btn')).toBeDisabled()

        fireEvent.click(screen.getByTestId('doc-save-btn'))
        fireEvent.click(screen.getByTestId('doc-submit-btn'))
        await new Promise(r => setTimeout(r, 100))
        expect(draftCalls).toBe(0)
        expect(submitCalls).toBe(0)
    })
})
