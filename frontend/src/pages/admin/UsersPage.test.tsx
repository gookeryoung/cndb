/**
 * UsersPage 用户管理页组件测试.
 *
 * 覆盖：列表渲染 / 筛选参数 / 编辑二次确认后提交 / 批量操作 / 操作日志抽屉.
 */

import { describe, expect, it, vi, afterEach, beforeEach } from 'vitest'
import { http, HttpResponse } from 'msw'
import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import UsersPage from './UsersPage'
import { renderProviders } from '@/test/render-providers'
import { server, mockUser } from '@/test/msw'
import type { ResponsiveState } from '@/hooks/useResponsive'

// 可控 useResponsive mock：默认桌面端，移动端用例在其内部切换
let responsiveState: ResponsiveState = {
  deviceType: 'desktop', isMobile: false, isTablet: false, isDesktop: true,
  width: 1280, height: 800,
}
vi.mock('@/hooks/useResponsive', async () => {
  const actual = await vi.importActual<typeof import('@/hooks/useResponsive')>('@/hooks/useResponsive')
  return { ...actual, useResponsive: () => responsiveState }
})

beforeEach(() => {
  // jsdom 无 Blob URL 实现：导出/下载用例需要它；每次用例重新定义并清空调用记录
  Object.defineProperty(URL, 'createObjectURL', { value: vi.fn(() => 'blob:mock'), writable: true, configurable: true })
  Object.defineProperty(URL, 'revokeObjectURL', { value: vi.fn(), writable: true, configurable: true })
})

afterEach(() => {
  vi.restoreAllMocks()
  responsiveState = {
    deviceType: 'desktop', isMobile: false, isTablet: false, isDesktop: true,
    width: 1280, height: 800,
  }
})

const USERS = {
  total: 2,
  items: [
    {
      id: 1, username: 'admin_su', email: 'su@x.com', phone: '13800000001',
      nickname: '系统管理员', role: 'system_admin', is_active: true,
      is_superuser: true, created_at: '2026-01-01T00:00:00Z',
    },
    {
      id: 2, username: 'bob', email: null, phone: null,
      nickname: '普通用户', role: 'user', is_active: false,
      is_superuser: false, created_at: '2026-01-02T00:00:00Z',
    },
  ],
}

const LOGS = {
  total: 1,
  items: [
    {
      id: 10, action: 'role_change', actor_id: 1, target_user_id: 2,
      detail: { before: { role: 'user' }, after: { role: 'security_admin' } },
      created_at: '2026-01-03T00:00:00Z',
    },
  ],
}

function renderPage() {
  return renderProviders(<UsersPage />, { route: '/admin', initialAuth: { user: mockUser, token: 'fake-token' } })
}

describe('UsersPage 用户管理', () => {
  it('渲染用户列表并展示角色/状态', async () => {
    server.use(http.get('/api/v1/accounts/users', () => HttpResponse.json(USERS)))
    renderPage()

    expect(await screen.findByText('admin_su')).toBeInTheDocument()
    expect(screen.getByText('bob')).toBeInTheDocument()
    // 昵称与角色标签可能同名（系统管理员），至少渲染一次即可
    expect(screen.getAllByText('系统管理员').length).toBeGreaterThan(0)
    expect(screen.getByText('13800000001')).toBeInTheDocument()
    // bob 被禁用
    expect(screen.getByText('禁用')).toBeInTheDocument()
    // 分页总数
    expect(screen.getByText(/共 2 个用户/)).toBeInTheDocument()
  })

  it('筛选参数随查询下发', async () => {
    // MSW handler 首参为 { request, params, cookies }，显式标注以供断言取 request
    const spy = vi.fn((_info: { request: Request }) => HttpResponse.json(USERS))
    server.use(http.get('/api/v1/accounts/users', spy))
    renderPage()

    await screen.findByText('admin_su')
    const input = screen.getByPlaceholderText('搜索用户名/邮箱/昵称…')
    fireEvent.change(input, { target: { value: 'bob' } })
    // SearchInput（0068）无搜索按钮：回车触发 onSearch 下发查询
    fireEvent.keyDown(input, { key: 'Enter' })

    await waitFor(() => {
      const calls = spy.mock.calls.filter(([info]) => new URL(info.request.url).searchParams.get('keyword') === 'bob')
      expect(calls.length).toBeGreaterThan(0)
    })
  })

  it('编辑保存前弹出二次确认，确认后提交 PATCH', async () => {
    server.use(
      http.get('/api/v1/accounts/users', () => HttpResponse.json(USERS)),
      http.patch('/api/v1/accounts/users/2', () => HttpResponse.json(USERS.items[1])),
    )
    renderPage()

    // 打开 bob 的编辑弹窗
    fireEvent.click((await screen.findAllByText('编辑'))[1])
    expect(await screen.findByText(/编辑用户：bob/)).toBeInTheDocument()

    // 修改昵称产生实际变更（无变更时组件会拦截保存）
    fireEvent.change(screen.getByLabelText('昵称'), { target: { value: '新昵称' } })
    fireEvent.click(screen.getByRole('button', { name: '保 存' }))
    // 二次确认弹窗
    expect(await screen.findByText('确认保存对该用户的修改？', { selector: '.ant-modal-title' })).toBeInTheDocument()
    fireEvent.click(await screen.findByRole('button', { name: '确认保存' }))

    expect(await screen.findByText('用户已更新，变更已记录到操作日志')).toBeInTheDocument()
  })

  it('新建用户：填写表单二次确认后提交 admin-register', async () => {
    const createHandler = vi.fn(() =>
      HttpResponse.json({
        id: 9, username: 'newbie', email: null, nickname: '普通用户',
        role: 'user', is_active: true, is_superuser: false,
      }),
    )
    server.use(
      http.get('/api/v1/accounts/users', () => HttpResponse.json(USERS)),
      http.post('/api/v1/accounts/auth/admin-register', createHandler),
    )
    renderPage()
    await screen.findByText('bob')

    fireEvent.click(screen.getByRole('button', { name: /新建用户/ }))
    expect(await screen.findByText('新建用户', { selector: '.ant-modal-title' })).toBeInTheDocument()

    fireEvent.change(screen.getByLabelText('用户名'), { target: { value: 'newbie' } })
    fireEvent.change(screen.getByLabelText('初始密码'), { target: { value: 'pw123456' } })
    fireEvent.click(screen.getByRole('button', { name: /创\s*建/ }))

    // 二次确认弹窗
    expect(await screen.findByText('确认创建该用户？', { selector: '.ant-modal-title' })).toBeInTheDocument()
    fireEvent.click(await screen.findByRole('button', { name: '确认创建' }))

    await waitFor(() => expect(createHandler).toHaveBeenCalledTimes(1))
    expect(await screen.findByText('用户 newbie 已创建')).toBeInTheDocument()
  })

  it('勾选用户后批量禁用走确认并提交 batch', async () => {
    const batchHandler = vi.fn(() =>
      HttpResponse.json({ total: 1, succeeded: 1, failed: 0, results: [{ user_id: 2, username: 'bob', success: true }] }),
    )
    server.use(
      http.get('/api/v1/accounts/users', () => HttpResponse.json(USERS)),
      http.post('/api/v1/accounts/users/batch', batchHandler),
    )
    renderPage()

    await screen.findByText('bob') // 等表格行渲染完成，行选择复选框才存在
    fireEvent.click((await screen.findAllByRole('checkbox'))[1])
    expect(await screen.findByText(/已选择 1 个用户/)).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '批量禁用' }))
    // Popconfirm 气泡确认
    fireEvent.click(await screen.findByRole('button', { name: '确认禁用' }))
    // Popconfirm 确认后进入 Modal.confirm，再次确认
    fireEvent.click(await screen.findByRole('button', { name: '确认执行' }))

    await waitFor(() => expect(batchHandler).toHaveBeenCalledTimes(1))
    expect(await screen.findByText(/批量操作完成：成功 1 项/)).toBeInTheDocument()
  })

  it('打开日志抽屉展示权限变更历史（before/after）', async () => {
    server.use(
      http.get('/api/v1/accounts/users', () => HttpResponse.json(USERS)),
      http.get('/api/v1/accounts/users/2/audit-logs', () => HttpResponse.json(LOGS)),
    )
    renderPage()

    fireEvent.click((await screen.findAllByText('日志'))[1])
    expect(await screen.findByText(/操作日志：bob/)).toBeInTheDocument()
    expect(await screen.findByText('角色变更')).toBeInTheDocument()
    expect(screen.getByText(/user.*→.*security_admin/)).toBeInTheDocument()
  })

  it('导出：按当前筛选请求 CSV 并触发浏览器下载', async () => {
    const requested: URL[] = []
    const exportHandler = vi.fn(({ request }: { request: Request }) => {
      requested.push(new URL(request.url))
      return new HttpResponse('username,email\nbob,b@x.com', {
        headers: {
          'content-type': 'text/csv',
          'content-disposition': 'attachment; filename="users.csv"; filename*=UTF-8\'\'%E7%94%A8%E6%88%B7%E5%88%97%E8%A1%A8.csv',
        },
      })
    })
    server.use(
      http.get('/api/v1/accounts/users', () => HttpResponse.json(USERS)),
      http.get('/api/v1/accounts/users/export', exportHandler),
    )
    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    renderPage()

    await screen.findByText('bob')
    fireEvent.click(screen.getByRole('button', { name: /导\s*出/ }))
    fireEvent.click(await screen.findByText('导出 CSV'))

    await waitFor(() => expect(exportHandler).toHaveBeenCalledTimes(1))
    expect(requested[0].searchParams.get('format')).toBe('csv')
    expect(URL.createObjectURL).toHaveBeenCalledTimes(1)
    expect(clickSpy).toHaveBeenCalledTimes(1)
    expect(await screen.findByText(/已导出 2 个用户/)).toBeInTheDocument()
  })

  it('批量导入：先预演再确认导入，展示结果与初始密码下载入口', async () => {
    // jsdom 的 FormData/File 与 undici multipart 解析器不兼容，直接按调用次序区分预演/正式导入
    let importCalls = 0
    const importHandler = vi.fn(() => {
      importCalls += 1
      const dryRun = importCalls === 1
      return HttpResponse.json({
        total: 1, created: 1, skipped: 0, failed: 0, dry_run: dryRun,
        results: [{
          row_index: 1, status: 'ok', message: dryRun ? '预演通过' : '',
          user_id: dryRun ? null : 9, username: 'imp_x',
          generated_password: dryRun ? null : 'Gen123456789',
        }],
      })
    })
    server.use(
      http.get('/api/v1/accounts/users', () => HttpResponse.json(USERS)),
      http.post('/api/v1/accounts/users/import', importHandler),
    )
    renderPage()
    await screen.findByText('bob')

    fireEvent.click(screen.getByRole('button', { name: /导\s*入/ }))
    expect(await screen.findByText('批量导入用户')).toBeInTheDocument()

    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement
    const file = new File(['username\nimp_x'], 'users.csv', { type: 'text/csv' })
    fireEvent.change(fileInput, { target: { files: [file] } })

    expect(await screen.findByText(/预演结果：共 1 行，可导入 1/)).toBeInTheDocument()
    expect(screen.getByText('可导入')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /确认导入 1 个用户/ }))

    expect(await screen.findByText(/导入完成：成功 1 个/)).toBeInTheDocument()
    expect(await screen.findByRole('button', { name: /下载初始密码（1）/ })).toBeInTheDocument()
    expect(importHandler).toHaveBeenCalledTimes(2)
  })
})

describe('UsersPage 管理员重置密码', () => {
  it('默认自动生成：二次确认后展示一次性密码', async () => {
    const resetHandler = vi.fn(() =>
      HttpResponse.json({ ok: true, generated_password: 'Ab3xY9pQ2mZk', revoked_sessions: 2 }),
    )
    server.use(
      http.get('/api/v1/accounts/users', () => HttpResponse.json(USERS)),
      http.post('/api/v1/accounts/users/2/password', resetHandler),
    )
    renderPage()

    fireEvent.click((await screen.findAllByText('重置密码'))[1])
    expect(await screen.findByText('重置用户密码', { selector: '.ant-modal-title' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '生成并重置' }))

    expect(await screen.findByText(/确认重置用户「bob」的密码？/, { selector: '.ant-modal-confirm-title' })).toBeInTheDocument()
    fireEvent.click(within(document.querySelector('.ant-modal-confirm') as HTMLElement).getByRole('button', { name: '确认重置' }))

    await waitFor(() => expect(resetHandler).toHaveBeenCalledTimes(1))
    expect(await screen.findByTestId('reset-password-result')).toHaveTextContent('Ab3xY9pQ2mZk')
    expect(screen.getByText(/只展示这一次/)).toBeInTheDocument()
  })

  it('手工输入：提交自定义密码且不回显', async () => {
    let body: unknown = null
    server.use(
      http.get('/api/v1/accounts/users', () => HttpResponse.json(USERS)),
      http.post('/api/v1/accounts/users/2/password', async ({ request }) => {
        body = await request.json()
        return HttpResponse.json({ ok: true, generated_password: null, revoked_sessions: 1 })
      }),
    )
    renderPage()

    fireEvent.click((await screen.findAllByText('重置密码'))[1])
    fireEvent.click(await screen.findByLabelText('手工输入'))
    fireEvent.change(screen.getByLabelText('新密码'), { target: { value: 'manual-pass-1' } })
    fireEvent.click(screen.getByRole('button', { name: '确认重置' }))
    await screen.findByText(/确认重置用户「bob」的密码？/, { selector: '.ant-modal-confirm-title' })
    fireEvent.click(within(document.querySelector('.ant-modal-confirm') as HTMLElement).getByRole('button', { name: '确认重置' }))

    await waitFor(() => expect(body).toEqual({ new_password: 'manual-pass-1' }))
    expect(await screen.findByText(/密码已重置，目标用户需用新密码重新登录/)).toBeInTheDocument()
    expect(screen.queryByTestId('reset-password-result')).not.toBeInTheDocument()
  })

  it('手工输入过短时阻止提交', async () => {
    const resetHandler = vi.fn(() => HttpResponse.json({ ok: true, generated_password: null, revoked_sessions: 0 }))
    server.use(
      http.get('/api/v1/accounts/users', () => HttpResponse.json(USERS)),
      http.post('/api/v1/accounts/users/2/password', resetHandler),
    )
    renderPage()

    fireEvent.click((await screen.findAllByText('重置密码'))[1])
    fireEvent.click(await screen.findByLabelText('手工输入'))
    fireEvent.change(screen.getByLabelText('新密码'), { target: { value: '123' } })
    fireEvent.click(screen.getByRole('button', { name: '确认重置' }))

    expect(await screen.findByText('密码长度须为 6-128 位')).toBeInTheDocument()
    expect(resetHandler).not.toHaveBeenCalled()
  })
})

describe('UsersPage 移动端适配', () => {
  it('窄屏下筛选控件整行排布，表格保留列宽并横向滚动', async () => {
    responsiveState = {
      deviceType: 'mobile', isMobile: true, isTablet: false, isDesktop: false,
      width: 390, height: 844,
    }
    server.use(http.get('/api/v1/accounts/users', () => HttpResponse.json(USERS)))
    renderPage()

    expect(await screen.findByText('admin_su')).toBeInTheDocument()

    // 筛选控件整行（避免固定宽度在手机上与相邻控件互相挤压）
    const searchInput = screen.getByPlaceholderText('搜索用户名/邮箱/昵称…')
    expect((searchInput.closest('.ant-input-affix-wrapper') as HTMLElement).style.width).toBe('100%')

    // 窄屏不再渲染宽表格：改为卡片列表（一屏一实体，无需左右滑动看角色/操作）
    expect(document.querySelector('.ant-table')).toBeNull()
    expect(screen.getByTestId('users-mobile-list')).toBeInTheDocument()
    expect(screen.getByTestId('user-card-1')).toHaveTextContent('admin_su')
  })

  it('桌面端筛选控件保持既有固定宽度', async () => {
    server.use(http.get('/api/v1/accounts/users', () => HttpResponse.json(USERS)))
    renderPage()

    await screen.findByText('admin_su')
    const searchInput = screen.getByPlaceholderText('搜索用户名/邮箱/昵称…')
    expect((searchInput.closest('.ant-input-affix-wrapper') as HTMLElement).style.width).toBe('220px')

    // 桌面端仍是表格：内容容器横向滚动 + 表格按内容宽度展开（列宽不被压成逐字换行，滚动兜底）
    const content = document.querySelector('.ant-table-content') as HTMLElement
    const table = content.querySelector('table') as HTMLElement
    expect(content.style.overflowX).toBe('auto')
    expect(table.style.width).toBe('max-content')
    const colWidths = [...document.querySelectorAll('.ant-table colgroup col')].map(
      c => (c as HTMLElement).style.width,
    )
    expect(colWidths).toContain('120px') // 昵称列
    expect(colWidths).toContain('180px') // 邮箱列
  })

  it('窄屏改为卡片列表：一屏一实体，角色/状态/操作直接可见', async () => {
    responsiveState = {
      deviceType: 'mobile', isMobile: true, isTablet: false, isDesktop: false,
      width: 390, height: 844,
    }
    server.use(http.get('/api/v1/accounts/users', () => HttpResponse.json(USERS)))
    renderPage()

    expect(await screen.findByTestId('users-mobile-list')).toBeInTheDocument()
    // 不再渲染宽表格
    expect(document.querySelector('.ant-table')).toBeNull()
    const card = screen.getByTestId('user-card-1')
    expect(card).toHaveTextContent('admin_su')
    expect(card).toHaveTextContent('su@x.com')
    expect(card).toHaveTextContent('系统管理员')
    expect(card).toHaveTextContent('超管')
    expect(card).toHaveTextContent('启用')
    expect(within(card).getByText('编辑')).toBeInTheDocument()
    expect(within(card).getByText('日志')).toBeInTheDocument()
    // 分页信息保留
    expect(screen.getByText('共 2 个用户')).toBeInTheDocument()
  })

  it('窄屏卡片勾选可参与批量操作', async () => {
    responsiveState = {
      deviceType: 'mobile', isMobile: true, isTablet: false, isDesktop: false,
      width: 390, height: 844,
    }
    server.use(http.get('/api/v1/accounts/users', () => HttpResponse.json(USERS)))
    renderPage()

    await screen.findByTestId('users-mobile-list')
    fireEvent.click(screen.getByLabelText('选择用户 bob'))

    expect(await screen.findByText(/已选择 1 个用户/)).toBeInTheDocument()
  })

  it('窄屏卡片「编辑」打开编辑弹窗', async () => {
    responsiveState = {
      deviceType: 'mobile', isMobile: true, isTablet: false, isDesktop: false,
      width: 390, height: 844,
    }
    server.use(http.get('/api/v1/accounts/users', () => HttpResponse.json(USERS)))
    renderPage()

    fireEvent.click(within(await screen.findByTestId('user-card-1')).getByText('编辑'))

    expect(await screen.findByText('编辑用户：admin_su')).toBeInTheDocument()
  })

  it('窄屏卡片「重置密码」打开重置弹窗', async () => {
    responsiveState = {
      deviceType: 'mobile', isMobile: true, isTablet: false, isDesktop: false,
      width: 390, height: 844,
    }
    server.use(http.get('/api/v1/accounts/users', () => HttpResponse.json(USERS)))
    renderPage()

    fireEvent.click(within(await screen.findByTestId('user-card-2')).getByText('重置密码'))

    expect(await screen.findByText('重置用户密码', { selector: '.ant-modal-title' })).toBeInTheDocument()
    expect(document.querySelector('.ant-modal-content')?.textContent).toContain('目标用户：bob')
  })

  it('桌面端仍为表格，不渲染卡片列表', async () => {
    server.use(http.get('/api/v1/accounts/users', () => HttpResponse.json(USERS)))
    renderPage()

    expect(await screen.findByText('admin_su')).toBeInTheDocument()
    expect(screen.queryByTestId('users-mobile-list')).toBeNull()
    expect(document.querySelector('.ant-table')).toBeTruthy()
  })
})
