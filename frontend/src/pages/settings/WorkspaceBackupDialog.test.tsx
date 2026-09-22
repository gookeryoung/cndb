/**
 * WorkspaceBackupDialog 组件测试 —— 工作区导入/导出.
 *
 * 覆盖：Tab 结构 / 导出下载（含 createObjectURL mock）/ 导入 JSON 成功 / 非 JSON 拒绝。
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
    expect(screen.queryByText('工作区导入 / 导出')).not.toBeInTheDocument()
  })

  it('open=true 渲染导出/导入两个 Tab', () => {
    renderProviders(<WorkspaceBackupDialog open wid="10" onClose={() => { }} />)

    expect(screen.getByText('工作区导入 / 导出')).toBeInTheDocument()
    expect(screen.getByText('导出工作区')).toBeInTheDocument()
    expect(screen.getByText('导入到工作区')).toBeInTheDocument()
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

    expect(await screen.findByText('已导出 1 张表')).toBeInTheDocument()
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

  it('导入 JSON 备份成功：显示导入统计并回调 onImported', async () => {
    const importSpy = vi.fn(() =>
      HttpResponse.json({ imported_tables: 2, imported_rows: 5, imported_views: 1 }))
    server.use(http.post('/api/v1/workspaces/10/import', importSpy))
    const onImported = vi.fn()
    renderProviders(
      <WorkspaceBackupDialog open wid="10" onClose={() => { }} onImported={onImported} />,
    )

    // 切到导入 Tab 并通过隐藏 input 上传文件
    fireEvent.click(screen.getByText('导入到工作区'))
    const input = document.querySelector('input[type="file"]') as HTMLInputElement
    expect(input).not.toBeNull()
    const file = new File([JSON.stringify({ tables: [] })], 'backup.json', { type: 'application/json' })
    Object.defineProperty(input, 'files', { value: [file] })
    fireEvent.change(input)

    expect(await screen.findByText(/导入完成：2 表 \/ 5 行 \/ 1 视图/)).toBeInTheDocument()
    expect(onImported).toHaveBeenCalledTimes(1)
  })

  it('上传非 JSON 文件被拒绝', async () => {
    renderProviders(<WorkspaceBackupDialog open wid="10" onClose={() => { }} />)

    fireEvent.click(screen.getByText('导入到工作区'))
    const input = document.querySelector('input[type="file"]') as HTMLInputElement
    const file = new File(['plain'], 'backup.txt', { type: 'text/plain' })
    Object.defineProperty(input, 'files', { value: [file] })
    fireEvent.change(input)

    expect(await screen.findByText('仅支持 JSON 文件')).toBeInTheDocument()
  })
})
