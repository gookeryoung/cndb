/**
 * WorkspaceSettingsModal 组件测试 —— Modal 包装层.
 *
 * 覆盖：open=false 不渲染 / open=true 渲染标题与内容 / 关闭按钮回调 /
 * 删除工作区成功后自动关闭 Modal 回到工作区列表视图。
 */

import { describe, expect, it, vi } from 'vitest'
import { http, HttpResponse } from 'msw'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import WorkspaceSettingsModal from './WorkspaceSettingsModal'
import { renderProviders } from '@/test/render-providers'
import { server } from '@/test/msw'
import { workspaceApi } from '@/api'

/** mock 工作区详情与成员列表，供 WorkspaceSettingsContent 基本设置 Tab 加载 */
function setupWorkspaceDetailHandler() {
  server.use(
    http.get('/api/v1/workspaces/:wid', () =>
      HttpResponse.json({
        id: 10, name: '测试', description: '', visibility: 'member', tags: [],
        allow_edit: true, created_by_id: 1, created_at: '', updated_at: '',
        owner: { id: 1, username: 'alice', nickname: null },
        table_count: 0, member_count: 1, view_count: 0, total_rows: 0,
        current_user_role: 'owner',
      }),
    ),
    http.get('/api/v1/workspaces/:wid/members', () => HttpResponse.json([])),
  )
}

describe('WorkspaceSettingsModal', () => {
  it('open=false 时不渲染任何内容', () => {
    renderProviders(
      <WorkspaceSettingsModal open={false} wid="10" onClose={() => { }} />,
    )

    expect(screen.queryByText('工作区设置')).not.toBeInTheDocument()
  })

  it('open=true 渲染标题、关闭按钮并加载设置内容', async () => {
    setupWorkspaceDetailHandler()
    renderProviders(
      <WorkspaceSettingsModal open wid="10" onClose={() => { }} />,
    )

    expect(screen.getByText('工作区设置')).toBeInTheDocument()
    // antd 两字按钮自动插入空格（"关 闭"），用正则兼容
    expect(screen.getByRole('button', { name: /^关\s*闭$/ })).toBeInTheDocument()
    // WorkspaceSettingsContent 基本设置 Tab 正常挂载
    // 注：rc-dialog 过渡期间 tab span 可能被判为不可见，这里断言存在性
    expect(await screen.findByText('基本设置')).toBeInTheDocument()
  })

  it('点击关闭按钮触发 onClose 回调', async () => {
    setupWorkspaceDetailHandler()
    const onClose = vi.fn()
    renderProviders(
      <WorkspaceSettingsModal open wid="10" onClose={onClose} />,
    )

    await waitFor(() => expect(screen.getByText('工作区设置')).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: /^关\s*闭$/ }))
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('owner 删除工作区成功后自动关闭 Modal 回到列表视图', async () => {
    setupWorkspaceDetailHandler()
    server.use(
      http.get('/api/v1/workspaces/10/members/candidates', () =>
        HttpResponse.json({ results: [] })),
    )
    const onClose = vi.fn()
    const removeSpy = vi.spyOn(workspaceApi, 'remove').mockResolvedValue(undefined as never)
    renderProviders(
      <WorkspaceSettingsModal open wid="10" onClose={onClose} />,
    )

    // 等基本设置 Tab 挂载（rc-dialog 过渡期可能判不可见，只断言存在性）
    await screen.findByText('基本设置')

    // 切到统计信息 Tab（危险操作区在此）
    fireEvent.click(screen.getByText('统计信息'))
    await screen.findByText('危险操作')

    // 点删除按钮并在 Popconfirm 中确认
    fireEvent.click(screen.getByRole('button', { name: /删除工作区/ }))
    await waitFor(() => {
      expect(document.querySelector('.ant-popconfirm')).not.toBeNull()
    }, { timeout: 5000 })
    const confirmBtn = document.querySelector(
      '.ant-popconfirm .ant-btn-dangerous, .ant-popconfirm .ant-btn-primary',
    )!
    fireEvent.click(confirmBtn)

    // 删除请求应已发出，但 onClose 未被调用（Modal 不关闭 —— RED）
    await waitFor(() => expect(removeSpy).toHaveBeenCalledWith('10'), { timeout: 5000 })
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1), { timeout: 5000 })

    removeSpy.mockRestore()
  }, 20000)
})
