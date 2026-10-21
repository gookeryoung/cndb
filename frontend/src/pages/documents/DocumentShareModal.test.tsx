/** 文档分享弹层（ADR 0017）——列表回显 / 创建 / 复制链接 / 撤销 / 未发布禁用. */

import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { http, HttpResponse } from 'msw'

import type { ShareItem } from '@/api/documents'
import { renderProviders } from '@/test/render-providers'
import { server } from '@/test/msw'
import DocumentShareModal, { shareLink } from './DocumentShareModal'

const WID = 10
const DOC_ID = 2

const ACTIVE: ShareItem = {
  id: 1,
  document_id: DOC_ID,
  token: 'token-active',
  permission: 'viewer',
  has_password: true,
  expires_at: null,
  view_count: 12,
  is_active: true,
  created_at: '2026-10-20T09:00:00Z',
}

const REVOKED: ShareItem = {
  ...ACTIVE,
  id: 2,
  token: 'token-revoked',
  has_password: false,
  view_count: 3,
  is_active: false,
}

function renderModal(docStatus = 'published') {
  return renderProviders(
    <DocumentShareModal open onClose={() => { }} workspaceId={WID} docId={DOC_ID} docStatus={docStatus} />,
  )
}

/** 可变的分享列表桩：创建 / 撤销后 GET 仍能反映最新状态 */
function stubShares(initial: ShareItem[]) {
  const items = [...initial]
  const created: unknown[] = []
  server.use(
    http.get(`/api/v1/workspaces/${WID}/documents/${DOC_ID}/share`, () =>
      HttpResponse.json({ items })),
    http.post(`/api/v1/workspaces/${WID}/documents/${DOC_ID}/share`, async ({ request }) => {
      const body = await request.json()
      created.push(body)
      const next: ShareItem = { ...ACTIVE, id: 11, token: 'token-new', has_password: false, view_count: 0 }
      items.unshift(next)
      return HttpResponse.json(next, { status: 201 })
    }),
    http.delete(`/api/v1/workspaces/${WID}/documents/${DOC_ID}/share/:shareId`, ({ params }) => {
      const id = Number(params.shareId)
      const target = items.find(it => it.id === id)
      if (target) target.is_active = false
      return HttpResponse.json({ id, revoked: true })
    }),
  )
  return { items, created }
}

describe('DocumentShareModal', () => {
  beforeEach(() => {
    server.resetHandlers()
  })

  it('列表展示状态 / 访问次数 / 需密码，已撤销的复制与撤销禁用', async () => {
    stubShares([ACTIVE, REVOKED])
    renderModal()

    expect(await screen.findByTestId('document-share-item-1')).toBeInTheDocument()
    expect(screen.getByText('有效')).toBeInTheDocument()
    expect(screen.getByText('已撤销')).toBeInTheDocument()
    expect(screen.getByText('需密码')).toBeInTheDocument()
    expect(screen.getByText('访问 12 次')).toBeInTheDocument()
    expect(screen.getByText('访问 3 次')).toBeInTheDocument()

    const revoked = screen.getByTestId('document-share-item-2')
    expect(within(revoked).getByRole('button', { name: /复制链接/ })).toBeDisabled()
    expect(within(revoked).getByRole('button', { name: /撤销/ })).toBeDisabled()
  })

  it('已发布文档可创建链接，创建后列表刷新', async () => {
    const { created } = stubShares([])
    renderModal()

    fireEvent.click(await screen.findByTestId('document-share-create'))

    expect(await screen.findByTestId('document-share-item-11')).toBeInTheDocument()
    expect(created).toEqual([{ permission: 'viewer' }])
    expect(screen.getByText('有效')).toBeInTheDocument()
  })

  it('未发布文档：提示并禁用创建', async () => {
    const { created } = stubShares([])
    renderModal('draft')

    expect(await screen.findByTestId('document-share-unpublished')).toHaveTextContent('仅已发布文档可创建分享链接')
    expect(screen.getByTestId('document-share-create')).toBeDisabled()
    expect(created).toEqual([])
  })

  it('复制链接为免登录公开页地址', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText },
    })
    stubShares([ACTIVE])
    renderModal()

    fireEvent.click(await screen.findByRole('button', { name: /复制链接/ }))

    await waitFor(() => expect(writeText).toHaveBeenCalledWith(shareLink(ACTIVE.token)))
    expect(writeText.mock.calls[0][0]).toBe(`${window.location.origin}/public/share/token-active`)
  })

  it('撤销后列表状态更新为已撤销', async () => {
    stubShares([ACTIVE])
    renderModal()

    const item = await screen.findByTestId('document-share-item-1')
    fireEvent.click(within(item).getByRole('button', { name: /撤销/ }))

    await waitFor(() => expect(document.querySelector('.ant-popconfirm')).not.toBeNull())
    const popconfirm = document.querySelector('.ant-popconfirm') as HTMLElement
    fireEvent.click(within(popconfirm).getByRole('button', { name: /^撤\s*销$/ }))

    await waitFor(() => expect(screen.getByText('已撤销')).toBeInTheDocument())
    expect(within(screen.getByTestId('document-share-item-1')).getByRole('button', { name: /复制链接/ }))
      .toBeDisabled()
  })
})
