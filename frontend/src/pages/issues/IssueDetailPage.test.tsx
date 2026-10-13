/**
 * IssueDetailPage 问题详情测试 —— 描述/评论/事件流渲染、发表评论、关闭/重开门控与流转。
 *
 * 注：AntD portal 类 UI（message）在事件触发后异步挂载，
 * 断言必须用 await findBy*，同步 getBy 会与 portal 渲染竞态。
 */

import { describe, expect, it, vi } from 'vitest'
import { http, HttpResponse } from 'msw'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import { Routes, Route } from 'react-router-dom'
import IssueDetailPage from './IssueDetailPage'
import { renderProviders } from '@/test/render-providers'
import { mockUser, server } from '@/test/msw'
import { issuesApi } from '@/api'
import type { IssueDetail } from '@/api'

const DETAIL: IssueDetail = {
  id: 31, workspace_id: 10, table_id: 20, title: '日期列出现 1970 值',
  description: '导入 CSV 后日期错位', category: 'data_error', status: 'open',
  created_by_id: 2, created_at: '2026-10-01T10:00:00', updated_at: '2026-10-01T10:00:00',
  comments: [
    { id: 9, issue_id: 31, content: '已确认是零填充问题', created_by_id: 1, created_at: '2026-10-01T11:00:00' },
  ],
  events: [
    { id: 1, issue_id: 31, action: 'created', actor_id: 2, created_at: '2026-10-01T10:00:00' },
  ],
}

const AUTH = { initialAuth: { user: mockUser, token: 'fake' } }

function setupDetailHandlers(overrides: Partial<IssueDetail> = {}) {
  server.use(
    http.get('/api/v1/workspaces/10/tables/20/issues/31', () =>
      HttpResponse.json({ ...DETAIL, ...overrides })),
    http.get('/api/v1/workspaces/10', () =>
      HttpResponse.json({
        id: 10, name: '测试工作区', description: '', visibility: 'member', tags: [],
        current_user_role: 'owner',
      })),
    http.get('/api/v1/workspaces/10/members', () =>
      HttpResponse.json([
        { id: 1, workspace_id: 10, user_id: 1, role: 'owner', pinned: false, user: { id: 1, username: 'alice', nickname: '爱丽丝', email: null } },
        { id: 2, workspace_id: 10, user_id: 2, role: 'editor', pinned: false, user: { id: 2, username: 'bob', nickname: null, email: null } },
      ])),
  )
}

function renderPage() {
  return renderProviders(
    <Routes>
      <Route path="/w/:wid/tables/:tid/issues/:issueId" element={<IssueDetailPage />} />
    </Routes>,
    { route: '/w/10/tables/20/issues/31', ...AUTH },
  )
}

describe('IssueDetailPage 问题详情', () => {
  it('渲染标题/描述/状态标签/评论与事件流（成员名映射）', async () => {
    setupDetailHandlers()
    renderPage()

    expect(await screen.findByText(/日期列出现 1970 值/)).toBeInTheDocument()
    expect(screen.getByText('导入 CSV 后日期错位')).toBeInTheDocument()
    expect(screen.getByText('待处理')).toBeInTheDocument()
    expect(screen.getByText('数据异常')).toBeInTheDocument()
    // 评论与事件流使用成员名映射（nickname / username）
    expect(screen.getByText('爱丽丝')).toBeInTheDocument()
    expect(screen.getByText('已确认是零填充问题')).toBeInTheDocument()
    // 事件流：bob 创建了问题（名字与动作分属嵌套节点，分开断言）
    expect(screen.getByText('bob')).toBeInTheDocument()
    expect(screen.getByText(/创建了问题/)).toBeInTheDocument()
  })

  it('发表评论后清空输入框并刷新评论列表', async () => {
    setupDetailHandlers()
    const addSpy = vi.spyOn(issuesApi, 'addComment').mockResolvedValue({
      id: 10, issue_id: 31, content: '修复中', created_by_id: 1, created_at: '2026-10-02T09:00:00',
    })
    renderPage()

    fireEvent.change(await screen.findByPlaceholderText('写下评论…'), { target: { value: '修复中' } })
    fireEvent.click(screen.getByRole('button', { name: /发\s*表\s*评\s*论/ }))

    await waitFor(() => expect(addSpy).toHaveBeenCalledWith('10', '20', '31', '修复中'))
    await waitFor(() => expect(screen.getByPlaceholderText('写下评论…')).toHaveValue(''))
  })

  it('owner 可关闭问题：状态流转为已关闭并提示', async () => {
    // 关闭后 invalidate 会回拉列表，GET handler 按可变状态返回已关闭
    let current: IssueDetail = DETAIL
    setupDetailHandlers()
    server.use(
      http.get('/api/v1/workspaces/10/tables/20/issues/31', () => HttpResponse.json(current)),
    )
    const closeSpy = vi.spyOn(issuesApi, 'close').mockImplementation(async () => {
      current = { ...DETAIL, status: 'closed' }
      return current
    })
    renderPage()

    fireEvent.click(await screen.findByRole('button', { name: /关\s*闭\s*问\s*题/ }))

    await waitFor(() => expect(closeSpy).toHaveBeenCalledTimes(1))
    // invalidate 回拉后状态标签更新 + message portal 提示
    expect(await screen.findByText('已关闭')).toBeInTheDocument()
    expect(await screen.findByText('问题已关闭')).toBeInTheDocument()
    // 关闭后出现「重开问题」入口
    expect(await screen.findByRole('button', { name: /重\s*开\s*问\s*题/ })).toBeInTheDocument()
  })

  it('查看者且非创建者时不显示流转按钮（与后端 403 门控一致）', async () => {
    setupDetailHandlers()
    server.use(
      http.get('/api/v1/workspaces/10', () =>
        HttpResponse.json({
          id: 10, name: '测试工作区', description: '', visibility: 'member', tags: [],
          current_user_role: 'viewer',
        })),
    )
    renderPage()

    await screen.findByText(/日期列出现 1970 值/)
    await waitFor(() => {
      expect(screen.queryByRole('button', { name: /关\s*闭\s*问\s*题/ })).toBeNull()
      expect(screen.queryByRole('button', { name: /重\s*开\s*问\s*题/ })).toBeNull()
    })
  })

  it('查看者是创建者本人时仍可关闭', async () => {
    setupDetailHandlers({ created_by_id: 1 })
    server.use(
      http.get('/api/v1/workspaces/10', () =>
        HttpResponse.json({
          id: 10, name: '测试工作区', description: '', visibility: 'member', tags: [],
          current_user_role: 'viewer',
        })),
    )
    const closeSpy = vi.spyOn(issuesApi, 'close').mockResolvedValue({ ...DETAIL, status: 'closed' })
    renderPage()

    fireEvent.click(await screen.findByRole('button', { name: /关\s*闭\s*问\s*题/ }))
    await waitFor(() => expect(closeSpy).toHaveBeenCalledTimes(1))
  })
})
