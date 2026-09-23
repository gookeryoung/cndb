/**
 * WorkspaceBackupDialog 组件测试 —— 工作区备份（仅导出 JSON）.
 *
 * 覆盖：对话框标题 / 导出下载（含 createObjectURL mock）/ 导出失败。
 * 导入工作区功能已统一移至工作区列表页顶部按钮，见 WorkspaceList 组件。
 */

import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { http, HttpResponse } from 'msw'
import { fireEvent, screen } from '@testing-library/react'
import WorkspaceBackupDialog from './WorkspaceBackupDialog'
import { renderProviders } from '@/test/render-providers'
import { server } from '@/test/msw'

beforeEach(() => {
  // jsdom 未实现 createObjectURL/revokeObjectURL
  vi.stubGlobal('URL', Object.assign(URL, {
    createObjectURL: vi.fn(() => 'blob:fake'),
    revokeObjectURL: vi.fn(),
  }))
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('WorkspaceBackupDialog 工作区备份', () => {
  it('open=false 时不渲染', () => {
    renderProviders(<WorkspaceBackupDialog open={false} wid="10" onClose={() => { }} />)
    expect(screen.queryByText('备份工作区')).not.toBeInTheDocument()
  })

  it('open=true 渲染备份对话框（仅导出）', () => {
    renderProviders(
      <WorkspaceBackupDialog open wid="10" workspaceName="测试工作区" onClose={() => { }} />,
    )

    expect(screen.getByText('备份工作区')).toBeInTheDocument()
    expect(screen.getByText(/将备份整个工作区「测试工作区」的完整数据/)).toBeInTheDocument()
    expect(screen.getByText('下载 JSON 备份')).toBeInTheDocument()
  })

  it('导出成功：触发下载并提示表数量', async () => {
    server.use(
      http.get('/api/v1/workspaces/10/export', () =>
        HttpResponse.json({
          workspace: { id: 10, name: '测试' },
          tables: [{ id: 100, name: '客户表', fields: [], rows: [] }],
        })),
    )
    renderProviders(
      <WorkspaceBackupDialog open wid="10" workspaceName="测试" onClose={() => { }} />,
    )

    fireEvent.click(screen.getByText('下载 JSON 备份'))

    expect(await screen.findByText('已备份 1 张表')).toBeInTheDocument()
    expect(URL.createObjectURL).toHaveBeenCalled()
  })

  it('导出失败：显示错误消息', async () => {
    server.use(
      http.get('/api/v1/workspaces/10/export', () =>
        HttpResponse.json({ detail: 'boom' }, { status: 500 })),
    )
    renderProviders(<WorkspaceBackupDialog open wid="10" onClose={() => { }} />)

    fireEvent.click(screen.getByText('下载 JSON 备份'))

    // api 拦截器把后端 detail 提取为 Error.message（见 client.test.ts 约定）
    expect(await screen.findByText('boom')).toBeInTheDocument()
  })
})
