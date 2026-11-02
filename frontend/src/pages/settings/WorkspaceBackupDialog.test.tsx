/** WorkspaceBackupDialog 组件测试 —— 工作区备份（仅全量归档）.
 *
 * 覆盖：对话框标题 / 归档说明 / 含密钥开关 / 归档导出成功与失败。
 * 覆盖恢复已移入工作区列表页「导入工作区」（见 WorkspaceList.test.tsx）。
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

  it('open=true 仅展示全量归档备份，不再提供 JSON / 恢复入口', () => {
    renderProviders(
      <WorkspaceBackupDialog open wid="10" workspaceName="测试工作区" onClose={() => { }} />,
    )

    expect(screen.getByText('备份工作区')).toBeInTheDocument()
    expect(screen.getByText(/将备份整个工作区「测试工作区」的完整数据/)).toBeInTheDocument()
    expect(screen.getByText('下载全量归档（.tar.gz）')).toBeInTheDocument()
    expect(screen.queryByText('下载 JSON 备份')).not.toBeInTheDocument()
    expect(screen.queryByText('恢复到本工作区')).not.toBeInTheDocument()
    expect(screen.queryByText('危险操作：覆盖恢复')).not.toBeInTheDocument()
    // 恢复入口指引到「导入工作区」
    expect(screen.getByText('恢复到工作区请走「导入工作区」')).toBeInTheDocument()
  })

  it('归档导出成功：提示密钥已包含', async () => {
    server.use(
      http.get('/api/v1/workspaces/10/export/archive', ({ request }) => {
        expect(new URL(request.url).searchParams.get('include_secrets')).toBe('true')
        return new HttpResponse(new Uint8Array([0x1f, 0x8b]), {
          headers: { 'Content-Type': 'application/gzip' },
        })
      }),
    )
    renderProviders(
      <WorkspaceBackupDialog open wid="10" workspaceName="测试" onClose={() => { }} />,
    )

    fireEvent.click(screen.getByText('下载全量归档（.tar.gz）'))

    expect(await screen.findByText(/已下载全量归档（含密钥/)).toBeInTheDocument()
    expect(URL.createObjectURL).toHaveBeenCalled()
  })

  it('关闭密钥开关后导出：include_secrets=false', async () => {
    server.use(
      http.get('/api/v1/workspaces/10/export/archive', ({ request }) => {
        expect(new URL(request.url).searchParams.get('include_secrets')).toBe('false')
        return new HttpResponse(new Uint8Array([0x1f, 0x8b]))
      }),
    )
    renderProviders(
      <WorkspaceBackupDialog open wid="10" workspaceName="测试" onClose={() => { }} />,
    )

    fireEvent.click(screen.getByRole('switch'))
    fireEvent.click(screen.getByText('下载全量归档（.tar.gz）'))

    expect(await screen.findByText(/已下载全量归档（密钥已剔除）/)).toBeInTheDocument()
  })

  it('归档导出失败：显示后端错误消息', async () => {
    server.use(
      http.get('/api/v1/workspaces/10/export/archive', () =>
        HttpResponse.json({ detail: 'boom' }, { status: 500 })),
    )
    renderProviders(<WorkspaceBackupDialog open wid="10" onClose={() => { }} />)

    fireEvent.click(screen.getByText('下载全量归档（.tar.gz）'))

    expect(await screen.findByText('boom')).toBeInTheDocument()
  })
})
