/**
 * LinkedTablePage 组件测试（ADR 0154 P2）—— 跨工作区只读网格.
 *
 * 覆盖：
 * 1) 正常态：展示来源 / 批准人 / 到期 / 只读徽标 + 表格数据；
 * 2) 只读边界：页面没有任何编辑 / 删除 / 新增入口；
 * 3) 无读取权限（403）：给出可执行提示且不渲染表格；
 * 4) 导出 CSV：走链接 export 端点。
 */

import { beforeEach, describe, expect, it } from 'vitest'
import { http, HttpResponse } from 'msw'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Routes, Route } from 'react-router-dom'

import LinkedTablePage from './LinkedTablePage'
import { server } from '@/test/msw'
import { installLinkHandlers, mockWorkspaceLink } from '@/test/linkFixtures'
import { renderProviders } from '@/test/render-providers'

function renderPage(linkOverrides: Record<string, unknown> = {}) {
  server.use(
    http.get('/api/v1/workspaces/:wid/links', () =>
      HttpResponse.json([{ ...mockWorkspaceLink, ...linkOverrides }])),
  )
  return renderProviders(
    <Routes>
      <Route path="/w/:wid/links/:linkId" element={<LinkedTablePage />} />
    </Routes>,
    { route: `/w/10/links/${mockWorkspaceLink.id}` },
  )
}

describe('LinkedTablePage 只读链接页', () => {
  beforeEach(() => installLinkHandlers(server))

  it('展示来源、批准人、到期与只读徽标，并渲染链接数据', async () => {
    renderPage()

    expect(await screen.findByTestId('linked-table-page')).toBeVisible()
    expect(await screen.findByTestId('linked-table-source')).toHaveTextContent('源工作区')
    expect(screen.getByTestId('linked-table-meta')).toHaveTextContent('张三')
    expect(screen.getByText('只读')).toBeVisible()

    expect(await screen.findByText('甲')).toBeVisible()
    expect(screen.getByText('12')).toBeVisible()
  })

  it('只读边界：没有新增 / 编辑 / 删除入口', async () => {
    renderPage()

    await screen.findByTestId('linked-table-grid')
    expect(screen.queryByRole('button', { name: /新\s*增|添加|编辑|删除|批量/ })).toBeNull()
    // 表内不出现可编辑输入框（只读渲染）
    expect(screen.queryByRole('textbox')).toBeNull()
  })

  it('无读取权限时给出提示且不渲染表格', async () => {
    server.use(
      http.get('/api/v1/workspaces/:wid/links', () =>
        HttpResponse.json([{ ...mockWorkspaceLink, readable: false }])),
      http.get('/api/v1/workspaces/:wid/links/:lid/fields', () =>
        HttpResponse.json({ detail: '你当前在此工作区的角色为【查看者】，权限不足' }, { status: 403 })),
    )
    renderProviders(
      <Routes>
        <Route path="/w/:wid/links/:linkId" element={<LinkedTablePage />} />
      </Routes>,
      { route: `/w/10/links/${mockWorkspaceLink.id}` },
    )

    expect(await screen.findByTestId('linked-table-denied')).toBeVisible()
    expect(screen.queryByTestId('linked-table-grid')).toBeNull()
  })

  it('导出 CSV 调用链接导出端点', async () => {
    let exported = 0
    server.use(
      http.get('/api/v1/workspaces/:wid/links/:lid/export', () => {
        exported += 1
        return new HttpResponse('名称,金额\n甲,12\n', {
          status: 200,
          headers: { 'Content-Type': 'text/csv; charset=utf-8' },
        })
      }),
    )
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: () => 'blob:mock' })
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: () => undefined })

    const user = userEvent.setup()
    renderPage()

    const button = await screen.findByTestId('linked-table-export')
    await waitFor(() => expect(button).toBeEnabled())
    await user.click(button)
    await waitFor(() => expect(exported).toBe(1))
  })
})
