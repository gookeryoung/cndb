/**
 * AdminPanel 页面组件测试 —— 系统管理台.
 *
 * 覆盖：非管理员 403 拦截 / 系统信息渲染 / 备份成功与失败回调 / 恢复文件校验摘要.
 */

import { describe, expect, it, vi, afterEach } from 'vitest'
import { http, HttpResponse } from 'msw'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import AdminPanel from './AdminPanel'
import * as apiModule from '@/api'
import { renderProviders } from '@/test/render-providers'
import { server, mockUser } from '@/test/msw'
import type { BackupManifest } from '@/api'

afterEach(() => {
  vi.restoreAllMocks()
})

const INFO = {
  app_name: 'cndb',
  app_version: '1.2.3',
  database_url: 'sqlite:///data/cndb.db',
  upload_dir: '/data/uploads',
  data_dir: '/data',
  auth_enabled: true,
  timezone: 'Asia/Shanghai',
}

const MANIFEST: BackupManifest = {
  version: '1.0',
  app_version: '1.2.3',
  created_at: '2026-01-01T08:00:00Z',
  database: {
    path: '/data/cndb.db',
    db_type: 'sqlite',
    backup_mode: 'native',
    tables: ['workspaces', 'tables'],
    row_counts: { workspaces: 3, tables: 5 },
    schema_version: '6399e5f0f61f',
    fallback_mode: 'sqlalchemy',
  },
  uploads: { included: true, file_count: 2, total_size: 2048 },
  schema_known: true,
  backup_ahead: false,
}

function renderPanel(user = mockUser) {
  return renderProviders(<AdminPanel />, { route: '/admin', initialAuth: { user, token: 'fake-token' } })
}

/** 切换到指定 Tab（label 含图标 aria-label 前缀，正则不锚定开头） */
async function activateTab(name: RegExp) {
  fireEvent.click(screen.getByRole('tab', { name }))
  await waitFor(() => expect(screen.getByRole('tab', { name })).toHaveAttribute('aria-selected', 'true'))
}

describe('AdminPanel 系统管理台', () => {
  it('非系统管理员显示无权访问提示且不发起管理端请求', async () => {
    renderPanel({ id: 2, username: 'bob', email: null, role: 'user', is_active: true })

    // 若误发 /api/v1/admin/info 请求，MSW onUnhandledRequest: 'error' 会直接报错
    expect(await screen.findByText('无权访问系统管理台')).toBeInTheDocument()
  })

  it('管理员加载并展示系统运行信息', async () => {
    server.use(http.get('/api/v1/admin/info', () => HttpResponse.json(INFO)))
    renderPanel()

    expect(await screen.findByText('应用名称')).toBeInTheDocument()
    expect(screen.getByText('cndb')).toBeInTheDocument()
    expect(screen.getByText('sqlite:///data/cndb.db')).toBeInTheDocument()
  })

  it('立即备份成功后生成下载并提示', async () => {
    server.use(
      http.get('/api/v1/admin/info', () => HttpResponse.json(INFO)),
      http.post('/api/v1/admin/backup', () =>
        new HttpResponse('fake-backup-bytes', { headers: { 'Content-Type': 'application/gzip' } }),
      ),
    )
    // jsdom 未实现 createObjectURL，组件 onSuccess 里会调用
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: () => 'blob:mock' })
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: () => { } })
    renderPanel()

    await activateTab(/系\s*统\s*备\s*份/)
    fireEvent.click(await screen.findByRole('button', { name: /立即备份并下载/ }))

    expect(await screen.findByText('系统备份已生成并开始下载')).toBeInTheDocument()
  })

  it('立即备份失败时显示后端错误信息', async () => {
    server.use(
      http.get('/api/v1/admin/info', () => HttpResponse.json(INFO)),
      http.post('/api/v1/admin/backup', () =>
        HttpResponse.json({ detail: '磁盘空间不足' }, { status: 500 }),
      ),
    )
    renderPanel()

    await activateTab(/系\s*统\s*备\s*份/)
    fireEvent.click(await screen.findByRole('button', { name: /立即备份并下载/ }))

    expect(await screen.findByText('磁盘空间不足')).toBeInTheDocument()
  })

  it('上传备份文件校验通过后展示 manifest 摘要', async () => {
    server.use(http.get('/api/v1/admin/info', () => HttpResponse.json(INFO)))
    // jsdom+MSW 下 axios 的 FormData 传输不可用（环境级限制，真实浏览器正常），
    // 在 API 边界 mock 校验方法，组件侧"选文件 → 校验 → 渲染摘要"逻辑仍全链路覆盖
    const inspectSpy = vi.spyOn(apiModule.adminApi, 'restoreInspect').mockResolvedValue(MANIFEST)
    renderPanel()

    await activateTab(/系\s*统\s*恢\s*复/)
    const file = new File(['fake-tar-gz'], 'backup.tar.gz', { type: 'application/gzip' })
    const input = document.querySelector('input[type="file"]')
    expect(input).not.toBeNull()
    fireEvent.change(input as Element, { target: { files: [file] } })

    expect(await screen.findByText(/已选择备份文件/)).toBeInTheDocument()
    expect(inspectSpy).toHaveBeenCalledTimes(1)
    expect(await screen.findByText('备份版本')).toBeInTheDocument()
    // 表清单标签渲染为 "表名 (行数)"
    expect(screen.getByText('workspaces (3)')).toBeInTheDocument()
    // schema 元信息与恢复模式选择器
    expect(screen.getByText('数据结构版本')).toBeInTheDocument()
    expect(screen.getByText('有')).toBeInTheDocument()
    expect(screen.getByText('自动选择（推荐）')).toBeInTheDocument()
  })

  it('备份 schema 领先时显示降级警告并自动选中 sqlalchemy 模式', async () => {
    server.use(http.get('/api/v1/admin/info', () => HttpResponse.json(INFO)))
    vi.spyOn(apiModule.adminApi, 'restoreInspect').mockResolvedValue({
      ...MANIFEST,
      schema_known: false,
      backup_ahead: true,
    })
    renderPanel()

    await activateTab(/系\s*统\s*恢\s*复/)
    const file = new File(['fake-tar-gz'], 'backup.tar.gz', { type: 'application/gzip' })
    const input = document.querySelector('input[type="file"]')
    fireEvent.change(input as Element, { target: { files: [file] } })

    expect(await screen.findByText('备份由更新版本的程序生成')).toBeInTheDocument()
    // 校验通过后恢复模式自动切到"兼容恢复"
    expect(await screen.findByText('兼容恢复（逐表导入，适用范围更广）')).toBeInTheDocument()
  })

  it('降级恢复返回裁剪报告时弹窗呈现丢失面', async () => {
    server.use(http.get('/api/v1/admin/info', () => HttpResponse.json(INFO)))
    const file = new File(['fake-tar-gz'], 'backup.tar.gz', { type: 'application/gzip' })
    vi.spyOn(apiModule.adminApi, 'restoreInspect').mockResolvedValue(MANIFEST)
    const restoreSpy = vi.spyOn(apiModule.adminApi, 'restore').mockResolvedValue({
      status: 'ok',
      message: '恢复完成',
      loss_report: {
        summary: '跳过未知表 1 个: future_table',
        skipped_tables: ['future_table'],
        dropped_columns: {},
      },
    })
    renderPanel()

    await activateTab(/系\s*统\s*恢\s*复/)
    const input = document.querySelector('input[type="file"]')
    fireEvent.change(input as Element, { target: { files: [file] } })
    // 恢复按钮包在 Popconfirm 内：先点开气泡再点确认
    fireEvent.click(await screen.findByRole('button', { name: /执行系统恢复（覆盖）/ }))
    fireEvent.click(await screen.findByRole('button', { name: /确认恢复/ }))

    // restore 调用未显式传 mode（auto → undefined），报告经 modal 呈现
    await waitFor(() => expect(restoreSpy).toHaveBeenCalledTimes(1))
    expect(restoreSpy).toHaveBeenCalledWith(file, true, undefined)
    expect(
      await screen.findByText('恢复完成 — 部分数据未导入', { selector: '.ant-modal-title' }),
    ).toBeInTheDocument()
    expect(
      screen.getByText('跳过未知表 1 个: future_table', { selector: '.ant-modal-body div' }),
    ).toBeInTheDocument()
  })
})
