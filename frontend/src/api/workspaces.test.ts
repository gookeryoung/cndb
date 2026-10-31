/**
 * workspaces api（v9 归档导入/覆盖恢复）请求构造测试.
 *
 * 重点回归：multipart 必须显式声明 `Content-Type: multipart/form-data`
 * —— axios 实例默认头是 application/json，漏了它 axios 会把 FormData
 * 序列化成 JSON，后端收不到文件（e2e 归档导入/恢复曾全量 422）。
 */

import { afterEach, describe, expect, it, vi } from 'vitest'

import api from './client'
import { workspaceApi } from './workspaces'

afterEach(() => vi.restoreAllMocks())

const WID = 4
const FILE = new File(['archive'], 'ws-backup.tar.gz', { type: 'application/gzip' })

function multipartHeader(call: unknown[]) {
  return (call[2] as { headers?: Record<string, string> } | undefined)?.headers?.['Content-Type']
}

describe('workspaceApi.importWorkspaceArchive', () => {
  it('以 multipart 提交归档文件', async () => {
    const post = vi.spyOn(api, 'post').mockResolvedValue({
      data: { workspace: { id: 9 }, imported_tables: 0, imported_rows: 0, imported_views: 0 },
    } as never)

    await workspaceApi.importWorkspaceArchive(FILE)

    const [url, body] = post.mock.calls[0]
    expect(url).toBe('/v1/workspaces/import/archive')
    expect(body).toBeInstanceOf(FormData)
    expect((body as FormData).get('file')).toBe(FILE)
    expect(multipartHeader(post.mock.calls[0])).toBe('multipart/form-data')
  })
})

describe('workspaceApi.restoreWorkspace', () => {
  it('以 multipart 提交归档文件', async () => {
    const post = vi.spyOn(api, 'post').mockResolvedValue({
      data: { imported_tables: 0, imported_rows: 0, imported_views: 0 },
    } as never)

    await workspaceApi.restoreWorkspace(WID, FILE)

    const [url, body] = post.mock.calls[0]
    expect(url).toBe(`/v1/workspaces/${WID}/restore`)
    expect(body).toBeInstanceOf(FormData)
    expect((body as FormData).get('file')).toBe(FILE)
    expect(multipartHeader(post.mock.calls[0])).toBe('multipart/form-data')
  })
})
