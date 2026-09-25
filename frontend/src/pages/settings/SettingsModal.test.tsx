/**
 * SettingsModal 组件测试 —— 个人设置（个人资料 + 主题 + 操作风格）.
 *
 * 覆盖：Tab 结构 / 个人资料表单保存 / 主题卡片选择持久化 / 操作风格下拉变更写入 store。
 */

import { describe, expect, it, vi, beforeEach } from 'vitest'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import SettingsModal from './SettingsModal'
import { renderProviders } from '@/test/render-providers'
import { useTableSettingsStore, useAuthStore } from '@/store'

// mock authApi，避免真实网络请求
vi.mock('@/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api')>()
  return {
    ...actual,
    authApi: {
      ...actual.authApi,
      updateProfile: vi.fn().mockResolvedValue({ id: 1, username: 'me', nickname: '新昵称', email: 'me@x.com' }),
      me: vi.fn().mockResolvedValue({ id: 1, username: 'me', nickname: '新昵称', email: 'me@x.com' }),
    },
  }
})

const profileUser = {
  id: 1,
  username: 'me',
  nickname: '旧昵称',
  email: 'old@x.com',
  role: 'user' as const,
}

describe('SettingsModal 个人设置', () => {
  beforeEach(() => {
    useAuthStore.setState({ user: null, token: null, loading: false, expired: false })
  })

  it('渲染三个 Tab 与全部主题卡片（10 张）', () => {
    renderProviders(<SettingsModal open onClose={() => { }} />)

    expect(screen.getByRole('tab', { name: '个人资料' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: '主题' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: '操作风格' })).toBeInTheDocument()
    // 主题卡片惰性渲染，切到主题 Tab 后才能查到
    fireEvent.click(screen.getByRole('tab', { name: '主题' }))
    const grid = document.querySelector('[data-testid="theme-grid"]')
    expect(grid?.querySelectorAll('[data-theme-card]')).toHaveLength(10)
  })

  it('个人资料 Tab：展示当前用户并保存昵称邮箱后刷新 auth store', async () => {
    const refreshSpy = vi.spyOn(useAuthStore.getState(), 'refresh').mockResolvedValue(undefined)
    renderProviders(<SettingsModal open onClose={() => { }} />, {
      initialAuth: { user: profileUser, token: 't' },
    })

    fireEvent.click(screen.getByRole('tab', { name: '个人资料' }))
    expect(await screen.findByText('用户名：me（不可修改）')).toBeInTheDocument()

    const nicknameInput = screen.getByLabelText('昵称')
    expect(nicknameInput).toHaveValue('旧昵称')
    fireEvent.change(nicknameInput, { target: { value: '新昵称' } })
    fireEvent.change(screen.getByLabelText('邮箱'), { target: { value: 'me@x.com' } })
    fireEvent.click(screen.getByRole('button', { name: '保 存' }))

    const { authApi } = await import('@/api')
    await waitFor(() =>
      expect(authApi.updateProfile).toHaveBeenCalledWith({ nickname: '新昵称', email: 'me@x.com' }),
    )
    await waitFor(() => expect(refreshSpy).toHaveBeenCalled())
    refreshSpy.mockRestore()
  })

  it('点击主题卡片切换主题并持久化到 localStorage', async () => {
    renderProviders(<SettingsModal open onClose={() => { }} />)

    // 默认 Tab 为个人资料，先切到主题 Tab
    fireEvent.click(screen.getByRole('tab', { name: '主题' }))
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
