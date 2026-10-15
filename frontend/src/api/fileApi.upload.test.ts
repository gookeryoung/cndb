/**
 * fileApi.upload 的归属上下文测试.
 *
 * 上传时携带 table_id / row_id / document_id，后端据此登记文件归属，
 * 使下载与删除按宿主对象（表/行/文档）的权限校验。
 */

import { describe, expect, it, vi, afterEach } from 'vitest'

import { fileApi } from './importExport'
import api from './client'

afterEach(() => vi.restoreAllMocks())

describe('fileApi.upload 归属上下文', () => {
    it('携带表与行 id 时写入对应表单字段', async () => {
        const post = vi.spyOn(api, 'post').mockResolvedValue({ data: { file_key: 'k.txt' } } as never)
        const file = new File(['x'], 'a.txt', { type: 'text/plain' })

        await fileApi.upload(10, file, { tableId: 7, rowId: 42 })

        const fd = post.mock.calls[0][1] as FormData
        expect(fd.get('file')).toBe(file)
        expect(fd.get('table_id')).toBe('7')
        expect(fd.get('row_id')).toBe('42')
        expect(fd.get('document_id')).toBeNull()
    })

    it('携带文档 id 时写入 document_id', async () => {
        const post = vi.spyOn(api, 'post').mockResolvedValue({ data: { file_key: 'k.png' } } as never)
        const file = new File(['x'], 'a.png', { type: 'image/png' })

        await fileApi.upload(10, file, { documentId: 3 })

        const fd = post.mock.calls[0][1] as FormData
        expect(fd.get('document_id')).toBe('3')
        expect(fd.get('table_id')).toBeNull()
    })

    it('不传上下文时不写归属字段（保持工作区级文件语义）', async () => {
        const post = vi.spyOn(api, 'post').mockResolvedValue({ data: { file_key: 'k.txt' } } as never)
        const file = new File(['x'], 'a.txt', { type: 'text/plain' })

        await fileApi.upload(10, file)

        const fd = post.mock.calls[0][1] as FormData
        expect(fd.get('table_id')).toBeNull()
        expect(fd.get('row_id')).toBeNull()
        expect(fd.get('document_id')).toBeNull()
    })
})
