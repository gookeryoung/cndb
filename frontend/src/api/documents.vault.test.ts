/**
 * documents.vault（Obsidian 库导入导出）请求构造测试.
 *
 * 重点回归：multipart 必须显式声明 `Content-Type: multipart/form-data`
 * —— axios 实例默认头是 application/json，漏了它后端收不到表单（线上曾 422）。
 */

import { afterEach, describe, expect, it, vi } from 'vitest'

import api from './client'
import { documentsApi } from './documents'

afterEach(() => vi.restoreAllMocks())

const WID = 4
const FILE = new File(['zip'], 'vault.zip', { type: 'application/zip' })

function multipartHeader(call: unknown[]) {
  return (call[2] as { headers?: Record<string, string> } | undefined)?.headers?.['Content-Type']
}

describe('documentsApi.vaultAnalyze', () => {
  it('以 multipart 提交文件与 parent_id', async () => {
    const post = vi.spyOn(api, 'post').mockResolvedValue({ data: { total_notes: 1 } } as never)

    await documentsApi.vaultAnalyze(WID, FILE, 9)

    const [url, body, config] = post.mock.calls[0]
    expect(url).toBe(`/v1/workspaces/${WID}/documents/import/analyze`)
    expect(body).toBeInstanceOf(FormData)
    expect((body as FormData).get('file')).toBe(FILE)
    expect((body as FormData).get('parent_id')).toBe('9')
    expect(multipartHeader(post.mock.calls[0])).toBe('multipart/form-data')
    expect(config).toBeTruthy()
  })

  it('根目录导入时不带 parent_id', async () => {
    const post = vi.spyOn(api, 'post').mockResolvedValue({ data: {} } as never)

    await documentsApi.vaultAnalyze(WID, FILE, null)

    expect((post.mock.calls[0][1] as FormData).get('parent_id')).toBeNull()
  })
})

describe('documentsApi.vaultImport', () => {
  it('提交冲突策略与各开关', async () => {
    const post = vi.spyOn(api, 'post').mockResolvedValue({ data: { created: 1 } } as never)

    await documentsApi.vaultImport(WID, FILE, {
      parentId: 3,
      conflict: 'skip',
      importAttachments: false,
      importTags: true,
      status: 'published',
    })

    const [url, body] = post.mock.calls[0]
    expect(url).toBe(`/v1/workspaces/${WID}/documents/import`)
    const form = body as FormData
    expect(form.get('parent_id')).toBe('3')
    expect(form.get('conflict')).toBe('skip')
    expect(form.get('import_attachments')).toBe('false')
    expect(form.get('import_tags')).toBe('true')
    expect(form.get('status')).toBe('published')
    expect(multipartHeader(post.mock.calls[0])).toBe('multipart/form-data')
  })

  it('缺省选项：改名策略 / 导入附件与标签 / 草稿', async () => {
    const post = vi.spyOn(api, 'post').mockResolvedValue({ data: {} } as never)

    await documentsApi.vaultImport(WID, FILE)

    const form = post.mock.calls[0][1] as FormData
    expect(form.get('parent_id')).toBeNull()
    expect(form.get('conflict')).toBe('rename')
    expect(form.get('import_attachments')).toBe('true')
    expect(form.get('import_tags')).toBe('true')
    expect(form.get('status')).toBe('draft')
  })
})

describe('documentsApi.vaultExport', () => {
  it('以 blob 方式下载整库 zip', async () => {
    const get = vi.spyOn(api, 'get').mockResolvedValue({ data: new Blob(['zip']) } as never)

    const blob = await documentsApi.vaultExport(WID)

    expect(get.mock.calls[0][0]).toBe(`/v1/workspaces/${WID}/documents/export/vault`)
    expect(get.mock.calls[0][1]).toMatchObject({ responseType: 'blob' })
    expect(blob).toBeInstanceOf(Blob)
  })
})
