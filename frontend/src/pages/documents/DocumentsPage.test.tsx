/**
 * 文档管理页测试 —— 顶层系列卡片总览 + 系列详情视图：
 * 纯函数聚合（buildSeriesStats）+ 顶层卡片网格渲染与导航 + 系列级操作（重命名/移动/删除）。
 * （需求 0065：页面内左树已移除、排序/筛选控件移入侧栏，正文系列卡片与列表保留。）
 */

import { describe, expect, it, vi, afterEach, beforeEach } from 'vitest'
import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { Routes, Route } from 'react-router-dom'
import { message } from 'antd'
import { http, HttpResponse } from 'msw'
import DocumentsPage, { buildSeriesStats } from './DocumentsPage'
import { renderProviders } from '@/test/render-providers'
import { mockDocuments, mockUser, server } from '@/test/msw'
import type { DocumentItem } from '@/api/documents'
import type { ResponsiveState } from '@/hooks/useResponsive'

// 可控 useResponsive mock：默认桌面端，移动端用例在内部切换（验证工具栏收敛）
let responsiveState: ResponsiveState = {
  deviceType: 'desktop', isMobile: false, isTablet: false, isDesktop: true,
  width: 1280, height: 800,
}
vi.mock('@/hooks/useResponsive', async () => {
  const actual = await vi.importActual<typeof import('@/hooks/useResponsive')>('@/hooks/useResponsive')
  return { ...actual, useResponsive: () => responsiveState }
})

describe('buildSeriesStats 纯函数', () => {
  it('空列表返回空数组', () => {
    expect(buildSeriesStats([])).toEqual([])
  })

  it('顶层文件夹聚合递归统计：文档数/子文件夹数/状态分布/最近更新', () => {
    const [series] = buildSeriesStats(mockDocuments)
    expect(series.folder.id).toBe(1)
    expect(series.folder.title).toBe('产品文档')
    expect(series.docCount).toBe(1) // 需求说明
    expect(series.subFolderCount).toBe(1) // 会议纪要
    expect(series.tagCount).toBe(0)
    expect(series.statusCounts).toEqual({ draft: 1 })
    expect(series.latestUpdate).toBe('2026-01-02T00:00:00Z')
  })

  it('顶层散文档与深层子孙均计入对应统计', () => {
    const deep: DocumentItem[] = [
      { ...mockDocuments[0], id: 1 }, // 根文件夹 A
      { ...mockDocuments[1], id: 2, parent_id: 1, status: 'published', tag_ids: [7, 8] }, // A 下文档
      { ...mockDocuments[2], id: 3, parent_id: 2 }, // A 下文件夹（嵌套）
      { ...mockDocuments[1], id: 4, parent_id: 3, status: 'archived', tag_ids: [8, 9], updated_at: '2026-03-01T00:00:00Z' }, // 深层文档
      { ...mockDocuments[1], id: 5, parent_id: null }, // 根级散文档（不进系列）
    ]
    const series = buildSeriesStats(deep)
    expect(series).toHaveLength(1) // 仅根文件夹 A 成系列
    expect(series[0].docCount).toBe(2) // id=2 与深层 id=4
    expect(series[0].subFolderCount).toBe(1) // id=3
    expect(series[0].tagCount).toBe(3) // 7/8/9 去重
    expect(series[0].statusCounts).toEqual({ published: 1, archived: 1 })
    expect(series[0].latestUpdate).toBe('2026-03-01T00:00:00Z')
  })
})

describe('DocumentsPage 顶层系列卡片总览', () => {
  it('顶层渲染系列卡片（统计齐全），不渲染 Empty', async () => {
    renderProviders(
      <Routes>
        <Route path="/w/:wid/documents" element={<DocumentsPage />} />
      </Routes>,
      { route: '/w/10/documents', initialAuth: { user: mockUser, token: 'fake-token' } },
    )

    const card = await screen.findByTestId('doc-series-card-1')
    expect(card).toBeVisible()
    expect(screen.getByText('产品文档')).toBeInTheDocument()
    expect(screen.getByText('1 篇文档')).toBeInTheDocument()
    expect(screen.getByText('1 个子文件夹')).toBeInTheDocument()
    expect(screen.getByText('草稿 1')).toBeInTheDocument()
    // 树中「需求说明」为子级文档，不进顶层列表（mock 无根级散文档）
    expect(screen.queryByText('需求说明')).toBeNull()
  })

  it('点击系列卡片进入文件夹：列表展示子项', async () => {
    renderProviders(
      <Routes>
        <Route path="/w/:wid/documents" element={<DocumentsPage />} />
      </Routes>,
      { route: '/w/10/documents', initialAuth: { user: mockUser, token: 'fake-token' } },
    )

    fireEvent.click(await screen.findByTestId('doc-series-card-1'))

    // 子级列表渲染（list 端点按 parent_id=1 过滤）
    expect(await screen.findByText('需求说明')).toBeInTheDocument()
    expect(screen.getByText('会议纪要')).toBeInTheDocument()
    // 系列卡片网格退场
    expect(screen.queryByTestId('doc-series-card-1')).toBeNull()
  })
})

describe('DocumentsPage 系列详情视图', () => {
  function renderPage() {
    return renderProviders(
      <Routes>
        <Route path="/w/:wid/documents" element={<DocumentsPage />} />
      </Routes>,
      { route: '/w/10/documents', initialAuth: { user: mockUser, token: 'fake-token' } },
    )
  }

  /** 进入「产品文档」系列详情 */
  async function enterSeries() {
    fireEvent.click(await screen.findByTestId('doc-series-card-1'))
    await screen.findByTestId('doc-series-detail')
  }

  it('系列详情头部：名称 + 递归统计 + 系列级操作', async () => {
    renderPage()
    await enterSeries()

    const detail = screen.getByTestId('doc-series-detail')
    expect(detail).toHaveTextContent('产品文档')
    expect(detail).toHaveTextContent('1 篇文档')
    expect(detail).toHaveTextContent('1 个子文件夹')
    expect(detail).toHaveTextContent('草稿 1')
    expect(screen.getByTestId('doc-series-rename')).toBeVisible()
    expect(screen.getByTestId('doc-series-move')).toBeVisible()
    expect(screen.getByTestId('doc-series-delete')).toBeVisible()
  })

  it('系列重命名：弹窗回填原名，提交 PATCH title', async () => {
    const bodies: unknown[] = []
    server.use(
      http.patch('/api/v1/workspaces/:wid/documents/:docId', async ({ request }) => {
        bodies.push(await request.json())
        return HttpResponse.json(mockDocuments[0])
      }),
    )
    renderPage()
    await enterSeries()

    fireEvent.click(screen.getByTestId('doc-series-rename'))
    const input = await screen.findByTestId('doc-series-rename-input')
    expect(input).toHaveValue('产品文档')
    fireEvent.change(input, { target: { value: '产品设计' } })
    fireEvent.click(screen.getByRole('button', { name: /保\s*存/ }))

    await waitFor(() => {
      expect(bodies).toEqual([{ title: '产品设计' }])
    })
  })

  it('系列移动：默认目标为当前父级，改选根目录提交 PATCH parent_id=0', async () => {
    const patches: Array<{ id: string; body: unknown }> = []
    server.use(
      http.patch('/api/v1/workspaces/:wid/documents/:docId', async ({ params, request }) => {
        patches.push({ id: String(params.docId), body: await request.json() })
        return HttpResponse.json(mockDocuments[0])
      }),
    )
    renderPage()
    await enterSeries()

    fireEvent.click(screen.getByTestId('doc-series-move'))
    // 弹窗打开，TreeSelect 默认值 = 当前 parent（根级文件夹 → 0），直接确认即移回根
    await screen.findByText('移动系列「产品文档」到…')
    fireEvent.click(screen.getByRole('button', { name: /^移\s*动$/ }))

    await waitFor(() => {
      expect(patches).toEqual([{ id: '1', body: { parent_id: 0 } }])
    })
  })

  it('删除当前系列：确认后调用 DELETE 并回退总览', async () => {
    const deleted: string[] = []
    server.use(
      http.delete('/api/v1/workspaces/:wid/documents/:docId', ({ params }) => {
        deleted.push(String(params.docId))
        return HttpResponse.json({ id: 1, deleted: true })
      }),
    )
    renderPage()
    await enterSeries()

    fireEvent.click(screen.getByTestId('doc-series-delete'))
    // Popconfirm 确认（Button 两字文本渲染为「删 除」）
    fireEvent.click(await screen.findByRole('button', { name: /^删\s*除$/ }))

    await waitFor(() => {
      expect(deleted).toEqual(['1'])
    })
    // 当前层级已删，回退总览：系列网格（刷新后仍由 tree 数据驱动）重新出现
    await waitFor(() => {
      expect(screen.getByTestId('doc-series-grid')).toBeInTheDocument()
    })
  })
})

describe('DocumentsPage 回收站', () => {
  function renderPage() {
    return renderProviders(
      <Routes>
        <Route path="/w/:wid/documents" element={<DocumentsPage />} />
      </Routes>,
      { route: '/w/10/documents', initialAuth: { user: mockUser, token: 'fake-token' } },
    )
  }

  it('打开回收站抽屉：列出租户内软删除文档并可恢复', async () => {
    const restored: string[] = []
    server.use(
      http.post('/api/v1/workspaces/:wid/documents/:docId/restore', ({ params }) => {
        restored.push(String(params.docId))
        return HttpResponse.json({ ...mockDocuments[1], restored_count: 1, reparented_to_root: false })
      }),
    )
    renderPage()
    await screen.findByTestId('doc-trash-open')

    fireEvent.click(screen.getByTestId('doc-trash-open'))
    const item = await screen.findByTestId('doc-trash-item-2')
    expect(item).toHaveTextContent('需求说明')
    expect(item).toHaveTextContent('删除于')

    fireEvent.click(screen.getByTestId('doc-trash-restore-2'))
    await waitFor(() => {
      expect(restored).toEqual(['2'])
    })
  })

  it('彻底删除：Popconfirm 确认后调用 purge', async () => {
    const purged: string[] = []
    server.use(
      http.delete('/api/v1/workspaces/:wid/documents/:docId/purge', ({ params }) => {
        purged.push(String(params.docId))
        return HttpResponse.json({ id: 2, purged: true, purged_count: 1, files_removed: 0, detached: 0 })
      }),
    )
    renderPage()
    await screen.findByTestId('doc-trash-open')

    fireEvent.click(screen.getByTestId('doc-trash-open'))
    fireEvent.click(await screen.findByTestId('doc-trash-purge-2'))
    const pop = await screen.findByRole('tooltip')
    fireEvent.click(within(pop).getByRole('button', { name: '彻底删除' }))

    await waitFor(() => {
      expect(purged).toEqual(['2'])
    })
  })

  it('回收站为空时展示空态', async () => {
    server.use(
      http.get('/api/v1/workspaces/:wid/documents/trash', () =>
        HttpResponse.json({ items: [], total: 0 })),
    )
    renderPage()
    await screen.findByTestId('doc-trash-open')

    fireEvent.click(screen.getByTestId('doc-trash-open'))
    expect(await screen.findByText('回收站为空')).toBeInTheDocument()
  })

describe('DocumentsPage 排序与 URL 状态', () => {
    function renderPage(route = '/w/10/documents') {
        return renderProviders(
            <Routes>
                <Route path="/w/:wid/documents" element={<DocumentsPage />} />
            </Routes>,
            { route, initialAuth: { user: mockUser, token: 'fake-token' } },
        )
    }

    it('?order= 深链：list 请求携带 order 参数（排序控件在侧栏，写 URL）', async () => {
        const orders: string[] = []
        server.use(
            http.get('/api/v1/workspaces/10/documents', ({ request }) => {
                orders.push(new URL(request.url).searchParams.get('order') ?? 'sort')
                return HttpResponse.json({ items: [], total: 0 })
            }),
        )
        renderPage('/w/10/documents?parent=1&order=updated')
        await screen.findByTestId('doc-series-detail')
        await waitFor(() => expect(orders[orders.length - 1]).toBe('updated'))
    })

    it('?parent= 深链：直接进入该文件夹（顶栏出现「上一级」）', async () => {
        renderPage('/w/10/documents?parent=1')

        expect(await screen.findByRole('button', { name: /上一级/ })).toBeInTheDocument()
        // 文件夹标题出现在面包屑中（产品文档；页面标题与卡片也会出现该文本，故用 findAllByText）
        expect((await screen.findAllByText('产品文档')).length).toBeGreaterThan(0)
    })
})

describe('DocumentsPage 批量操作', () => {
    function renderPage(route = '/w/10/documents?parent=1') {
        return renderProviders(
            <Routes>
                <Route path="/w/:wid/documents" element={<DocumentsPage />} />
            </Routes>,
            { route, initialAuth: { user: mockUser, token: 'fake-token' } },
        )
    }

    it('勾选后出现批量栏；全选与取消选择可用', async () => {
        renderPage()
        // 文件夹内有两个子项（说明文档 + 需求文件夹）
        await screen.findByTestId('doc-select-2')

        expect(screen.queryByTestId('doc-batch-bar')).toBeNull()

        fireEvent.click(screen.getByTestId('doc-select-2'))
        expect(await screen.findByTestId('doc-batch-bar')).toHaveTextContent('已选 1 项')

        const total = screen.getAllByTestId(/^doc-select-/).length
        fireEvent.click(screen.getByTestId('doc-batch-select-all'))
        await waitFor(() => expect(screen.getByTestId('doc-batch-bar')).toHaveTextContent(`已选 ${total} 项`))

        fireEvent.click(screen.getByTestId('doc-batch-clear'))
        await waitFor(() => expect(screen.queryByTestId('doc-batch-bar')).toBeNull())
    })

    it('批量删除：确认后提交 action=delete 与所选 ids，并提示结果', async () => {
        const successSpy = vi.spyOn(message, 'success')
        const bodies: unknown[] = []
        server.use(
            http.post('/api/v1/workspaces/10/documents/batch', async ({ request }) => {
                bodies.push(await request.json())
                return HttpResponse.json({ action: 'delete', updated: 1, skipped: [] })
            }),
        )
        renderPage()
        await screen.findByTestId('doc-select-2')

        fireEvent.click(screen.getByTestId('doc-select-2'))
        fireEvent.click(await screen.findByTestId('doc-batch-delete'))
        // Popconfirm 确认
        // Popconfirm 确认（antd 两字按钮文本渲染为「删 除」）
        fireEvent.click(await screen.findByRole('button', { name: /^删\s*除$/ }))

        await waitFor(() => expect(bodies).toHaveLength(1))
        expect(bodies[0]).toMatchObject({ action: 'delete', ids: [2] })
        expect(successSpy).toHaveBeenCalledWith('已删除 1 项')
        await waitFor(() => expect(screen.queryByTestId('doc-batch-bar')).toBeNull())
        successSpy.mockRestore()
    })

    it('批量移动：提交 action=move 与目标 parent_id；被跳过项提示原因', async () => {
        const warnSpy = vi.spyOn(message, 'warning')
        const bodies: unknown[] = []
        server.use(
            http.post('/api/v1/workspaces/10/documents/batch', async ({ request }) => {
                bodies.push(await request.json())
                return HttpResponse.json({
                    action: 'move',
                    updated: 1,
                    skipped: [{ id: 3, reason: '不能将文档移动到自身子孙节点下' }],
                })
            }),
        )
        renderPage()
        await screen.findByTestId('doc-select-2')

        fireEvent.click(screen.getByTestId('doc-select-2'))
        fireEvent.click(await screen.findByTestId('doc-batch-move'))
        // Modal 确认（antd 两字按钮文本渲染为「移 动」）
        fireEvent.click(await screen.findByRole('button', { name: /^移\s*动$/ }))

        await waitFor(() => expect(bodies).toHaveLength(1))
        // 默认目标是当前层级（?parent=1）
        expect(bodies[0]).toMatchObject({ action: 'move', ids: [2], parent_id: 1 })
        // 跳过项以 warning 提示（用 spy 断言文案，避免依赖 antd 静态 message 的挂载时序）
        expect(warnSpy).toHaveBeenCalledWith(expect.stringContaining('跳过 1 项'))
        expect(warnSpy).toHaveBeenCalledWith(expect.stringContaining('子孙'))
        await waitFor(() => expect(screen.queryByTestId('doc-batch-bar')).toBeNull())
        warnSpy.mockRestore()
    })

describe('DocumentsPage 最近打开与置顶标识', () => {
    function renderPage(route = '/w/10/documents') {
        return renderProviders(
            <Routes>
                <Route path="/w/:wid/documents" element={<DocumentsPage />} />
            </Routes>,
            { route, initialAuth: { user: mockUser, token: 'fake-token' } },
        )
    }

    it('无历史时不渲染最近打开条', async () => {
        renderPage()
        await screen.findByTestId('doc-series-card-1')
        expect(screen.queryByTestId('doc-recent')).toBeNull()
    })

    it('有历史时展示最近打开并可点击进入；清除后隐藏', async () => {
        window.localStorage.setItem(
            'cndb_recent_docs_v1:10',
            JSON.stringify([{ id: 2, title: '说明文档', at: 2000 }, { id: 999, title: '已删除文档', at: 1000 }]),
        )
        renderPage()

        const strip = await screen.findByTestId('doc-recent')
        expect(strip).toHaveTextContent('最近打开')
        // 已删除（不在树中）的条目被过滤，避免死链
        expect(screen.getByTestId('doc-recent-2')).toBeInTheDocument()
        expect(screen.queryByTestId('doc-recent-999')).toBeNull()

        fireEvent.click(screen.getByTestId('doc-recent-clear'))
        await waitFor(() => expect(screen.queryByTestId('doc-recent')).toBeNull())
        expect(window.localStorage.getItem('cndb_recent_docs_v1:10')).toBeNull()
    })

    it('置顶文档展示「置顶」标识', async () => {
        server.use(
            http.get('/api/v1/workspaces/10/documents/tree', () => HttpResponse.json({
                items: mockDocuments.map(d => ({ ...d, pinned: d.id === 1 })),
            })),
        )
        renderPage()

        await screen.findByTestId('doc-series-card-1')
        expect(screen.getByTestId('doc-pinned-tag-1')).toHaveTextContent('置顶')
    })
})
})

describe('DocumentsPage 标签筛选', () => {
    function renderPage(route = '/w/10/documents') {
        return renderProviders(
            <Routes>
                <Route path="/w/:wid/documents" element={<DocumentsPage />} />
            </Routes>,
            { route, initialAuth: { user: mockUser, token: 'fake-token' } },
        )
    }

    it('?tag= 深链：list 请求携带 tag_id，下拉回显所选标签', async () => {
        const tagIds: (string | null)[] = []
        server.use(
            http.get('/api/v1/workspaces/10/documents/tags', () =>
                HttpResponse.json({ items: [{ id: 7, name: '季度', doc_count: 2, color: null }] })),
            http.get('/api/v1/workspaces/10/documents', ({ request }) => {
                tagIds.push(new URL(request.url).searchParams.get('tag_id'))
                return HttpResponse.json({ items: [], total: 0 })
            }),
        )
        renderPage('/w/10/documents?parent=1&tag=7')

        await waitFor(() => expect(tagIds).toContain('7'))
    })

    it('根层按 ?tag= 过滤派生的散文档列表', async () => {
        const looseDocs = [
            { ...mockDocuments[1], id: 101, parent_id: null, is_folder: false, title: '带标签文档', tag_ids: [7] },
            { ...mockDocuments[1], id: 102, parent_id: null, is_folder: false, title: '无标签文档', tag_ids: [] },
        ]
        server.use(
            http.get('/api/v1/workspaces/10/documents/tags', () =>
                HttpResponse.json({ items: [{ id: 7, name: '季度', doc_count: 1, color: null }] })),
            http.get('/api/v1/workspaces/10/documents/tree', () => HttpResponse.json({ items: looseDocs })),
        )
        renderPage('/w/10/documents?tag=7')

        expect(await screen.findByText('带标签文档')).toBeInTheDocument()
        await waitFor(() => expect(screen.queryByText('无标签文档')).toBeNull())
        // 文件夹本身没有标签 → 按标签筛选时根层只展示命中的散文档（网格已移除，见 0065）
        expect(screen.queryByTestId('doc-series-grid')).toBeNull()
    })
})

describe('列表可见性提示', () => {
    it('未发布草稿标注「仅自己可见」，已发布不标注', async () => {
        const items = mockDocuments.map(d => {
            if (d.id === 2) {
                return { ...d, status: 'draft' as const, visibility: 'private' as const }
            }
            if (d.id === 3) {
                return { ...d, status: 'draft' as const, visibility: 'private' as const }
            }
            return { ...d, status: 'published' as const, visibility: 'workspace' as const }
        })
        server.use(
            http.get('/api/v1/workspaces/10/documents/tree', () => HttpResponse.json({ items })),
            http.get('/api/v1/workspaces/10/documents', () => HttpResponse.json({ items, total: items.length })),
        )

        renderProviders(
            <Routes>
                <Route path="/w/:wid/documents" element={<DocumentsPage />} />
            </Routes>,
            { route: '/w/10/documents?parent=1', initialAuth: { user: mockUser, token: 'fake-token' } },
        )

        await screen.findByTestId('doc-series-detail')

        const privateTag = await screen.findByTestId('doc-list-visibility-2')
        expect(privateTag).toHaveAttribute('aria-label', '仅自己可见')
        // 悬浮说明"同事看不到"，避免误以为文档丢失
        fireEvent.mouseEnter(privateTag)
        expect(await screen.findByText(/仅你与工作区所有者可见/)).toBeInTheDocument()

        // 已发布文档不显示提示（成员均可见）
        expect(screen.queryByTestId('doc-list-visibility-1')).toBeNull()
    })
})

describe('DocumentsPage 移动端顶部工具栏', () => {
  beforeEach(() => {
    responsiveState = {
      deviceType: 'mobile', isMobile: true, isTablet: false, isDesktop: false,
      width: 390, height: 844,
    }
  })

  afterEach(() => {
    responsiveState = {
      deviceType: 'desktop', isMobile: false, isTablet: false, isDesktop: true,
      width: 1280, height: 800,
    }
  })

  it('顶部收为两行：搜索与新建常驻，排序 / 筛选已移入侧栏（需求 0065）', async () => {
    renderProviders(
      <Routes>
        <Route path="/w/:wid/documents" element={<DocumentsPage />} />
      </Routes>,
      { route: '/w/10/documents', initialAuth: { user: mockUser, token: 'fake-token' } },
    )

    const toolbar = await screen.findByTestId('doc-toolbar-mobile')
    expect(toolbar).toBeVisible()
    // 桌面常显的次级按钮不再直接渲染
    expect(screen.queryByTestId('doc-trash-open')).toBeNull()
    expect(screen.queryByTestId('doc-file-import')).toBeNull()
    // 只剩导航行 + 搜索/筛选/新建行；列表排序控件在侧栏（?order=），不在页面
    expect(toolbar.children).toHaveLength(2)
    expect(screen.queryByTestId('doc-order-select')).toBeNull()
    // 标签 / 状态筛选在内容区顶部（需求 0065 第二次修订）
    expect(within(toolbar).getByTestId('doc-tag-filter')).toBeVisible()
    expect(within(toolbar).getByTestId('doc-status-filter')).toBeVisible()
    // 搜索、新建仍可用
    expect(within(toolbar).getByPlaceholderText('本页标题过滤')).toBeVisible()
    expect(within(toolbar).getByRole('button', { name: /新建/ })).toBeVisible()

    // 「更多」菜单承载回收站与导入入口
    fireEvent.click(within(toolbar).getByTestId('doc-toolbar-more'))
    expect(await screen.findByText('回收站')).toBeInTheDocument()
    expect(screen.getByText('导入')).toBeInTheDocument()
    expect(screen.getByText('新建文件夹')).toBeInTheDocument()
  })

  it('?status= 深链：list 请求携带 status 参数（状态筛选写 URL，控件在侧栏）', async () => {
    const statuses: (string | null)[] = []
    server.use(
      http.get('/api/v1/workspaces/10/documents', ({ request }) => {
        statuses.push(new URL(request.url).searchParams.get('status'))
        return HttpResponse.json({ items: [], total: 0 })
      }),
    )
    renderProviders(
      <Routes>
        <Route path="/w/:wid/documents" element={<DocumentsPage />} />
      </Routes>,
      { route: '/w/10/documents?parent=1&status=draft', initialAuth: { user: mockUser, token: 'fake-token' } },
    )

    await screen.findByTestId('doc-series-detail')
    await waitFor(() => expect(statuses[statuses.length - 1]).toBe('draft'))
  })
})

describe('文档列表边缘线与行操作', () => {
  function renderPage(route = '/w/10/documents?parent=1') {
    return renderProviders(
      <Routes>
        <Route path="/w/:wid/documents" element={<DocumentsPage />} />
      </Routes>,
      { route, initialAuth: { user: mockUser, token: 'fake-token' } },
    )
  }

  it('列表容器挂 GitHub 式边缘线样式类', async () => {
    renderPage()
    expect(await screen.findByTestId('doc-list')).toHaveClass('cn-doc-list')
  })

  it('行内重命名：回填原标题，提交 PATCH title', async () => {
    const bodies: unknown[] = []
    server.use(
      http.patch('/api/v1/workspaces/:wid/documents/:docId', async ({ request }) => {
        bodies.push(await request.json())
        return HttpResponse.json(mockDocuments[1])
      }),
    )
    renderPage()

    fireEvent.click(await screen.findByTestId('doc-row-rename-2'))
    const input = await screen.findByTestId('doc-rename-input')
    expect(input).toHaveValue('需求说明')
    fireEvent.change(input, { target: { value: '需求说明书' } })
    fireEvent.click(screen.getByRole('button', { name: /保\s*存/ }))

    await waitFor(() => expect(bodies).toEqual([{ title: '需求说明书' }]))
  })

  it('行内移动：改选根目录后提交 PATCH parent_id=0', async () => {
    const patches: Array<{ id: string; body: unknown }> = []
    server.use(
      http.patch('/api/v1/workspaces/:wid/documents/:docId', async ({ params, request }) => {
        patches.push({ id: String(params.docId), body: await request.json() })
        return HttpResponse.json(mockDocuments[1])
      }),
    )
    renderPage()

    fireEvent.click(await screen.findByTestId('doc-row-move-2'))
    await screen.findByText('移动「需求说明」到…')
    const selector = screen.getByTestId('doc-row-move-target').querySelector('.ant-select-selector')
    expect(selector).not.toBeNull()
    fireEvent.mouseDown(selector as Element)
    fireEvent.click(await screen.findByText('（根目录）'))
    fireEvent.click(screen.getByRole('button', { name: /^移\s*动$/ }))

    await waitFor(() => expect(patches).toEqual([{ id: '2', body: { parent_id: 0 } }]))
  })

  it('行内置顶：调用 POST /{docId}/pin', async () => {
    const pinned: string[] = []
    server.use(
      http.post('/api/v1/workspaces/:wid/documents/:docId/pin', ({ params }) => {
        pinned.push(String(params.docId))
        return HttpResponse.json({ document_id: 2, pinned: true })
      }),
    )
    renderPage()

    fireEvent.click(await screen.findByTestId('doc-row-pin-2'))
    await waitFor(() => expect(pinned).toEqual(['2']))
  })
})
})
