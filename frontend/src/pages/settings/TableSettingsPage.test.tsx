/**
 * TableSettingsPage 路由页测试 —— 由 TableSettingsModal 页面化（P3）后的回归保障。
 *
 * 验收：
 *  1. ?tab=permissions 直达时自动加载权限数据（useEffect refetch，修复原 enabled:false 永不加载）
 *  2. 隐藏字段走受控 state：保存 payload 为 { hidden_fields: { viewer: [...] }, manage_data_role }，且不携带 row_filters
 *  3. 基本信息脏检查：无改动时保存禁用，修改表名后启用
 *  4. Tab 状态由 URL ?tab= 驱动：切换 Tab 写回 search params
 *  5. 删除表后 navigate 回工作区表列表
 */

import { describe, expect, it, beforeEach, afterEach, vi } from 'vitest'
import { http, HttpResponse } from 'msw'
import { screen, waitFor, fireEvent, within } from '@testing-library/react'
import { Routes, Route, useLocation } from 'react-router-dom'
import TableSettingsPage from './TableSettingsPage'
import { renderProviders } from '@/test/render-providers'
import { server } from '@/test/msw'
import { permissionApi, viewApi } from '@/api'
import type { View } from '@/api'
import type { ResponsiveState } from '@/hooks/useResponsive'

// 可控 useResponsive mock：默认桌面端（竖排页签），移动端用例在其内部切换
let responsiveState: ResponsiveState = {
  deviceType: 'desktop', isMobile: false, isTablet: false, isDesktop: true,
  width: 1280, height: 800,
}
vi.mock('@/hooks/useResponsive', async () => {
  const actual = await vi.importActual<typeof import('@/hooks/useResponsive')>('@/hooks/useResponsive')
  return { ...actual, useResponsive: () => responsiveState }
})

const WID = '10'
const TID = '20'

/** 表详情 fixture（含统计 / 视图摘要 / 当前用户动作） */
const tableFixture = {
  id: 20, workspace_id: 10, name: '任务表', description: '原始描述',
  db_table_name: 't_20',
  fields: [
    { id: 1, name: '标题', field_type: 'text', order: 0 },
    { id: 2, name: '密级', field_type: 'select', order: 1 },
    { id: 3, name: '备注', field_type: 'longtext', order: 2 },
  ],
  created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
  field_count: 3, record_count: 42, view_count: 2,
  owner: { id: 1, username: 'alice', nickname: null },
  views: [
    { id: 1, name: '全部任务', view_type: 'grid', is_default: true },
    { id: 2, name: '按状态', view_type: 'kanban', is_default: false },
  ],
  current_user_actions: ['edit_schema', 'edit_views', 'edit_records'],
  trashed: false,
}

/** 权限 fixture：viewer 桶预置一个隐藏字段 + 已有行级过滤（验证保存不误清空） */
const permFixture = {
  hidden_fields: { viewer: ['密级'] },
  row_filters: { conjunction: 'AND', conditions: [] },
  manage_data_role: '',
}

const AUTH = {
  initialAuth: {
    user: { id: 1, username: 'alice', email: null, role: 'system_admin' as const, is_active: true },
    token: 'fake',
  },
}

function setupTableHandlers() {
  server.use(
    http.get('/api/v1/workspaces/:wid/tables/:tid', () => HttpResponse.json(tableFixture)),
    http.get('/api/v1/workspaces/:wid/tables/:tid/views', () => HttpResponse.json(tableFixture.views)),
    // PermissionEditor 挂载时的成员 / 工作区查询
    http.get('/api/v1/workspaces/:wid/tables/:tid/members', () => HttpResponse.json([])),
    http.get('/api/v1/workspaces/:wid', () =>
      HttpResponse.json({
        id: 10, name: '测试工作区', description: '', visibility: 'member', tags: [],
        allow_edit: true, created_by_id: 1, created_at: '', updated_at: '',
        owner: { id: 1, username: 'alice', nickname: null },
        table_count: 1, member_count: 1, view_count: 0, total_rows: 0,
        current_user_role: 'owner',
      }),
    ),
    http.get('/api/v1/workspaces/:wid/members', () =>
      HttpResponse.json([
        {
          id: 1, workspace_id: 10, user_id: 1, role: 'owner', pinned: false,
          user: { id: 1, username: 'alice', nickname: null, email: null },
        },
      ]),
    ),
  )
}

/** 页面从 useParams 取 wid/tid，测试需用真实路由结构挂载；tab 用初始 route 指定 */
function renderPage(route = `/w/${WID}/tables/${TID}/settings`) {
  return renderProviders(
    <Routes>
      <Route path="/w/:wid/tables/:tid/settings" element={<TableSettingsPage />} />
    </Routes>,
    { route, ...AUTH },
  )
}

function LocationProbe() {
  const loc = useLocation()
  return <span data-testid="location">{loc.pathname}{loc.search}</span>
}

/** 带路由探针的渲染（删除表导航用例） */
function renderPageWithProbe(route = `/w/${WID}/tables/${TID}/settings`) {
  return renderProviders(
    <Routes>
      <Route path="/w/:wid/tables" element={<LocationProbe />} />
      <Route path="/w/:wid/tables/:tid/settings" element={<><TableSettingsPage /><LocationProbe /></>} />
    </Routes>,
    { route, ...AUTH },
  )
}

describe('TableSettingsPage 权限健壮性', () => {
  beforeEach(() => {
    setupTableHandlers()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('?tab=permissions 直达时自动加载权限数据', async () => {
    const getSpy = vi.spyOn(permissionApi, 'get').mockResolvedValue(permFixture)
    renderPage(`/w/${WID}/tables/${TID}/settings?tab=permissions`)

    await waitFor(() => expect(getSpy).toHaveBeenCalled(), { timeout: 5000 })
  })

  it('隐藏字段勾选受控：保存 payload 为 viewer 桶且不携带 row_filters', async () => {
    vi.spyOn(permissionApi, 'get').mockResolvedValue(permFixture)
    const patchSpy = vi.spyOn(permissionApi, 'patch').mockResolvedValue(permFixture)
    renderPage(`/w/${WID}/tables/${TID}/settings?tab=permissions`)

    // 等待权限数据到达并回显：viewer 桶预置的「密级」应勾选
    const mijiBox = await screen.findByRole('checkbox', { name: /密级/ }, { timeout: 5000 })
    await waitFor(() => expect(mijiBox).toBeChecked())

    // 勾选「备注」→ hiddenNames = ['密级', '备注']
    fireEvent.click(screen.getByRole('checkbox', { name: /备注/ }))
    fireEvent.click(screen.getByRole('button', { name: /保\s*存\s*权\s*限/ }))

    await waitFor(() => expect(patchSpy).toHaveBeenCalledTimes(1))
    const firstPayload = patchSpy.mock.calls[0]![2]!
    expect(firstPayload).toEqual({ hidden_fields: { viewer: ['密级', '备注'] }, manage_data_role: '' })
    expect(firstPayload).not.toHaveProperty('row_filters')

    // 取消「密级」→ hiddenNames = ['备注']（空/部分取消也能正确落库）
    fireEvent.click(screen.getByRole('checkbox', { name: /密级/ }))
    fireEvent.click(screen.getByRole('button', { name: /保\s*存\s*权\s*限/ }))

    await waitFor(() => expect(patchSpy).toHaveBeenCalledTimes(2))
    expect(patchSpy.mock.calls[1]![2]!).toEqual({ hidden_fields: { viewer: ['备注'] }, manage_data_role: '' })
  })
})

describe('TableSettingsPage 基本信息脏检查', () => {
  beforeEach(() => {
    setupTableHandlers()
  })

  it('无改动时保存禁用，修改表名后启用', async () => {
    renderPage()

    // 等表单回填（默认 Tab 为 basic）
    const nameInput = await screen.findByDisplayValue('任务表', {}, { timeout: 5000 })
    const saveBtn = screen.getByRole('button', { name: /保\s*存/ })
    expect(saveBtn).toBeDisabled()

    fireEvent.change(nameInput, { target: { value: '新表名' } })
    await waitFor(() => expect(saveBtn).toBeEnabled())
  })

  it('Tab 切换写回 URL search params（?tab=views），basic 时不携带参数', async () => {
    renderPageWithProbe()

    await screen.findByDisplayValue('任务表', {}, { timeout: 5000 })
    expect(screen.getByTestId('location')).toHaveTextContent('/w/10/tables/20/settings')

    fireEvent.click(screen.getByRole('tab', { name: /视图/ }))
    await waitFor(() => {
      expect(screen.getByTestId('location')).toHaveTextContent('/w/10/tables/20/settings?tab=views')
    })

    fireEvent.click(screen.getByRole('tab', { name: /基本信息/ }))
    await waitFor(() => {
      expect(screen.getByTestId('location')).toHaveTextContent('/w/10/tables/20/settings')
    })
    // 探针含 search，pathname 后可能带 ?，单独断言不包含 tab=views
    expect(screen.getByTestId('location')).not.toHaveTextContent('tab=views')
  })
})

describe('TableSettingsPage 视图列表（拖拽 + 默认）', () => {
  beforeEach(() => {
    setupTableHandlers()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('渲染拖拽手柄，仅非默认视图提供「设为默认视图」', async () => {
    renderPage(`/w/${WID}/tables/${TID}/settings?tab=views`)

    const row2 = await screen.findByTestId('ts-view-row-2', {}, { timeout: 5000 })
    within(row2).getByLabelText('拖拽排序 按状态')
    within(row2).getByRole('button', { name: '设为默认视图 按状态' })

    // 已是默认的视图不再展示该按钮（避免误操作）
    const row1 = screen.getByTestId('ts-view-row-1')
    expect(within(row1).queryByRole('button', { name: /设为默认视图/ })).toBeNull()
  })

  it('点击「设为默认视图」调用 PATCH 且仅携带 is_default', async () => {
    const updateSpy = vi.spyOn(viewApi, 'update').mockResolvedValue({
      id: 2, name: '按状态', view_type: 'kanban', is_default: true,
    } as View)

    renderPage(`/w/${WID}/tables/${TID}/settings?tab=views`)

    fireEvent.click(await screen.findByRole('button', { name: '设为默认视图 按状态' }, { timeout: 5000 }))

    await waitFor(() => expect(updateSpy).toHaveBeenCalledTimes(1))
    expect(updateSpy.mock.calls[0]![2]).toBe(2)
    expect(updateSpy.mock.calls[0]![3]).toEqual({ is_default: true })
  })
})

// ─────────────── 删除表后导航 ───────────────

describe('TableSettingsPage 删除表后导航', () => {
  beforeEach(() => {
    setupTableHandlers()
    server.use(
      http.delete('/api/v1/workspaces/:wid/tables/:tid', () => HttpResponse.json({})),
    )
  })

  it('删除表成功后提示成功并 navigate 到工作区表列表', async () => {
    renderPageWithProbe()

    // 等待「基本信息」Tab 表单回填（确认页面挂载完成）
    await screen.findByDisplayValue('任务表', {}, { timeout: 5000 })

    // 点击删除 → Popconfirm 弹窗
    fireEvent.click(screen.getByRole('button', { name: /删\s*除\s*表/ }))
    // Popconfirm 的「删除」按钮确认
    fireEvent.click(await screen.findByRole('button', { name: /^删\s*除$/ }))

    // 成功提示
    expect(await screen.findByText('表已删除')).toBeInTheDocument()

    // 关键断言：路由从 /w/10/tables/20/settings 跳回 /w/10/tables
    await waitFor(
      () => expect(screen.getByTestId('location')).toHaveTextContent(`/w/${WID}/tables`),
      { timeout: 3000 },
    )
  })

  it('删除表失败时停留在当前页，不 navigate', async () => {
    server.use(
      http.delete('/api/v1/workspaces/:wid/tables/:tid', () =>
        HttpResponse.json({ detail: '表不存在' }, { status: 404 }),
      ),
    )
    renderPageWithProbe()

    await screen.findByDisplayValue('任务表', {}, { timeout: 5000 })
    fireEvent.click(screen.getByRole('button', { name: /删\s*除\s*表/ }))
    fireEvent.click(await screen.findByRole('button', { name: /^删\s*除$/ }))

    expect(await screen.findByText('表不存在')).toBeInTheDocument()
    // 路由保持在表设置页
    expect(screen.getByTestId('location')).toHaveTextContent(`/w/${WID}/tables/${TID}/settings`)
  })
})

describe('TableSettingsPage 移动端适配', () => {
  beforeEach(() => {
    setupTableHandlers()
  })

  afterEach(() => {
    responsiveState = {
      deviceType: 'desktop', isMobile: false, isTablet: false, isDesktop: true,
      width: 1280, height: 800,
    }
  })

  it('窄屏下页签由左侧竖排改为顶部横排，统计条四项齐全', async () => {
    responsiveState = {
      deviceType: 'mobile', isMobile: true, isTablet: false, isDesktop: false,
      width: 390, height: 844,
    }
    renderPage()

    await screen.findByDisplayValue('任务表', {}, { timeout: 5000 })
    const tabs = document.querySelector('.table-settings-tabs') as HTMLElement
    expect(tabs.className).toContain('ant-tabs-top')
    expect(tabs.className).not.toContain('ant-tabs-left')
    // 统计条四项（字段 / 记录 / 视图 / 创建日期）都渲染，靠 CSS 换行不再被裁切
    expect(document.querySelectorAll('.ts-stats .ts-stat')).toHaveLength(4)
  })

  it('桌面端保持左侧竖排页签', async () => {
    renderPage()

    await screen.findByDisplayValue('任务表', {}, { timeout: 5000 })
    expect((document.querySelector('.table-settings-tabs') as HTMLElement).className).toContain('ant-tabs-left')
  })
})
