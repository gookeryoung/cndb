/**
 * GridViewBar 测试 —— 重点覆盖移动端视图切换可达性：
 * 视图页签占满剩余宽度、模式切换收进下拉、更多菜单承载次级入口、搜索折叠为第二行；
 * 同时回归桌面端原有布局（模式按钮组常显 + 搜索常显）。
 */

import { describe, expect, it, vi, beforeEach } from 'vitest'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import { AppstoreOutlined, ColumnHeightOutlined, CalendarOutlined } from '@ant-design/icons'

import type { ResponsiveState } from '@/hooks/useResponsive'
import type { View } from '@/api'
import { renderProviders } from '@/test/render-providers'
import GridViewBar from './gridViewBar'
import type { ViewMode } from './views/viewModes'

let responsiveState: ResponsiveState = {
  deviceType: 'desktop', isMobile: false, isTablet: false, isDesktop: true,
  width: 1280, height: 800,
}
vi.mock('@/hooks/useResponsive', async () => {
  const actual = await vi.importActual<typeof import('@/hooks/useResponsive')>('@/hooks/useResponsive')
  return { ...actual, useResponsive: () => responsiveState }
})

const VIEWS: View[] = [
  { id: 1, name: '全部记录', view_type: 'grid', is_default: true, owner_id: null },
  { id: 2, name: '本月进行中', view_type: 'kanban', is_default: false, owner_id: null },
  { id: 3, name: '我的待办', view_type: 'grid', is_default: false, owner_id: 9 },
]

const MODE_BUTTONS = [
  { mode: 'grid' as ViewMode, label: '表格', tooltip: '表格 (Grid)', icon: <ColumnHeightOutlined /> },
  { mode: 'kanban' as ViewMode, label: '看板', tooltip: '看板 (Kanban)', icon: <AppstoreOutlined /> },
  { mode: 'calendar' as ViewMode, label: '日历', tooltip: '日历 (Calendar)', icon: <CalendarOutlined /> },
]

function renderBar(overrides: Partial<React.ComponentProps<typeof GridViewBar>> = {}) {
  const props = {
    wid: '10',
    tid: '100',
    views: VIEWS,
    activeViewId: 1,
    mode: 'grid' as ViewMode,
    modeButtons: MODE_BUTTONS,
    showModeSwitch: true,
    hasFilters: false,
    hasSorts: false,
    searchQuery: '',
    onSearchChange: vi.fn(),
    onSelectView: vi.fn(),
    onModeChange: vi.fn(),
    onDragEnd: vi.fn(),
    canManageViews: true,
    onCreate: vi.fn(),
    onEdit: vi.fn(),
    onDelete: vi.fn(),
    onImport: vi.fn(),
    onOpenViewConfig: vi.fn(),
    onOpenTableSettings: vi.fn(),
    ...overrides,
  }
  const utils = renderProviders(<GridViewBar {...props} />, { route: '/w/10/tables/100' })
  return { ...utils, props }
}

beforeEach(() => {
  responsiveState = {
    deviceType: 'desktop', isMobile: false, isTablet: false, isDesktop: true,
    width: 1280, height: 800,
  }
})

describe('GridViewBar 桌面端', () => {
  it('模式按钮组与搜索输入常显，视图页签可点选', () => {
    const { props } = renderBar()

    expect(screen.getByTestId('view-mode-switch')).toBeInTheDocument()
    expect(screen.getByTestId('view-search-input')).toBeInTheDocument()
    // 桌面端不出现移动端专用控件
    expect(screen.queryByTestId('view-mode-dropdown')).toBeNull()
    expect(screen.queryByTestId('view-more-btn')).toBeNull()

    fireEvent.click(screen.getByTestId('view-tab-2'))
    expect(props.onSelectView).toHaveBeenCalledWith(VIEWS[1])
  })
})

describe('GridViewBar 移动端', () => {
  beforeEach(() => {
    responsiveState = {
      deviceType: 'mobile', isMobile: true, isTablet: false, isDesktop: false,
      width: 390, height: 844,
    }
  })

  it('视图页签全部可见可点，右侧仅保留模式/筛选/更多三个控件', () => {
    const { props } = renderBar()

    expect(screen.getByTestId('view-tab-1')).toBeInTheDocument()
    expect(screen.getByTestId('view-tab-2')).toBeInTheDocument()
    expect(screen.getByTestId('view-tab-3')).toBeInTheDocument()
    // 移动端专用控件
    expect(screen.getByTestId('view-mode-dropdown')).toBeInTheDocument()
    expect(screen.getByTestId('view-more-btn')).toBeInTheDocument()
    expect(screen.getByTestId('view-filter-btn')).toBeInTheDocument()
    // 桌面端的常显模式按钮组与搜索框不再占据同一行
    expect(screen.queryByTestId('view-mode-switch')).toBeNull()
    expect(screen.queryByTestId('view-search-input')).toBeNull()

    fireEvent.click(screen.getByTestId('view-tab-2'))
    expect(props.onSelectView).toHaveBeenCalledWith(VIEWS[1])
  })

  it('模式下拉列出全部可用模式并触发切换', async () => {
    const { props } = renderBar()

    fireEvent.click(screen.getByTestId('view-mode-dropdown'))

    expect(await screen.findByTestId('view-mode-item-grid')).toHaveTextContent('表格')
    expect(screen.getByTestId('view-mode-item-kanban')).toHaveTextContent('看板')
    expect(screen.getByTestId('view-mode-item-calendar')).toHaveTextContent('日历')

    fireEvent.click(screen.getByTestId('view-mode-item-kanban'))
    await waitFor(() => expect(props.onModeChange).toHaveBeenCalledWith('kanban'))
  })

  it('仅一种视图类型时不渲染模式下拉', () => {
    renderBar({ modeButtons: [MODE_BUTTONS[0]!], showModeSwitch: false })
    expect(screen.queryByTestId('view-mode-dropdown')).toBeNull()
  })

  it('「更多」菜单承载新建/编辑/删除/导入/导出/表格设置等次级入口', async () => {
    const { props } = renderBar()

    fireEvent.click(screen.getByTestId('view-more-btn'))

    for (const label of ['新建视图', '编辑当前视图', '删除当前视图', '导入视图', '导出视图', '搜索当前视图', '表格设置']) {
      expect(await screen.findByText(label)).toBeInTheDocument()
    }
    fireEvent.click(screen.getByText('新建视图'))
    await waitFor(() => expect(props.onCreate).toHaveBeenCalled())

    fireEvent.click(screen.getByTestId('view-more-btn'))
    fireEvent.click(await screen.findByText('编辑当前视图'))
    await waitFor(() => expect(props.onEdit).toHaveBeenCalled())

    fireEvent.click(screen.getByTestId('view-more-btn'))
    fireEvent.click(await screen.findByText('表格设置'))
    await waitFor(() => expect(props.onOpenTableSettings).toHaveBeenCalled())
  })

  it('「更多 → 搜索当前视图」展开搜索行并回传输入', async () => {
    const { props } = renderBar()

    expect(screen.queryByTestId('view-search-row')).toBeNull()

    fireEvent.click(screen.getByTestId('view-more-btn'))
    fireEvent.click(await screen.findByText('搜索当前视图'))

    const input = await screen.findByTestId('view-search-input')
    fireEvent.change(input, { target: { value: '客户' } })
    expect(props.onSearchChange).toHaveBeenCalledWith('客户')
  })

  it('搜索词非空时搜索行保持展开（不隐藏已生效的过滤条件）', () => {
    renderBar({ searchQuery: '关键客户' })

    expect(screen.getByTestId('view-search-row')).toBeInTheDocument()
    expect(screen.getByTestId('view-search-input')).toHaveValue('关键客户')
  })

  it('无视图管理权限时公共视图的编辑入口禁用，个人视图仍可编辑', async () => {
    const { unmount } = renderBar({ canManageViews: false, activeViewId: 1 })

    fireEvent.click(screen.getByTestId('view-more-btn'))
    const publicEdit = (await screen.findByText('编辑当前视图')).closest('li')
    expect(publicEdit).toHaveClass('ant-dropdown-menu-item-disabled')
    unmount()

    renderBar({ canManageViews: false, activeViewId: 3 })
    fireEvent.click(screen.getByTestId('view-more-btn'))
    const ownEdit = (await screen.findByText('编辑当前视图')).closest('li')
    expect(ownEdit).not.toHaveClass('ant-dropdown-menu-item-disabled')
  })

  it('视图标签三态：private=我的 / shared=指定成员 / table 不带标签', () => {
    const triViews: View[] = [
      { id: 11, name: '公开视角', view_type: 'grid', is_default: false, owner_id: 9, visibility: 'table' },
      { id: 12, name: '共享视角', view_type: 'grid', is_default: false, owner_id: 9, visibility: 'shared', grantee_count: 3 },
      { id: 13, name: '私有视角', view_type: 'grid', is_default: false, owner_id: 9, visibility: 'private' },
    ]
    renderBar({ views: triViews, activeViewId: 11 })

    const table = screen.getByTestId('view-tab-11')
    expect(table).not.toHaveTextContent('我的')
    expect(table).not.toHaveTextContent('指定成员')
    // table 档视图同样带 owner_id（创建者），因此**不能**用 owner_id != null 判「我的」
    expect(screen.getByTestId('view-tab-12')).toHaveTextContent('指定成员')
    expect(screen.getByTestId('view-tab-13')).toHaveTextContent('我的')
  })

  it('「更多 → 视图权限」按后端下发的 can_manage 门控（不自行用 visibility/owner_id 推断）', async () => {
    // 后端明确 can_manage=false（例如只读用户看他人表内可见视图）→ 置灰
    const deniedViews: View[] = [
      { id: 1, name: '全部记录', view_type: 'grid', is_default: true, owner_id: 9, visibility: 'table', can_manage: false },
    ]
    const { unmount } = renderBar({ views: deniedViews, activeViewId: 1, canManageViews: false })
    fireEvent.click(screen.getByTestId('view-more-btn'))
    expect((await screen.findByText('视图权限')).closest('li')).toHaveClass('ant-dropdown-menu-item-disabled')
    unmount()

    // can_manage=true 时可点
    const ownViews: View[] = [
      { id: 3, name: '我的待办', view_type: 'grid', is_default: false, owner_id: 9, visibility: 'private', can_manage: true },
    ]
    renderBar({ views: ownViews, activeViewId: 3, canManageViews: false })
    fireEvent.click(screen.getByTestId('view-more-btn'))
    expect((await screen.findByText('视图权限')).closest('li')).not.toHaveClass('ant-dropdown-menu-item-disabled')
  })
})
