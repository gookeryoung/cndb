/**
 * WorkspaceBackupDialog 组件测试 —— 工作区备份（JSON 导出 + 全量归档 + 覆盖恢复）.
 *
 * 覆盖：对话框标题 / JSON 导出下载 / 导出失败 / 全量归档导出（含密钥开关）/
 * 恢复区仅 owner 可见 / 双重确认门禁 / 恢复成功。
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

  it('open=true 渲染备份对话框（JSON + 全量归档）', () => {
    renderProviders(
      <WorkspaceBackupDialog open wid="10" workspaceName="测试工作区" onClose={() => { }} />,
    )

    expect(screen.getByText('备份工作区')).toBeInTheDocument()
    expect(screen.getByText(/将备份整个工作区「测试工作区」的完整数据/)).toBeInTheDocument()
    expect(screen.getByText('下载 JSON 备份')).toBeInTheDocument()
    expect(screen.getByText('下载全量归档（.tar.gz）')).toBeInTheDocument()
  })

  it('JSON 导出成功：触发下载并提示表数量', async () => {
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

  it('JSON 导出失败：显示错误消息', async () => {
    server.use(
      http.get('/api/v1/workspaces/10/export', () =>
        HttpResponse.json({ detail: 'boom' }, { status: 500 })),
    )
    renderProviders(<WorkspaceBackupDialog open wid="10" onClose={() => { }} />)

    fireEvent.click(screen.getByText('下载 JSON 备份'))

    // api 拦截器把后端 detail 提取为 Error.message（见 client.test.ts 约定）
    expect(await screen.findByText('boom')).toBeInTheDocument()
  })

  it('全量归档导出成功：提示密钥已包含', async () => {
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
})

describe('WorkspaceBackupDialog 覆盖恢复', () => {
  it('非 owner 不显示恢复区', () => {
    renderProviders(
      <WorkspaceBackupDialog open wid="10" workspaceName="测试" currentUserRole="editor" onClose={() => { }} />,
    )
    expect(screen.queryByText('危险操作：覆盖恢复')).not.toBeInTheDocument()
  })

  it('owner 显示恢复区，未完成双重确认时按钮禁用', () => {
    renderProviders(
      <WorkspaceBackupDialog open wid="10" workspaceName="测试" currentUserRole="owner" onClose={() => { }} />,
    )
    expect(screen.getByText('危险操作：覆盖恢复')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /覆盖恢复本工作区/ })).toBeDisabled()
  })

  it('恢复成功：调用接口并关闭对话框', async () => {
    const file = new File([new Uint8Array([0x1f, 0x8b])], 'backup.tar.gz')
    const onClose = vi.fn()
    server.use(
      http.post('/api/v1/workspaces/10/restore', () =>
        HttpResponse.json({
          imported_tables: 3, imported_rows: 40, imported_views: 2, errors: [],
        })),
    )
    renderProviders(
      <WorkspaceBackupDialog open wid="10" workspaceName="测试" currentUserRole="owner" onClose={onClose} />,
    )

    // 选择文件（Modal 经 portal 渲染在 document.body）
    const input = document.querySelector('input[type="file"]') as HTMLInputElement | null
    expect(input).not.toBeNull()
    await fireEvent.change(input!, { target: { files: [file] } })

    // 勾选确认 + 输入工作区名
    fireEvent.click(screen.getByRole('checkbox'))
    fireEvent.change(screen.getByPlaceholderText(/输入工作区名称/), { target: { value: '测试' } })

    fireEvent.click(screen.getByText('覆盖恢复本工作区'))

    expect(await screen.findByText(/恢复完成：3 张表 · 40 行/)).toBeInTheDocument()
    expect(onClose).toHaveBeenCalled()
  })
})
