/**
 * GridToolbar 测试 —— 重点覆盖窄屏收纳：
 * 桌面端「表设置 / 更新导出 / 数据治理」常显 + 记录数徽标；
 * 窄屏隐藏记录徽标与常显按钮，能力前置到「更多」菜单，标题留出宽度。
 */

import { afterEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, screen, waitFor } from '@testing-library/react'

import type { ResponsiveState } from '@/hooks/useResponsive'
import { renderProviders } from '@/test/render-providers'
import GridToolbar from './gridToolbar'

// 可控 useResponsive mock：默认桌面端，移动端用例在其内部切换
let responsiveState: ResponsiveState = {
  deviceType: 'desktop', isMobile: false, isTablet: false, isDesktop: true,
  width: 1280, height: 800,
}
vi.mock('@/hooks/useResponsive', async () => {
  const actual = await vi.importActual<typeof import('@/hooks/useResponsive')>('@/hooks/useResponsive')
  return { ...actual, useResponsive: () => responsiveState }
})

function renderToolbar(overrides: Partial<React.ComponentProps<typeof GridToolbar>> = {}) {
  const props = {
    wid: '10',
    tid: '20',
    tableKey: 'w10-t20',
    tableName: '产品开发',
    recordCount: 500,
    mode: 'grid',
    addRowDisabled: false,
    onAddRow: vi.fn(),
    permissionLabel: '可编辑',
    onEditRow: vi.fn(),
    editRowDisabled: false,
    canEditSchema: true,
    canManageData: true,
    onOpenTableSettings: vi.fn(),
    onOpenImportExport: vi.fn(),
    onOpenGovernance: vi.fn(),
    activeViewName: '全部',
    activeViewId: 1,
    onCopyTable: vi.fn(),
    onMove: vi.fn(),
    onResetColumnLayout: vi.fn(),
    ...overrides,
  }
  const utils = renderProviders(<GridToolbar {...props} />, { route: '/w/10/tables/20' })
  return { ...utils, props }
}

const resetResponsive = () => {
  responsiveState = {
    deviceType: 'desktop', isMobile: false, isTablet: false, isDesktop: true,
    width: 1280, height: 800,
  }
}

afterEach(resetResponsive)

describe('GridToolbar 桌面端', () => {
  it('常显表设置 / 更新导出 / 数据治理与记录数徽标', () => {
    renderToolbar()

    expect(screen.getByText('产品开发')).toBeInTheDocument()
    expect(screen.getByText('500 条记录')).toBeInTheDocument()
    expect(screen.getByTestId('add-row-btn')).toBeInTheDocument()
    expect(screen.getByTestId('edit-row-btn')).toBeInTheDocument()
    expect(screen.getByTestId('table-settings-btn')).toBeInTheDocument()
    expect(screen.getByTestId('import-export-btn')).toBeInTheDocument()
    expect(screen.getByTestId('governance-btn')).toBeInTheDocument()
  })
})

describe('GridToolbar 移动端', () => {
  it('隐藏记录徽标与常显按钮，仅保留新增行 + 更多', async () => {
    responsiveState = {
      deviceType: 'mobile', isMobile: true, isTablet: false, isDesktop: false,
      width: 390, height: 844,
    }
    renderToolbar()

    expect(screen.getByText('产品开发')).toBeInTheDocument()
    expect(screen.getByTestId('add-row-btn')).toBeInTheDocument()
    expect(screen.getByTestId('grid-more-menu')).toBeInTheDocument()
    // 记录数徽标隐藏（底部「共 N 条」已给出），常显按钮收进菜单
    expect(screen.queryByText('500 条记录')).toBeNull()
    expect(screen.queryByTestId('table-settings-btn')).toBeNull()
    expect(screen.queryByTestId('import-export-btn')).toBeNull()
    expect(screen.queryByTestId('governance-btn')).toBeNull()
    expect(screen.queryByTestId('edit-row-btn')).toBeNull()
    // 权限徽标保留（只读/可编辑对移动端用户同样关键）
    expect(screen.getByTestId('table-permission-pill')).toBeInTheDocument()
  })

  it('「更多」菜单前置编辑行 / 表设置 / 更新导出 / 数据治理并可触发', async () => {
    responsiveState = {
      deviceType: 'mobile', isMobile: true, isTablet: false, isDesktop: false,
      width: 390, height: 844,
    }
    const { props } = renderToolbar()

    fireEvent.click(screen.getByTestId('grid-more-menu'))

    for (const label of ['编辑行', '表设置', '更新 / 导出', '数据治理', '刷新', '复制表', '移动到其他工作区', '删除表']) {
      expect(await screen.findByText(label)).toBeInTheDocument()
    }

    fireEvent.click(screen.getByText('编辑行'))
    await waitFor(() => expect(props.onEditRow).toHaveBeenCalled())

    fireEvent.click(screen.getByTestId('grid-more-menu'))
    fireEvent.click(await screen.findByText('表设置'))
    await waitFor(() => expect(props.onOpenTableSettings).toHaveBeenCalled())

    fireEvent.click(screen.getByTestId('grid-more-menu'))
    fireEvent.click(await screen.findByText('更新 / 导出'))
    await waitFor(() => expect(props.onOpenImportExport).toHaveBeenCalled())

    fireEvent.click(screen.getByTestId('grid-more-menu'))
    fireEvent.click(await screen.findByText('数据治理'))
    await waitFor(() => expect(props.onOpenGovernance).toHaveBeenCalled())
  })

  it('非 grid 模式（如看板）不提供编辑行入口', async () => {
    responsiveState = {
      deviceType: 'mobile', isMobile: true, isTablet: false, isDesktop: false,
      width: 390, height: 844,
    }
    renderToolbar({ mode: 'kanban' })

    expect(screen.queryByTestId('add-row-btn')).toBeNull()
    fireEvent.click(screen.getByTestId('grid-more-menu'))
    expect(await screen.findByText('表设置')).toBeInTheDocument()
    expect(screen.queryByText('编辑行')).toBeNull()
  })
})
