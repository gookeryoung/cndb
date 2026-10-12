/**
 * PermissionEditor 组件测试 —— 表权限编辑器（三区布局）.
 *
 * 覆盖：Owner 卡片 / 编辑者区-查看者区成员分区渲染 / 隐藏字段受控勾选 / 非管理者无管理入口 /
 * 切换角色 PATCH / Popconfirm 移除 DELETE / 分区添加成员 POST 与后端错误提示。
 */

import { describe, expect, it, vi } from 'vitest'
import { http, HttpResponse } from 'msw'
import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import PermissionEditor from './PermissionEditor'
import { renderProviders } from '@/test/render-providers'
import { server, mockUser } from '@/test/msw'
import { makeField } from '@/test/fixtures'
import type { Field, TableMember, TableOwnerInfo, WorkspaceMember, WorkspaceRole } from '@/api'

const WID = 10
const TID = 100

const FIELDS: Field[] = [
  makeField({ id: 1, name: '名称', field_type: 'text' }),
  makeField({ id: 2, name: '邮箱', field_type: 'text' }),
  makeField({ id: 3, name: '密级', field_type: 'select', config: { options: ['高', '低'] }, hidden: true }),
]

const OWNER: TableOwnerInfo = { id: 1, username: 'alice' }

const MEMBERS: TableMember[] = [
  { user_id: 2, username: 'bob', role: 'read' },
  { user_id: 3, username: 'carol', role: 'write' },
]

const WS_MEMBERS: WorkspaceMember[] = [
  { id: 11, workspace_id: WID, user_id: 2, role: 'editor', user: { id: 2, username: 'bob' } },
  { id: 12, workspace_id: WID, user_id: 3, role: 'editor', user: { id: 3, username: 'carol' } },
  { id: 13, workspace_id: WID, user_id: 4, role: 'editor', user: { id: 4, username: 'dave', nickname: '老D' } },
]

/** 覆盖 PermissionEditor 挂载所需的三个查询端点 */
function setupHandlers(opts?: { members?: TableMember[]; role?: WorkspaceRole }) {
  server.use(
    http.get(`/api/v1/workspaces/${WID}/tables/${TID}/members`, () =>
      HttpResponse.json(opts?.members ?? MEMBERS)),
    http.get(`/api/v1/workspaces/${WID}`, () =>
      HttpResponse.json({ id: WID, name: '测试工作区', current_user_role: opts?.role ?? 'owner' })),
    http.get(`/api/v1/workspaces/${WID}/members`, () => HttpResponse.json(WS_MEMBERS)),
  )
}

function renderEditor(opts?: {
  owner?: TableOwnerInfo
  hiddenNames?: string[]
  onHiddenNamesChange?: (names: string[]) => void
}) {
  return renderProviders(
    <PermissionEditor
      fields={FIELDS}
      wid={WID}
      tid={TID}
      owner={opts?.owner ?? OWNER}
      hiddenNames={opts?.hiddenNames ?? []}
      onHiddenNamesChange={opts?.onHiddenNamesChange ?? (() => { })}
    />,
    { initialAuth: { user: mockUser } },
  )
}

function openSelect(selector: Element) {
  fireEvent.mouseDown(selector)
}

/** 等待 canManageMembers 生效（workspace 查询返回前按钮禁用，返回后翻转可用） */
async function waitCanManage() {
  await waitFor(() => expect(screen.getByRole('button', { name: /转让所有权/ })).toBeEnabled())
}

describe('PermissionEditor 表权限编辑器', () => {
  it('展示态：Owner 卡片显示拥有者与"（就是您）"标记，管理按钮可用', async () => {
    setupHandlers()
    renderEditor()

    expect(await screen.findByText('alice')).toBeInTheDocument()
    expect(screen.getByText(/（就是您）/)).toBeInTheDocument()
    expect(screen.getByText(/拥有者对该表负全责/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /转让所有权/ })).toBeEnabled()
    expect(screen.getAllByRole('button', { name: /添加成员/ }).length).toBe(2)
  })

  it('展示态：三区布局 —— 编辑者/查看者分区卡片按授权级别展示成员', async () => {
    setupHandlers()
    renderEditor()

    const bobCell = await screen.findByText('bob')
    expect(screen.getByText('carol')).toBeInTheDocument()
    // bob（read）在查看者区，carol（write）在编辑者区；标题计数各 1
    const viewerCard = bobCell.closest('.ant-card')!
    expect(viewerCard.querySelector('.ant-card-head-title')!.textContent).toContain('查看者（1）')
    const editorCard = screen.getByText('carol').closest('.ant-card')!
    expect(editorCard.querySelector('.ant-card-head-title')!.textContent).toContain('编辑者（1）')
    expect(screen.getByText('read · 只读')).toBeInTheDocument()
    expect(screen.getByText('write · 可编辑')).toBeInTheDocument()
    // 两个分区各有一个「添加成员」入口
    expect(screen.getAllByRole('button', { name: /添加成员/ }).length).toBe(2)
  })

  it('展示态：隐藏字段 Checkbox 过滤 hidden 字段', async () => {
    setupHandlers()
    renderEditor()

    expect(await screen.findByRole('checkbox', { name: /名称/ })).toBeInTheDocument()
    expect(screen.getByRole('checkbox', { name: /邮箱/ })).toBeInTheDocument()
    // hidden: true 的「密级」不参与勾选
    expect(screen.queryByRole('checkbox', { name: /密级/ })).not.toBeInTheDocument()
    expect(screen.queryByText(/暂无可见字段/)).not.toBeInTheDocument()
  })

  it('展示态：非管理者（viewer 且非 owner）看不到添加入口且按钮禁用', async () => {
    setupHandlers({ role: 'viewer' })
    renderEditor({ owner: { id: 999, username: 'oscar' } })

    expect(await screen.findByText('oscar')).toBeInTheDocument()
    // 等成员行到达，避免在 loading 态断言按钮
    expect(await screen.findByText('bob')).toBeInTheDocument()
    expect(screen.queryByText(/（就是您）/)).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /添加成员/ })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /转让所有权/ })).toBeDisabled()
    screen.getAllByRole('button', { name: /移\s*除/ }).forEach(b => expect(b).toBeDisabled())
  })

  it('交互态：勾选/取消隐藏字段回调受控名称集合', async () => {
    setupHandlers()
    const onHiddenNamesChange = vi.fn()
    renderEditor({ hiddenNames: ['名称'], onHiddenNamesChange })

    expect(await screen.findByRole('checkbox', { name: /名称/ })).toBeChecked()

    // 勾选「邮箱」→ ['名称', '邮箱']
    fireEvent.click(screen.getByRole('checkbox', { name: /邮箱/ }))
    expect(onHiddenNamesChange).toHaveBeenCalledWith(['名称', '邮箱'])

    // 再取消「名称」→ 父级未实际更新受控值，组内仍勾选名称，移除后为 []
    fireEvent.click(screen.getByRole('checkbox', { name: /名称/ }))
    expect(onHiddenNamesChange).toHaveBeenCalledWith([])
  })

  it('交互态：切换成员角色发起 PATCH 更新', async () => {
    setupHandlers()
    const patchSpy = vi.fn()
    server.use(http.patch(`/api/v1/workspaces/${WID}/tables/${TID}/members/2`, async ({ request }) => {
      patchSpy(await request.json())
      return HttpResponse.json({ user_id: 2, username: 'bob', role: 'write' })
    }))
    renderEditor()

    expect(await screen.findByText('bob')).toBeInTheDocument()
    await waitCanManage()
    // 分区渲染顺序：编辑者区（carol）在前、查看者区（bob）在后，第二个 Select 为 bob 行
    openSelect(document.querySelectorAll('.ant-select .ant-select-selector')[1])
    // 选项 label 是 Tag（文本隔一层，option-content 无直接文本节点），在下拉容器内点选
    const dropdown = await waitFor(() => {
      const el = document.querySelector('.ant-select-dropdown')
      expect(el).not.toBeNull()
      return el as HTMLElement
    })
    fireEvent.click(within(dropdown).getByText('write · 可编辑'))

    await waitFor(() => expect(patchSpy).toHaveBeenCalledWith({ role: 'write' }))
  })

  it('交互态：Popconfirm 确认后发起 DELETE 移除成员', async () => {
    setupHandlers()
    const delSpy = vi.fn()
    // 编辑者区（carol，user_id=3）渲染在前，第一个移除按钮属于 carol
    server.use(http.delete(`/api/v1/workspaces/${WID}/tables/${TID}/members/3`, () => {
      delSpy()
      return HttpResponse.json({})
    }))
    renderEditor()

    expect(await screen.findByText('carol')).toBeInTheDocument()
    await waitCanManage()
    // 编辑者区 carol 行的移除按钮（第一个）
    fireEvent.click(screen.getAllByRole('button', { name: /移\s*除/ })[0]!)

    // 等待 Popconfirm 气泡出现后点击确认按钮
    await screen.findByText(/该用户将失去本表显式授予的成员权限/)
    const confirmBtn = document.querySelector('.ant-popconfirm .ant-btn-dangerous') as HTMLElement
    fireEvent.click(confirmBtn)

    await waitFor(() => expect(delSpy).toHaveBeenCalledTimes(1))
  })

  it('交互态：从编辑者区添加成员候选排除已有成员与 owner，提交 POST（默认 write）', async () => {
    setupHandlers()
    const addSpy = vi.fn()
    server.use(http.post(`/api/v1/workspaces/${WID}/tables/${TID}/members`, async ({ request }) => {
      addSpy(await request.json())
      return HttpResponse.json({ user_id: 4, username: 'dave', role: 'write' })
    }))
    renderEditor()

    // 编辑者区（write 分区渲染在前）的「添加成员」按钮，弹窗预选 write
    const addBtns = await screen.findAllByRole('button', { name: /添加成员/ })
    fireEvent.click(addBtns[0]!)
    const modal = (await screen.findByText('添加表成员')).closest('.ant-modal') as HTMLElement

    // 模态框内第一个 Select 为用户选择器
    openSelect(modal.querySelectorAll('.ant-select .ant-select-selector')[0])
    // 候选只剩 dave（bob/carol 已是表成员，alice 是 owner）
    fireEvent.click(await screen.findByText('dave (老D)', { selector: '.ant-select-item-option-content' }))
    fireEvent.click(within(modal).getByRole('button', { name: /添\s*加/ }))

    await waitFor(() => expect(addSpy).toHaveBeenCalledWith({ user_id: 4, role: 'write' }))
  })

  it('异常态：添加成员后端报错时展示 detail 错误信息', async () => {
    setupHandlers()
    server.use(http.post(`/api/v1/workspaces/${WID}/tables/${TID}/members`, () =>
      HttpResponse.json({ detail: '用户不存在' }, { status: 400 })))
    renderEditor()

    const addBtns = await screen.findAllByRole('button', { name: /添加成员/ })
    fireEvent.click(addBtns[0]!)
    const modal = (await screen.findByText('添加表成员')).closest('.ant-modal') as HTMLElement
    openSelect(modal.querySelectorAll('.ant-select .ant-select-selector')[0])
    fireEvent.click(await screen.findByText('dave (老D)', { selector: '.ant-select-item-option-content' }))
    fireEvent.click(within(modal).getByRole('button', { name: /添\s*加/ }))

    // axios 拦截器把 detail 提取为 Error.message，经 antd message 展示
    expect(await screen.findByText('用户不存在')).toBeInTheDocument()
  })
})
