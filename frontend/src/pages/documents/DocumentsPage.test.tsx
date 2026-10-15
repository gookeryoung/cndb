/**
 * 文档管理页测试 —— 顶层系列卡片总览 + 系列详情视图：
 * 纯函数聚合（buildSeriesStats）+ 顶层卡片网格渲染与导航 + 系列级操作（重命名/移动/删除）。
 */

import { describe, expect, it } from 'vitest'
import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { Routes, Route } from 'react-router-dom'
import { http, HttpResponse } from 'msw'
import DocumentsPage, { buildSeriesStats } from './DocumentsPage'
import { renderProviders } from '@/test/render-providers'
import { mockDocuments, mockUser, server } from '@/test/msw'
import type { DocumentItem } from '@/api/documents'

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
    await screen.findByTestId('doc-series-card-1')

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
    await screen.findByTestId('doc-series-card-1')

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
    await screen.findByTestId('doc-series-card-1')

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

    it('排序切换写入 URL，并在文件夹列表请求中带上 order 参数', async () => {
        const orders: string[] = []
        server.use(
            http.get('/api/v1/workspaces/10/documents', ({ request }) => {
                const url = new URL(request.url)
                orders.push(url.searchParams.get('order') ?? 'sort')
                return HttpResponse.json({ items: [], total: 0 })
            }),
        )
        // 根层不请求 list（由全量树派生），故进入文件夹后再验证
        renderPage('/w/10/documents?parent=1')
        await screen.findByTestId('doc-order-select')
        await screen.findByRole('button', { name: /上一级/ })
        await waitFor(() => expect(orders.length).toBeGreaterThan(0))
        expect(orders[orders.length - 1]).toBe('sort')

        const openSelect = () => {
            const selector = screen.getByTestId('doc-order-select').querySelector('.ant-select-selector') as HTMLElement
            fireEvent.mouseDown(selector)
        }
        openSelect()
        fireEvent.click(await screen.findByText('最近更新'))
        await waitFor(() => expect(orders[orders.length - 1]).toBe('updated'))

        // 再切回「手动顺序」时 URL 不保留 order 参数（保持链接干净）
        openSelect()
        fireEvent.click(await screen.findByText('手动顺序'))
        await waitFor(() => expect(orders[orders.length - 1]).toBe('sort'))
    })

    it('?parent= 深链：直接进入该文件夹（顶栏出现「上一级」）', async () => {
        renderPage('/w/10/documents?parent=1')

        expect(await screen.findByRole('button', { name: /上一级/ })).toBeInTheDocument()
        // 文件夹标题出现在面包屑中（产品文档；页面标题与卡片也会出现该文本，故用 findAllByText）
        expect((await screen.findAllByText('产品文档')).length).toBeGreaterThan(0)
    })
})

describe('DocumentsPage 系列卡片排序', () => {
    it('切到「最近更新」后，系列卡片按系列最新更新时间倒序排列', async () => {
        // 两个根文件夹：A 更新较新、B 较旧；手动顺序相反（B 在前）
        const tree = [
            { ...mockDocuments[0], id: 1, title: '旧系列', sort_order: 0 },
            { ...mockDocuments[2], id: 2, parent_id: 1, title: '旧系列的文档', updated_at: '2026-01-01T00:00:00Z' },
            { ...mockDocuments[0], id: 3, title: '新系列', sort_order: 1 },
            { ...mockDocuments[2], id: 4, parent_id: 3, title: '新系列的文档', updated_at: '2026-09-01T00:00:00Z' },
        ]
        server.use(http.get('/api/v1/workspaces/10/documents/tree', () => HttpResponse.json({ items: tree })))
        renderProviders(
            <Routes>
                <Route path="/w/:wid/documents" element={<DocumentsPage />} />
            </Routes>,
            { route: '/w/10/documents', initialAuth: { user: mockUser, token: 'fake-token' } },
        )

        const titles = () => Array.from(document.querySelectorAll('[data-testid^="doc-series-card-"]'))
            .map(el => el.getAttribute('data-testid'))

        // 默认手动顺序：旧系列(1) 在前
        await screen.findByTestId('doc-series-card-1')
        expect(titles()[0]).toBe('doc-series-card-1')

        const selector = screen.getByTestId('doc-order-select').querySelector('.ant-select-selector') as HTMLElement
        fireEvent.mouseDown(selector)
        fireEvent.click(await screen.findByText('最近更新'))

        await waitFor(() => expect(titles()[0]).toBe('doc-series-card-3'))
    })
})
})
