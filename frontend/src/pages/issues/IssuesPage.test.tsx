/**
 * IssuesPage 问题清单测试 —— 列表筛选 / 类别标签 / 评论数 / 新建跳转详情。
 *
 * 注：AntD portal 类 UI（Modal/message）在事件触发后异步挂载，
 * 断言必须用 await findBy*，同步 getBy 会与 portal 渲染竞态。
 */

import { describe, expect, it, vi } from 'vitest'
import { http, HttpResponse } from 'msw'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import { Routes, Route } from 'react-router-dom'
import IssuesPage from './IssuesPage'
import { renderProviders } from '@/test/render-providers'
import { mockUser, server } from '@/test/msw'
import { issuesApi } from '@/api'
import type { IssueListItem } from '@/api'

const ISSUES: IssueListItem[] = [
  {
    id: 31, workspace_id: 10, table_id: 20, title: '日期列出现 1970 值',
    description: '导入后日期错位', category: 'data_error', status: 'open',
    created_by_id: 1, comment_count: 2, created_at: '2026-10-01T10:00:00', updated_at: '2026-10-01T10:00:00',
  },
  {
    id: 30, workspace_id: 10, table_id: 20, title: '希望支持批量粘贴',
    description: '', category: 'suggestion', status: 'closed',
    created_by_id: 2, comment_count: 0, created_at: '2026-09-28T09:00:00', updated_at: '2026-09-28T09:00:00',
  },
]

const AUTH = { initialAuth: { user: mockUser, token: 'fake' } }

function listHandler(captured: { status?: string } = {}) {
  return http.get('/api/v1/workspaces/10/tables/20/issues', ({ request }) => {
    captured.status = new URL(request.url).searchParams.get('status') ?? undefined
    const status = captured.status ?? 'open'
    const items = status === 'all' ? ISSUES : ISSUES.filter(i => i.status === status)
    return HttpResponse.json({ items, total: items.length })
  })
}

function renderPage(route = '/w/10/tables/20/issues') {
  return renderProviders(
    <Routes>
      <Route path="/w/:wid/tables/:tid/issues" element={<IssuesPage />} />
      <Route path="/w/:wid/tables/:tid/issues/:issueId" element={<div data-testid="issue-detail-stub">详情</div>} />
    </Routes>,
    { route, ...AUTH },
  )
}

describe('IssuesPage 问题清单列表', () => {
  it('默认展示 open 列表，渲染类别标签与评论数', async () => {
    const captured: { status?: string } = {}
    server.use(listHandler(captured))
    renderPage()

    expect(await screen.findByText('日期列出现 1970 值')).toBeInTheDocument()
    // closed 项不出现（默认 open 过滤）
    expect(screen.queryByText('希望支持批量粘贴')).toBeNull()
    // 类别标签 + 评论数
    expect(screen.getByText('数据异常')).toBeInTheDocument()
    expect(screen.getByLabelText('评论数 2')).toBeInTheDocument()
    expect(captured.status).toBe('open')
  })

  it('切换「已关闭」筛选携带 status=closed', async () => {
    const captured: { status?: string } = {}
    server.use(listHandler(captured))
    renderPage()

    await screen.findByText('日期列出现 1970 值')
    fireEvent.click(screen.getByText('已关闭'))

    await waitFor(() => expect(captured.status).toBe('closed'))
    expect(await screen.findByText('希望支持批量粘贴')).toBeInTheDocument()
    expect(screen.queryByText('日期列出现 1970 值')).toBeNull()
  })

  it('切换「全部」时 closed 项带「已关闭」标记', async () => {
    const captured: { status?: string } = {}
    server.use(listHandler(captured))
    renderPage()

    await screen.findByText('日期列出现 1970 值')
    fireEvent.click(screen.getByText('全部'))

    await waitFor(() => expect(captured.status).toBe('all'))
    const closedRow = await screen.findByText('希望支持批量粘贴')
    expect(closedRow.closest('.ant-listy-item')?.textContent).toContain('已关闭')
  })

  it('点击列表项导航到详情页', async () => {
    server.use(listHandler())
    renderPage()

    fireEvent.click(await screen.findByText('日期列出现 1970 值'))
    await waitFor(() => {
      expect(screen.getByTestId('issue-detail-stub')).toBeInTheDocument()
    })
  })
})

describe('IssuesPage 新建问题', () => {
  it('提交成功后提示并跳转详情页', async () => {
    server.use(listHandler())
    const createSpy = vi.spyOn(issuesApi, 'create').mockResolvedValue({
      ...ISSUES[0]!, id: 32, title: '新问题', comments: [], events: [],
    })
    renderPage()

    fireEvent.click(await screen.findByRole('button', { name: /新\s*建\s*问\s*题/ }))
    // Modal 为 portal 渲染，用 findBy
    fireEvent.change(await screen.findByPlaceholderText('一句话描述问题'), { target: { value: '新问题' } })
    fireEvent.click(screen.getByRole('button', { name: /提\s*交/ }))

    await waitFor(() => expect(createSpy).toHaveBeenCalledTimes(1))
    expect(createSpy.mock.calls[0]![2]).toMatchObject({ title: '新问题', category: 'other' })
    expect(await screen.findByTestId('issue-detail-stub')).toBeInTheDocument()
    // 提交成功提示（message portal）
    expect(await screen.findByText('问题已提交')).toBeInTheDocument()
  })

  it('标题为空时校验拦截，不发起请求', async () => {
    server.use(listHandler())
    const createSpy = vi.spyOn(issuesApi, 'create').mockResolvedValue({
      ...ISSUES[0]!, comments: [], events: [],
    })
    renderPage()

    fireEvent.click(await screen.findByRole('button', { name: /新\s*建\s*问\s*题/ }))
    fireEvent.click(await screen.findByRole('button', { name: /提\s*交/ }))

    expect(await screen.findByText('请输入标题')).toBeInTheDocument()
    expect(createSpy).not.toHaveBeenCalled()
  })
})
