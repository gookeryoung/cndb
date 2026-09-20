/**
 * TableSettingsDialog 组件测试 —— 表格显示设置.
 *
 * 覆盖：设置项回显 / 修改后保存写入 store / 重置默认 / 取消不落盘。
 */

import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import TableSettingsDialog from './TableSettingsDialog'
import { renderProviders } from '@/test/render-providers'
import { useTableSettingsStore } from '@/store'
import { DEFAULT_TABLE_SETTINGS } from '@/theme/tableSettings'

beforeEach(() => {
  // 用例间复位 store（保留 action）
  const { updateSettings, resetSettings, ...rest } = useTableSettingsStore.getState()
  void updateSettings
  void resetSettings
  useTableSettingsStore.setState({ ...rest, ...DEFAULT_TABLE_SETTINGS })
})

describe('TableSettingsDialog 显示模式设置', () => {
  it('open=true 渲染三个开关与标题', () => {
    renderProviders(<TableSettingsDialog open onClose={() => { }} />)

    expect(screen.getByText('显示模式')).toBeInTheDocument()
    expect(screen.getByText('边框')).toBeInTheDocument()
    expect(screen.getByText('表头')).toBeInTheDocument()
    expect(screen.getByText('斑马纹')).toBeInTheDocument()
  })

  it('修改间距与每页行数后保存写入 store 并回调 onClose', async () => {
    const onClose = vi.fn()
    renderProviders(<TableSettingsDialog open onClose={onClose} />)

    // 间距：适中 → 紧凑
    fireEvent.mouseDown(screen.getByText('适中'))
    fireEvent.click(await screen.findByText('紧凑'))
    // 每页行数：50 → 100
    fireEvent.mouseDown(screen.getByText('50 条'))
    fireEvent.click(await screen.findByText('100 条'))

    // antd 两字按钮自动插空格（“保 存”），用正则匹配
    fireEvent.click(screen.getByRole('button', { name: /^保\s*存$/ }))

    await waitFor(() => {
      expect(useTableSettingsStore.getState().density).toBe('compact')
      expect(useTableSettingsStore.getState().defaultPageSize).toBe(100)
    })
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('开关切换后保存写入 store', async () => {
    renderProviders(<TableSettingsDialog open onClose={() => { }} />)

    // 边框默认 false → 打开
    fireEvent.click(screen.getByText('边框'))
    fireEvent.click(screen.getByRole('button', { name: /^保\s*存$/ }))

    await waitFor(() => expect(useTableSettingsStore.getState().bordered).toBe(true))
  })

  it('重置默认恢复所有设置项', async () => {
    useTableSettingsStore.getState().updateSettings({ density: 'spacious', bordered: true })
    renderProviders(<TableSettingsDialog open onClose={() => { }} />)

    fireEvent.click(screen.getByText('重置默认'))

    await waitFor(() => {
      expect(useTableSettingsStore.getState().density).toBe('comfortable')
      expect(useTableSettingsStore.getState().bordered).toBe(false)
    })
    expect(screen.getByText('适中')).toBeInTheDocument()
  })

  it('取消关闭对话框但不保存草稿修改', async () => {
    const onClose = vi.fn()
    renderProviders(<TableSettingsDialog open onClose={onClose} />)

    fireEvent.mouseDown(screen.getByText('适中'))
    fireEvent.click(await screen.findByText('紧凑'))
    fireEvent.click(screen.getByRole('button', { name: /^取\s*消$/ }))

    expect(onClose).toHaveBeenCalledTimes(1)
    expect(useTableSettingsStore.getState().density).toBe('comfortable')
  })
})
