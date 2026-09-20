/**
 * SettingsModal 组件测试 —— 个人设置（主题 + 操作风格）.
 *
 * 覆盖：Tab 结构 / 主题卡片选择持久化 / 操作风格下拉变更写入 store。
 */

import { describe, expect, it } from 'vitest'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import SettingsModal from './SettingsModal'
import { renderProviders } from '@/test/render-providers'
import { useTableSettingsStore } from '@/store'

describe('SettingsModal 个人设置', () => {
  it('渲染两个 Tab 与全部主题卡片（10 张）', () => {
    renderProviders(<SettingsModal open onClose={() => { }} />)

    expect(screen.getByRole('tab', { name: '主题' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: '操作风格' })).toBeInTheDocument()
    const grid = document.querySelector('[data-testid="theme-grid"]')
    expect(grid?.querySelectorAll('[data-theme-card]')).toHaveLength(10)
  })

  it('点击主题卡片切换主题并持久化到 localStorage', async () => {
    renderProviders(<SettingsModal open onClose={() => { }} />)

    const oceanCard = document.querySelector<HTMLElement>('[data-theme-card="ocean"]')
    expect(oceanCard).not.toBeNull()
    fireEvent.click(oceanCard!)

    await waitFor(() => expect(localStorage.getItem('cndb_theme')).toBe('ocean'))
    expect(oceanCard!.style.border).toContain('2px solid')
  })

  it('操作风格 Tab：新增行默认位置变更写入 store 与 localStorage', async () => {
    renderProviders(<SettingsModal open onClose={() => { }} />)

    // 切到操作风格 Tab
    fireEvent.click(screen.getByRole('tab', { name: '操作风格' }))
    expect(await screen.findByText('新增行默认位置')).toBeInTheDocument()

    // 默认为 tail（表格尾部），打开下拉切换为 top
    expect(useTableSettingsStore.getState().newRowPosition).toBe('tail')
    fireEvent.mouseDown(screen.getByText('表格尾部'))
    fireEvent.click(await screen.findByText('表格顶部'))

    await waitFor(() => expect(useTableSettingsStore.getState().newRowPosition).toBe('top'))
    // zustand persist 存储格式为 { state: {...}, version: 0 }
    const persisted = JSON.parse(localStorage.getItem('cndb_table_settings') ?? '{}') as {
      state?: { newRowPosition?: string }
    }
    expect(persisted.state?.newRowPosition).toBe('top')
  })
})
