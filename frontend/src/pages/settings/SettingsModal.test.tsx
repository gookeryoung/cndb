/**
 * SettingsModal 组件测试 —— 个人设置（用户资料 + 主题/字体 + 表格）.
 *
 * 覆盖：Tab 结构与 initialTab 定位 / 用户资料紧凑表单（用户名只读）保存 /
 * 主题卡片选择持久化 / 字体设置（字号/加粗）持久化 /
 * 表格页签：显示模式（间距/每页）即时生效写 store /
 * 操作风格（新增行位置）写入 store / 恢复默认。
 */

import { describe, expect, it, vi, beforeEach } from 'vitest'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import SettingsModal from './SettingsModal'
import { renderProviders } from '@/test/render-providers'
import { useTableSettingsStore, useAuthStore } from '@/store'
import { DEFAULT_TABLE_SETTINGS } from '@/theme/tableSettings'

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
    localStorage.clear()
    useAuthStore.setState({ user: null, token: null, loading: false, expired: false })
    // 表格设置 store 复位为默认值（保留 action）
    const { updateSettings, resetSettings, ...rest } = useTableSettingsStore.getState()
    void updateSettings
    void resetSettings
    useTableSettingsStore.setState({ ...rest, ...DEFAULT_TABLE_SETTINGS })
  })

  it('渲染三个 Tab 与全部主题卡片（10 张），主题页含配色与字体两节', () => {
    renderProviders(<SettingsModal open onClose={() => { }} />)

    expect(screen.getByRole('tab', { name: '用户资料' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: '主题' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: '表格' })).toBeInTheDocument()
    // 主题卡片惰性渲染，切到主题 Tab 后才能查到
    fireEvent.click(screen.getByRole('tab', { name: '主题' }))
    const grid = document.querySelector('[data-testid="theme-grid"]')
    expect(grid?.querySelectorAll('[data-theme-card]')).toHaveLength(10)
    // 首节标题为「配色」（不再叫「主题」），并新增「字体」节
    expect(screen.getByText('配色')).toBeInTheDocument()
    expect(screen.getByText('字体')).toBeInTheDocument()
  })

  it('initialTab="table" 打开时直接定位表格页签', () => {
    renderProviders(<SettingsModal open initialTab="table" onClose={() => { }} />)

    // 页签激活态在 .ant-tabs-tab 容器上（role=tab 命中的是内部 .ant-tabs-tab-btn）
    const activeTab = document.querySelector('.ant-tabs-tab.ant-tabs-tab-active')
    expect(activeTab?.textContent).toContain('表格')
    // 表格页签内容直接可见（显示模式 + 操作风格两节）
    expect(screen.getByText('显示模式')).toBeInTheDocument()
    expect(screen.getByText('操作风格')).toBeInTheDocument()
    expect(screen.getByText('新增行默认位置')).toBeInTheDocument()
  })

  it('用户资料 Tab：用户名只读，昵称邮箱同行紧凑排布，保存后刷新 auth store', async () => {
    const refreshSpy = vi.spyOn(useAuthStore.getState(), 'refresh').mockResolvedValue(undefined)
    renderProviders(<SettingsModal open onClose={() => { }} />, {
      initialAuth: { user: profileUser, token: 't' },
    })

    fireEvent.click(screen.getByRole('tab', { name: '用户资料' }))

    // 用户名只读且展示当前账号，附不可修改说明
    const usernameInput = screen.getByLabelText('用户名') as HTMLInputElement
    expect(usernameInput).toHaveValue('me')
    expect(usernameInput).toBeDisabled()
    expect(screen.getByText('注册后不可修改')).toBeInTheDocument()
    // 不再有重复的「个人资料」节标题
    expect(screen.queryByText('个人资料')).not.toBeInTheDocument()

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

    // 默认 Tab 为用户资料，先切到主题 Tab
    fireEvent.click(screen.getByRole('tab', { name: '主题' }))
    const oceanCard = document.querySelector<HTMLElement>('[data-theme-card="ocean"]')
    expect(oceanCard).not.toBeNull()
    fireEvent.click(oceanCard!)

    await waitFor(() => expect(localStorage.getItem('cndb_theme')).toBe('ocean'))
    expect(oceanCard!.style.border).toContain('2px solid')
  })

  it('字体节：切换字号档位持久化到 localStorage 并同步 body 字号', async () => {
    renderProviders(<SettingsModal open onClose={() => { }} />)

    fireEvent.click(screen.getByRole('tab', { name: '主题' }))
    // mousedown 需派发到 rc-select 的 combobox 输入元素才能打开下拉
    fireEvent.mouseDown(screen.getByRole('combobox'))
    fireEvent.click(await screen.findByText('大', { selector: '.ant-select-item-option-content' }))

    await waitFor(() => {
      const persisted = JSON.parse(localStorage.getItem('cndb_font') ?? '{}') as { scale?: string }
      expect(persisted.scale).toBe('large')
    })
    expect(document.body.style.fontSize).toBe('16px')
  })

  it('字体节：开启全局加粗持久化到 localStorage 并同步 body 字重', async () => {
    renderProviders(<SettingsModal open onClose={() => { }} />)

    fireEvent.click(screen.getByRole('tab', { name: '主题' }))
    fireEvent.click(document.querySelector<HTMLElement>('[data-testid="font-bold-switch"]')!)

    await waitFor(() => {
      const persisted = JSON.parse(localStorage.getItem('cndb_font') ?? '{}') as { bold?: boolean }
      expect(persisted.bold).toBe(true)
    })
    expect(document.body.style.fontWeight).toBe('600')
  })

  it('表格 Tab：切换间距与每页行数即时写入 store 与 localStorage', async () => {
    renderProviders(<SettingsModal open initialTab="table" onClose={() => { }} />)

    // 间距：适中 → 紧凑（mousedown 派发到选中值文本，冒泡至选择器打开下拉）
    expect(useTableSettingsStore.getState().density).toBe('comfortable')
    fireEvent.mouseDown(screen.getByText('适中'))
    fireEvent.click(await screen.findByText('紧凑', { selector: '.ant-select-item-option-content' }))

    // 每页行数：50 → 100
    fireEvent.mouseDown(screen.getByText('50 条'))
    fireEvent.click(await screen.findByText('100 条', { selector: '.ant-select-item-option-content' }))

    await waitFor(() => {
      expect(useTableSettingsStore.getState().density).toBe('compact')
      expect(useTableSettingsStore.getState().defaultPageSize).toBe(100)
    })
    const persisted = JSON.parse(localStorage.getItem('cndb_table_settings') ?? '{}') as {
      state?: { density?: string; defaultPageSize?: number }
    }
    expect(persisted.state?.density).toBe('compact')
    expect(persisted.state?.defaultPageSize).toBe(100)
  })

  it('表格 Tab：新增行默认位置变更写入 store 与 localStorage', async () => {
    renderProviders(<SettingsModal open initialTab="table" onClose={() => { }} />)

    // 默认为 tail（表格尾部），打开下拉切换为 top
    expect(useTableSettingsStore.getState().newRowPosition).toBe('tail')
    fireEvent.mouseDown(screen.getByText('表格尾部'))
    fireEvent.click(await screen.findByText('表格顶部', { selector: '.ant-select-item-option-content' }))

    await waitFor(() => expect(useTableSettingsStore.getState().newRowPosition).toBe('top'))
    // zustand persist 存储格式为 { state: {...}, version: 0 }
    const persisted = JSON.parse(localStorage.getItem('cndb_table_settings') ?? '{}') as {
      state?: { newRowPosition?: string }
    }
    expect(persisted.state?.newRowPosition).toBe('top')
  })

  it('表格 Tab：恢复默认重置全部设置项', async () => {
    useTableSettingsStore.getState().updateSettings({ density: 'spacious', defaultPageSize: 200, newRowPosition: 'top' })
    renderProviders(<SettingsModal open initialTab="table" onClose={() => { }} />)

    fireEvent.click(screen.getByRole('button', { name: '恢复默认' }))

    await waitFor(() => {
      expect(useTableSettingsStore.getState().density).toBe('comfortable')
      expect(useTableSettingsStore.getState().defaultPageSize).toBe(DEFAULT_TABLE_SETTINGS.defaultPageSize)
      expect(useTableSettingsStore.getState().newRowPosition).toBe('tail')
    })
    expect(screen.getByText('适中')).toBeInTheDocument()
  })
})
