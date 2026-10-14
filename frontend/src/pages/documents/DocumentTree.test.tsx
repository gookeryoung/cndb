/**
 * 文档结构树测试 —— 组树纯函数 + 组件交互（展开导航 / 新建 / 重命名 / 移动 / 删除）.
 */

import { describe, expect, it, vi } from 'vitest'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import { Routes, Route, Outlet, useLocation } from 'react-router-dom'
import { http, HttpResponse } from 'msw'
import DocumentTree, {
    ancestorChain,
    buildDocTree,
    descendantIds,
    planDropMove,
} from './DocumentTree'
import { renderProviders } from '@/test/render-providers'
import { mockDocuments, mockUser, server } from '@/test/msw'
import type { DocumentItem } from '@/api/documents'

// ─────────────── 纯函数 ───────────────

describe('buildDocTree 组树', () => {
    it('按 parent_id 组装层级：根 → 文件夹 → 子项', () => {
        const tree = buildDocTree(mockDocuments)
        expect(tree).toHaveLength(1)
        expect(tree[0].title).toBe('产品文档')
        expect(tree[0].children.map(c => c.title)).toEqual(['需求说明', '会议纪要'])
    })

    it('孤儿节点（父不在列表中）挂到根，不丢失', () => {
        const orphan: DocumentItem = { ...mockDocuments[2], id: 9, parent_id: 404 }
        const tree = buildDocTree([...mockDocuments, orphan])
        const rootTitles = tree.map(n => n.title)
        expect(rootTitles).toContain('会议纪要')
        expect(tree).toHaveLength(2)
    })
})

describe('ancestorChain 祖先链', () => {
    it('返回从根到自身的完整链路', () => {
        const chain = ancestorChain(mockDocuments, 2)
        expect(chain.map(n => n.id)).toEqual([1, 2])
    })

    it('目标不存在时返回空链', () => {
        expect(ancestorChain(mockDocuments, 999)).toEqual([])
    })
})

describe('descendantIds 子孙集合', () => {
    it('含自身与全部子孙（用于移动环检测）', () => {
        const tree = buildDocTree(mockDocuments)
        expect(descendantIds(tree[0]).sort()).toEqual([1, 2, 3])
    })
})

describe('planDropMove 拖拽规划', () => {
    const tree = buildDocTree(mockDocuments)

    it('rel=0 成为文件夹子节点：生成 parent 变更操作', () => {
        // 需求说明(2) 拖入会议纪要(3)：父变更，追加后 sort 仍为 0 无变化
        expect(planDropMove(tree, 2, 3, 0)).toEqual([{ id: 2, parent_id: 3 }])
    })

    it('rel=1 移到目标之后：仅生成发生变化的 sort_order', () => {
        // 需求说明(2) 移到会议纪要(3) 之后：同级顺序对调，两项 sort 均变化
        expect(planDropMove(tree, 2, 3, 1)).toEqual([
            { id: 3, sort_order: 0 },
            { id: 2, sort_order: 1 },
        ])
    })

    it('移到根目录：parent_id 使用 0 约定（null 语义为不更新）', () => {
        const rootDoc: DocumentItem = { ...mockDocuments[1], id: 4, parent_id: null, sort_order: 1 }
        const tree2 = buildDocTree([...mockDocuments, rootDoc])
        // 需求说明(2) 拖到根级散文档(4) 之后：移出文件夹回到根
        expect(planDropMove(tree2, 2, 4, 1)).toEqual([
            { id: 2, parent_id: 0 },
            { id: 2, sort_order: 2 },
        ])
    })

    it('拖到自身或自身子孙：环检测拦截返回 null', () => {
        expect(planDropMove(tree, 1, 1, 0)).toBeNull()
        expect(planDropMove(tree, 1, 2, 0)).toBeNull()
        expect(planDropMove(tree, 1, 3, 0)).toBeNull()
    })

    it('rel=0 但目标非文件夹：拦截返回 null', () => {
        expect(planDropMove(tree, 3, 2, 0)).toBeNull()
    })

    it('落点即当前位置：不产生操作（幂等）', () => {
        // 会议纪要(3) 已在需求说明(2) 之后，原位放置无操作
        expect(planDropMove(tree, 3, 2, 1)).toEqual([])
    })
})

// ─────────────── 组件交互 ───────────────

/** 编辑页路由桩：展示当前 pathname 供导航断言 */
function EditorStub() {
    const loc = useLocation()
    return <div data-testid="doc-editor-stub">{loc.pathname}</div>
}

/** 树宿主：模拟 DocumentsLayout —— 树常驻 + Outlet 承接内容区 */
function TreeHost({ onNavigate }: { onNavigate?: () => void }) {
    return (
        <>
            <DocumentTree onNavigate={onNavigate} />
            <Outlet />
        </>
    )
}

function renderTree(route = '/w/10/documents') {
    // 嵌套路由：树在 /w/:wid 段常驻渲染（路由内取 useParams），内容区经 Outlet 切换
    return renderProviders(
        <Routes>
            <Route path="/w/:wid" element={<TreeHost />}>
                <Route path="documents" element={<span data-testid="doc-list-stub" />} />
                <Route path="documents/:docId" element={<EditorStub />} />
            </Route>
        </Routes>,
        { route, initialAuth: { user: mockUser, token: 'fake-token' } },
    )
}

describe('DocumentTree 组件', () => {
    it('渲染根级文件夹，点击展开后显示子节点，点击文档导航到编辑页', async () => {
        renderTree()

        // 根级文件夹可见（默认折叠）
        expect(await screen.findByTestId('doc-tree-folder-1')).toBeVisible()

        // 点击文件夹标题展开（expandAction=click）
        fireEvent.click(screen.getByTestId('doc-tree-folder-1'))
        await waitFor(() => {
            expect(screen.getByTestId('doc-tree-doc-2')).toBeVisible()
        })

        // 点击文档节点 → 导航到编辑页
        fireEvent.click(screen.getByTestId('doc-tree-doc-2'))
        await waitFor(() => {
            expect(screen.getByTestId('doc-editor-stub')).toHaveTextContent('/w/10/documents/2')
        })
    })

    it('编辑页上下文（?docId 路由）选中态对应当前文档并自动展开祖先链', async () => {
        renderTree('/w/10/documents/2')

        // 祖先链自动展开：子文档直接可见
        await waitFor(() => {
            expect(screen.getByTestId('doc-tree-doc-2')).toBeVisible()
        })
        // 选中节点带 ant-tree-node-selected 类
        expect(
            screen.getByTestId('doc-tree-doc-2').closest('.ant-tree-treenode'),
        ).toHaveClass('ant-tree-treenode-selected')
    })

    it('树内过滤：关键词命中分支保留，未命中节点隐藏', async () => {
        renderTree()

        await screen.findByTestId('doc-tree-folder-1')
        fireEvent.click(screen.getByTestId('doc-tree-folder-1'))
        await waitFor(() => {
            expect(screen.getByTestId('doc-tree-doc-2')).toBeVisible()
        })

        // 过滤"会议"：仅命中的「会议纪要」分支保留
        fireEvent.change(screen.getByTestId('doc-tree-filter'), { target: { value: '会议' } })
        await waitFor(() => {
            expect(screen.queryByTestId('doc-tree-doc-2')).toBeNull()
        })
        expect(screen.getByTestId('doc-tree-folder-1')).toBeVisible()

        // 过滤命中子项时父链保留（分支剪枝语义）
        fireEvent.change(screen.getByTestId('doc-tree-filter'), { target: { value: '需求' } })
        await waitFor(() => {
            expect(screen.getByTestId('doc-tree-doc-2')).toBeVisible()
        })
    })

    it('新建文档：工具栏入口 → 输入标题 → 创建成功并跳转编辑页', async () => {
        renderTree()
        await screen.findByTestId('doc-tree-folder-1')

        fireEvent.click(screen.getByTestId('doc-tree-new-doc'))
        const input = await screen.findByTestId('doc-tree-dialog-input')
        fireEvent.change(input, { target: { value: '新文档' } })
        fireEvent.click(screen.getByRole('button', { name: /创\s*建/ }))

        // POST 成功（msw 返回 id=99）→ 导航到新文档编辑页
        await waitFor(() => {
            expect(screen.getByTestId('doc-editor-stub')).toHaveTextContent('/w/10/documents/99')
        })
    })

    it('今日笔记：POST daily-note 后跳转到该文档编辑页', async () => {
        renderTree()
        await screen.findByTestId('doc-tree-folder-1')

        fireEvent.click(screen.getByTestId('doc-tree-daily-note'))

        // msw 返回今日笔记 id=77 → 导航进入编辑（幂等入口：当日重复点击进入同一篇）
        await waitFor(() => {
            expect(screen.getByTestId('doc-editor-stub')).toHaveTextContent('/w/10/documents/77')
        })
    })

    it('右键文档节点：重命名提交 PATCH title', async () => {
        const bodies: unknown[] = []
        server.use(
            http.patch('/api/v1/workspaces/:wid/documents/:docId', async ({ request }) => {
                bodies.push(await request.json())
                return HttpResponse.json(mockDocuments[1])
            }),
        )
        renderTree()

        await screen.findByTestId('doc-tree-folder-1')
        fireEvent.click(screen.getByTestId('doc-tree-folder-1'))
        await waitFor(() => {
            expect(screen.getByTestId('doc-tree-doc-2')).toBeVisible()
        })

        // 右键文档节点 → 菜单出现
        fireEvent.contextMenu(screen.getByTestId('doc-tree-doc-2'))
        fireEvent.click(await screen.findByText('重命名'))

        // 弹窗回填原标题，改为新标题提交
        const input = await screen.findByTestId('doc-tree-dialog-input')
        expect(input).toHaveValue('需求说明')
        fireEvent.change(input, { target: { value: '需求说明-v2' } })
        fireEvent.click(screen.getByRole('button', { name: /保\s*存/ }))

        await waitFor(() => {
            expect(bodies).toEqual([{ title: '需求说明-v2' }])
        })
    })

    it('右键文件夹：移动到根目录提交 PATCH parent_id=0（移回根的约定）', async () => {
        const bodies: unknown[] = []
        server.use(
            http.patch('/api/v1/workspaces/:wid/documents/:docId', async ({ request }) => {
                bodies.push(await request.json())
                return HttpResponse.json(mockDocuments[2])
            }),
        )
        renderTree()

        await screen.findByTestId('doc-tree-folder-1')
        fireEvent.contextMenu(screen.getByTestId('doc-tree-folder-1'))
        fireEvent.click(await screen.findByText('移动到…'))

        // 弹窗内 TreeSelect 默认值 = 当前 parent（根 → 0），直接确认即移回根
        await screen.findByText('移动「产品文档」到…')
        fireEvent.click(screen.getByRole('button', { name: /^移\s*动$/ }))

        await waitFor(() => {
            expect(bodies).toEqual([{ parent_id: 0 }])
        })
    })

    it('右键节点：删除弹确认框，确认后调用 DELETE', async () => {
        const deleted: string[] = []
        server.use(
            http.delete('/api/v1/workspaces/:wid/documents/:docId', ({ params }) => {
                deleted.push(String(params.docId))
                return HttpResponse.json({ id: 1, deleted: true })
            }),
        )
        renderTree()

        const folder = await screen.findByTestId('doc-tree-folder-1')
        fireEvent.contextMenu(folder)
        // 菜单项文本无插空（antd 仅对 Button 两字文本加空格）
        fireEvent.click(await screen.findByText('删除'))

        // Modal.confirm 弹出：确认删除（Button 两字文本渲染为「删 除」）
        const okBtn = await screen.findByRole('button', { name: /^删\s*除$/ })
        fireEvent.click(okBtn)

        await waitFor(() => {
            expect(deleted).toEqual(['1'])
        })
    })

    it('空树渲染 Empty 引导', async () => {
        server.use(
            http.get('/api/v1/workspaces/:wid/documents/tree', () =>
                HttpResponse.json({ items: [] })),
        )
        renderTree()

        expect(await screen.findByText('暂无文档')).toBeVisible()
    })

    it('无效工作区（wid 非数字）不渲染', () => {
        const { container } = renderProviders(
            <Routes>
                <Route path="/w/:wid/documents" element={<DocumentTree />} />
            </Routes>,
            { route: '/w/abc/documents', initialAuth: { user: mockUser, token: 'fake-token' } },
        )
        expect(container.querySelector('[data-testid="document-tree"]')).toBeNull()
    })

    it('onNavigate 回调：点击文档导航后触发（移动端抽屉收起）', async () => {
        const onNavigate = vi.fn()
        renderProviders(
            <Routes>
                <Route path="/w/:wid" element={<TreeHost onNavigate={onNavigate} />}>
                    <Route path="documents" element={<span data-testid="doc-list-stub" />} />
                    <Route path="documents/:docId" element={<EditorStub />} />
                </Route>
            </Routes>,
            { route: '/w/10/documents', initialAuth: { user: mockUser, token: 'fake-token' } },
        )

        await screen.findByTestId('doc-tree-folder-1')
        fireEvent.click(screen.getByTestId('doc-tree-folder-1'))
        await waitFor(() => {
            expect(screen.getByTestId('doc-tree-doc-2')).toBeVisible()
        })
        fireEvent.click(screen.getByTestId('doc-tree-doc-2'))
        await waitFor(() => {
            expect(onNavigate).toHaveBeenCalled()
        })
    })
})

describe('DocumentTree 拖拽整理', () => {
    /** 拖拽 fixture：根级文件夹 A（含 doc1 与子文件夹 B）+ 根级散文档 doc2 */
    const dragDocs: DocumentItem[] = [
        { ...mockDocuments[0], id: 1, title: 'A' },
        { ...mockDocuments[1], id: 2, title: 'doc1' },
        { ...mockDocuments[2], id: 3, title: 'B' },
        { ...mockDocuments[1], id: 4, title: 'doc2', parent_id: null, sort_order: 1 },
    ]

    /** 取树节点标题对应的可拖拽 selector 元素 */
    const wrapperOf = (testid: string) =>
        screen.getByTestId(testid).closest('.ant-tree-node-content-wrapper') as HTMLElement

    it('拖 doc2 到子文件夹 B 之后：提交移动与排序两次 PATCH', async () => {
        const patches: Array<{ id: string; body: unknown }> = []
        server.use(
            http.get('/api/v1/workspaces/:wid/documents/tree', () =>
                HttpResponse.json({ items: dragDocs })),
            http.patch('/api/v1/workspaces/:wid/documents/:docId', async ({ params, request }) => {
                patches.push({ id: String(params.docId), body: await request.json() })
                return HttpResponse.json(dragDocs[3])
            }),
        )
        renderTree()

        // 展开 A 使子文件夹 B 可见
        fireEvent.click(await screen.findByTestId('doc-tree-folder-1'))
        await waitFor(() => {
            expect(screen.getByTestId('doc-tree-folder-3')).toBeVisible()
        })

        // HTML5 拖拽事件序列：拖起 doc2 → 移入 B 上方 → 释放在 B 上
        // （jsdom 无法测量真实缩进 indent=0，rc-tree 回退为「放入目标内部」语义）
        fireEvent.dragStart(wrapperOf('doc-tree-doc-4'))
        fireEvent.dragEnter(wrapperOf('doc-tree-folder-3'))
        fireEvent.dragOver(wrapperOf('doc-tree-folder-3'))
        fireEvent.drop(wrapperOf('doc-tree-folder-3'))
        fireEvent.dragEnd(wrapperOf('doc-tree-doc-4'))

        // 规划结果：doc2 从根移入 B（parent null→3）且成为其唯一子项（sort_order 0）
        await waitFor(() => {
            expect(patches).toEqual([
                { id: '4', body: { parent_id: 3 } },
                { id: '4', body: { sort_order: 0 } },
            ])
        })
    })
})
