/**
 * WorkspaceSettingsModal 组件测试 —— Modal 包装层.
 *
 * 覆盖：open=false 不渲染 / open=true 渲染标题与内容 / 关闭按钮回调。
 */

import { describe, expect, it, vi } from 'vitest'
import { http, HttpResponse } from 'msw'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import WorkspaceSettingsModal from './WorkspaceSettingsModal'
import { renderProviders } from '@/test/render-providers'
import { server } from '@/test/msw'

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
})
