/**
 * ViewPermissionDrawer 测试 —— 视图可见性三档 + 共享名单（ADR 0003 P3）.
 *
 * 覆盖：三档渲染与即时生效（无保存按钮）/ 「表内所有人可见」需表 EDIT_VIEWS 门控（D4）/
 * 名单加载与可授权对象 / 加人（默认 viewer）/ 改权（editor）/ 收权 / 已失效授权标注 /
 * 非 shared 档的名单保留提示（后端保留但不生效）。
 *
 * 网络走 MSW（`src/test/msw.ts`，onUnhandledRequest: 'error'），逐用例 server.use() 覆盖。
 */

import { describe, expect, it, vi } from 'vitest'
import { http, HttpResponse } from 'msw'
import { fireEvent, screen, waitFor } from '@testing-library/react'

import { renderProviders } from '@/test/render-providers'
import { server } from '@/test/msw'
import type { ShareableMember, View, ViewMember } from '@/api'
import ViewPermissionDrawer from './ViewPermissionDrawer'

const WID = 10
const TID = 100
const VID = 200
const BASE = `/api/v1/workspaces/${WID}/tables/${TID}/views/${VID}`

const SHARED_VIEW: View = {
  id: VID, name: '本月进行中', view_type: 'grid', is_default: false,
  visibility: 'shared', owner_id: 1, can_edit: true, can_manage: true, grantee_count: 2,
}

const ROSTER: ViewMember[] = [
  { user_id: 2, username: 'bob', nickname: '鲍勃', role: 'editor', available: true },
  { user_id: 3, username: 'carol', nickname: '', role: 'viewer', available: false },
]

const SHAREABLE: ShareableMember[] = [
  { user_id: 3, username: 'carol', nickname: '', can_edit_views: false },
  { user_id: 4, username: 'dave', nickname: '戴夫', can_edit_views: true },
]

/** 注册本组件会用到的全部端点（未覆盖的用例再用 server.use 叠加） */
function useBaseHandlers(roster: ViewMember[] = ROSTER) {
  server.use(
    http.get(`${BASE}/members`, () => HttpResponse.json(roster)),
    http.get(`${BASE}/shareable-members`, () => HttpResponse.json(SHAREABLE)),
    http.get(`${BASE}`, () => HttpResponse.json(SHARED_VIEW)),
    http.post(`${BASE}/visibility`, async ({ request }) => {
      const body = (await request.json()) as Record<string, unknown>
      return HttpResponse.json({ ...SHARED_VIEW, visibility: body.visibility })
    }),
    http.put(`${BASE}/members/:uid`, async ({ params, request }) => {
      const body = (await request.json()) as { role: ViewMember['role'] }
      return HttpResponse.json({ user_id: Number(params.uid), username: 'x', nickname: '', role: body.role, available: true })
    }),
    http.delete(`${BASE}/members/:uid`, () => new HttpResponse(null, { status: 204 })),
  )
}

function renderDrawer(overrides: Partial<React.ComponentProps<typeof ViewPermissionDrawer>> = {}) {
  const props = {
    open: true,
    onClose: vi.fn(),
    wid: String(WID),
    tid: String(TID),
    view: SHARED_VIEW,
    canPublishToTable: true,
    onUpdated: vi.fn(),
    ...overrides,
  }
  const utils = renderProviders(<ViewPermissionDrawer {...props} />, { route: `/w/${WID}/tables/${TID}` })
  return { ...utils, props }
}

/** 打开第 idx 个 antd Select（0 = 添加成员的多选） */
function openSelect(idx: number) {
  const selector = document.querySelectorAll('.ant-select')[idx]
  fireEvent.mouseDown(selector)
}

/** 点击下拉选项（连续操作时前一个 portal 可能残留，取最后一个） */
async function pickOption(text: string) {
  const opts = await screen.findAllByText(text, { selector: '.ant-select-item-option-content' })
  fireEvent.click(opts.at(-1)!)
}

describe('ViewPermissionDrawer 档位', () => {
  it('渲染三档单选并高亮当前档位，附带共享人数', async () => {
    useBaseHandlers()
    renderDrawer()

    expect(await screen.findByRole('radio', { name: /指定成员可见/ })).toBeChecked()
    expect(screen.getByRole('radio', { name: /仅本人可见/ })).not.toBeChecked()
    expect(screen.getByRole('radio', { name: /表内所有人可见/ })).not.toBeChecked()
    expect(screen.getByText('2 人')).toBeInTheDocument()
  })

  it('切档只提交 visibility，不带 members（后端据此保留既有名单）', async () => {
    let posted: Record<string, unknown> | null = null
    useBaseHandlers()
    server.use(
      http.post(`${BASE}/visibility`, async ({ request }) => {
        posted = (await request.json()) as Record<string, unknown>
        return HttpResponse.json({ ...SHARED_VIEW, visibility: 'private' })
      }),
    )
    const { props } = renderDrawer()

    fireEvent.click(screen.getByRole('radio', { name: /仅本人可见/ }))

    await waitFor(() => expect(posted).toEqual({ visibility: 'private' }))
    expect(props.onUpdated).toHaveBeenCalled()
  })

  it('无表 EDIT_VIEWS 时「表内所有人可见」档禁用并给出原因（D4）', async () => {
    useBaseHandlers()
    renderDrawer({ canPublishToTable: false })

    expect(await screen.findByRole('radio', { name: /表内所有人可见/ })).toBeDisabled()
    expect(await screen.findByText(/无权限/)).toBeInTheDocument()
  })

  it('私有档且名单为空时不渲染成员区，仅给引导文案', async () => {
    useBaseHandlers([])
    renderDrawer({ view: { ...SHARED_VIEW, visibility: 'private', grantee_count: 0 } })

    expect(await screen.findByText(/切换到「指定成员可见」后即可选择共享对象/)).toBeInTheDocument()
    expect(screen.queryByTestId('view-member-add')).toBeNull()
  })

  it('非 shared 档但名单有留存时提示「切回后自动恢复生效」', async () => {
    useBaseHandlers()
    renderDrawer({ view: { ...SHARED_VIEW, visibility: 'private' } })

    expect(await screen.findByTestId('view-member-preserved')).toHaveTextContent('已保留 2 人')
  })
})

describe('ViewPermissionDrawer 共享名单', () => {
  it('列出名单并区分「只读 / 可编辑」，失效授权打标', async () => {
    useBaseHandlers()
    renderDrawer()

    expect(await screen.findByTestId('view-member-row-2')).toHaveTextContent('鲍勃')
    expect(screen.getByTestId('view-member-row-3')).toHaveTextContent('carol')
    expect(screen.getByText('已失效')).toBeInTheDocument()
    expect(screen.getByTestId('view-member-role-2')).toHaveTextContent('可编辑')
    expect(screen.getByTestId('view-member-role-3')).toHaveTextContent('只读')
  })

  it('添加成员默认授予只读，并把「可编辑」能力标注在选择项上', async () => {
    const calls: Array<{ uid: string; role: string }> = []
    useBaseHandlers()
    server.use(
      http.put(`${BASE}/members/:uid`, async ({ params, request }) => {
        const body = (await request.json()) as { role: string }
        calls.push({ uid: String(params.uid), role: body.role })
        return HttpResponse.json({ user_id: Number(params.uid), username: 'dave', nickname: '戴夫', role: body.role, available: true })
      }),
    )
    renderDrawer()
    await screen.findByTestId('view-member-add')

    openSelect(0)
    // 是否可选 editor 完全由后端下发的 can_edit_views 决定，前端不自己算
    expect(await screen.findByText('戴夫（可编辑）', { selector: '.ant-select-item-option-content' })).toBeInTheDocument()
    await pickOption('戴夫（可编辑）')

    await waitFor(() => expect(calls).toEqual([{ uid: '4', role: 'viewer' }]))
  })

  it('已列入名单的成员不再出现在可添加项里', async () => {
    useBaseHandlers()
    renderDrawer()
    await screen.findByTestId('view-member-add')

    openSelect(0)
    expect(await screen.findByText('戴夫（可编辑）', { selector: '.ant-select-item-option-content' })).toBeInTheDocument()
    // carol 已在名单中 → 即便 can_edit_views=false 也不作为可选项出现
    expect(screen.queryByText('carol', { selector: '.ant-select-item-option-content' })).toBeNull()
  })

  it('改权调用 PUT members/{uid} 并回传角色', async () => {
    const calls: Array<{ uid: string; role: string }> = []
    useBaseHandlers()
    server.use(
      http.put(`${BASE}/members/:uid`, async ({ params, request }) => {
        const body = (await request.json()) as { role: string }
        calls.push({ uid: String(params.uid), role: body.role })
        return HttpResponse.json({ user_id: Number(params.uid), username: 'bob', nickname: '鲍勃', role: body.role, available: true })
      }),
    )
    renderDrawer()
    await screen.findByTestId('view-member-role-2')

    openSelect(1) // 0 = 添加成员，1 = 第一行的角色选择器
    await pickOption('只读')

    await waitFor(() => expect(calls).toEqual([{ uid: '2', role: 'viewer' }]))
  })

  it('移除成员调用 DELETE 并刷新列表与视图', async () => {
    const removed: string[] = []
    useBaseHandlers()
    server.use(
      http.delete(`${BASE}/members/:uid`, ({ params }) => {
        removed.push(String(params.uid))
        return new HttpResponse(null, { status: 204 })
      }),
    )
    const { props } = renderDrawer()
    await screen.findByTestId('view-member-row-2')

    fireEvent.click(screen.getByLabelText('移除 bob'))

    await waitFor(() => expect(removed).toEqual(['2']))
    await waitFor(() => expect(props.onUpdated).toHaveBeenCalled())
  })
})
