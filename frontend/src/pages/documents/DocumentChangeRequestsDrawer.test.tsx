/**
 * DocumentChangeRequestsDrawer 测试 —— 待审列表 / 内容 DIFF 展开 / 通过 · 驳回 · 刷新基准 · 删除草稿
 * 以及按角色与提交人身份的门控。
 */

import { describe, expect, it, vi } from 'vitest'
import { http, HttpResponse } from 'msw'
import { fireEvent, screen, waitFor } from '@testing-library/react'

import type { DocumentChangeRequestItem } from '@/api/documents'
import { documentsApi } from '@/api/documents'
import { renderProviders } from '@/test/render-providers'
import { mockUser, server } from '@/test/msw'
import DocumentChangeRequestsDrawer from './DocumentChangeRequestsDrawer'

const OPEN_CR: DocumentChangeRequestItem = {
  id: 7,
  workspace_id: 10,
  document_id: 2,
  document_title: '需求说明',
  title: '修改文档《需求说明》',
  description: '补充交付范围',
  change_summary: '',
  status: 'open',
  stale: false,
  base_version_number: 1,
  current_version_number: 1,
  proposed_size: 15,
  submitted_by_id: 2,
  reviewed_by_id: null,
  reviewed_at: null,
  review_comment: '',
  created_at: '2026-10-15T09:00:00',
  updated_at: '2026-10-15T09:00:00',
}

const DETAIL: DocumentChangeRequestItem = {
  ...OPEN_CR,
  proposed_content: '# 标题\n新增段落\n',
  diff: {
    diff: '--- base\n+++ head\n@@ -1,2 +1,3 @@\n # 标题\n+新增段落\n',
    added: 1,
    removed: 0,
    base_size: 8,
    proposed_size: 15,
    base_version_number: 1,
  },
}

function renderDrawer(role: 'owner' | 'editor' | 'viewer' = 'owner', userId = 1) {
  return renderProviders(
    <DocumentChangeRequestsDrawer open onClose={() => { }} workspaceId={10} documentId={2} role={role} />,
    { initialAuth: { user: { ...mockUser, id: userId }, token: 'fake' } },
  )
}

function stubList(items: DocumentChangeRequestItem[]) {
  server.use(
    http.get('/api/v1/workspaces/10/document-change-requests', () => HttpResponse.json({ items, total: items.length })),
    http.get('/api/v1/workspaces/10/document-change-requests/7', () => HttpResponse.json(DETAIL)),
  )
}

describe('DocumentChangeRequestsDrawer', () => {
  it('渲染待审申请：状态、标题、基准版本与提案规模', async () => {
    stubList([OPEN_CR])
    renderDrawer()

    expect(await screen.findByText('修改文档《需求说明》')).toBeInTheDocument()
    expect(screen.getByText('待审核')).toBeInTheDocument()
    expect(screen.getByText('补充交付范围')).toBeInTheDocument()
    expect(screen.getByText(/v1 → v1/)).toBeInTheDocument()
    expect(screen.queryByText('基准已过期')).toBeNull()
  })

  it('owner 可「通过」：调用 merge 并提示新版本号', async () => {
    stubList([OPEN_CR])
    const mergeSpy = vi.spyOn(documentsApi, 'mergeChangeRequest').mockResolvedValue({
      request: { ...OPEN_CR, status: 'merged' },
      version_number: 2,
    })
    renderDrawer('owner')

    fireEvent.click(await screen.findByTestId('dcr-merge-7'))

    await waitFor(() => expect(mergeSpy).toHaveBeenCalledWith(10, 7))
    expect(await screen.findByText('已通过并生成 v2')).toBeInTheDocument()
  })

  it('展开差异：拉取详情并用文档 DIFF 组件渲染内容变更', async () => {
    stubList([OPEN_CR])
    renderDrawer()

    fireEvent.click(await screen.findByTestId('dcr-toggle-7'))

    expect(await screen.findByTestId('dcr-diff-7')).toBeInTheDocument()
    expect(await screen.findByText('新增段落')).toBeInTheDocument()
    expect(screen.getByText('+1 新增')).toBeInTheDocument()
  })

  it('提交人在基准过期时可「刷新基准」', async () => {
    stubList([{ ...OPEN_CR, stale: true, current_version_number: 2 }])
    const baseSpy = vi.spyOn(documentsApi, 'updateChangeRequestBase').mockResolvedValue({
      ...OPEN_CR,
      stale: false,
      base_version_number: 2,
    })
    renderDrawer('viewer', 2)

    expect(await screen.findByText('基准已过期')).toBeInTheDocument()
    fireEvent.click(screen.getByTestId('dcr-rebase-7'))

    await waitFor(() => expect(baseSpy).toHaveBeenCalledWith(10, 7))
    expect(await screen.findByText('基准已刷新至 v2')).toBeInTheDocument()
  })

  it('提交人可删除草稿（确认后调用 DELETE）', async () => {
    stubList([OPEN_CR])
    const deleteSpy = vi.spyOn(documentsApi, 'deleteChangeRequest').mockResolvedValue(undefined)
    renderDrawer('viewer', 2)

    fireEvent.click(await screen.findByTestId('dcr-delete-7'))
    // antd 会在两字按钮文案间插空格，用锚定正则匹配 Popconfirm 的确认按钮
    fireEvent.click(await screen.findByRole('button', { name: /^删\s*除$/ }))

    await waitFor(() => expect(deleteSpy).toHaveBeenCalledWith(10, 7))
    expect(await screen.findByText('草稿已删除')).toBeInTheDocument()
  })

  it('非提交人 viewer 无审核与删除入口', async () => {
    stubList([OPEN_CR])
    renderDrawer('viewer', 99)

    expect(await screen.findByText('修改文档《需求说明》')).toBeInTheDocument()
    expect(screen.queryByTestId('dcr-merge-7')).toBeNull()
    expect(screen.queryByTestId('dcr-close-7')).toBeNull()
    expect(screen.queryByTestId('dcr-delete-7')).toBeNull()
    // 查看差异对所有成员开放
    expect(screen.getByTestId('dcr-toggle-7')).toBeInTheDocument()
  })

  it('无申请时展示空态说明', async () => {
    stubList([])
    renderDrawer()

    expect(await screen.findByText(/暂无修改申请/)).toBeInTheDocument()
  })
})
