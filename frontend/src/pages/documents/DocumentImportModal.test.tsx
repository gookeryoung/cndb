/**
 * 通用导入弹窗测试 —— 单文件 / 文件夹 / Obsidian 库三种模式。
 *
 * 覆盖：预览摘要与冲突提示 / 模式切换与相对路径 / 库模式切到 VaultImportForm /
 * 冲突策略与开关传递 / 导入结果摘要与跳过明细 / 解析失败清空 / 未选文件时禁用提交。
 */

import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import DocumentImportModal from './DocumentImportModal'
import { renderProviders } from '@/test/render-providers'
import {
  documentsApi,
  type FileImportAnalyzeResult,
  type FileImportResult,
  type VaultAnalyzeResult,
} from '@/api/documents'

const WID = 7

const ANALYSIS: FileImportAnalyzeResult = {
  total_files: 4,
  total_documents: 3,
  total_folders: 1,
  assets: 1,
  conflicts: 1,
  skipped: [{ path: 'bad.txt', reason: '不支持的格式：.txt' }],
  warnings: [{ path: '笔记.md', message: '标题取自正文首个一级标题，已从正文剥离' }],
  folders: [{ path: '笔记', title: '笔记', status: 'new' }],
  items: [
    {
      path: '笔记/设计.docx',
      title: '设计',
      folder: '笔记',
      suffix: '.docx',
      format: 'markdown',
      is_asset: false,
      status: 'conflict',
      existing_document_id: 9,
      warnings: [],
    },
    {
      path: '说明.md',
      title: '说明',
      folder: '',
      suffix: '.md',
      format: 'markdown',
      is_asset: false,
      status: 'new',
      existing_document_id: null,
      warnings: ['标题取自文件名'],
    },
    {
      path: '报告.pdf',
      title: '报告',
      folder: '',
      suffix: '.pdf',
      format: 'pdf',
      is_asset: true,
      status: 'new',
      existing_document_id: null,
      warnings: [],
    },
  ],
  preview_truncated: false,
}

const RESULT: FileImportResult = {
  created: 1,
  updated: 1,
  skipped: 1,
  total: 3,
  folders_created: 1,
  attachments: 2,
  attachment_bytes: 2048,
  assets: 1,
  documents: [{ id: 11, title: '说明', path: '说明.md' }],
  skipped_files: [{ path: 'bad.txt', reason: '不支持的格式：.txt' }],
  warnings: [{ path: '设计.docx', message: '内嵌图片未导入：image1.png' }],
}

/** 造一个带 webkitRelativePath 的 File（浏览器只读属性，测试里补上） */
function folderFile(name: string, relativePath: string, content = 'x') {
  const file = new File([content], name, { type: 'text/markdown' })
  Object.defineProperty(file, 'webkitRelativePath', { value: relativePath })
  return file
}

function fileInput(): HTMLInputElement {
  return document.querySelector('input[type="file"]') as HTMLInputElement
}

function pick(files: File[]) {
  fireEvent.change(fileInput(), { target: { files } })
}

beforeEach(() => {
  vi.restoreAllMocks()
  vi.spyOn(documentsApi, 'fileImportAnalyze').mockResolvedValue(ANALYSIS)
  vi.spyOn(documentsApi, 'fileImport').mockResolvedValue(RESULT)
})

const VAULT_ANALYSIS: VaultAnalyzeResult = {
  filename: 'vault.zip',
  root_dir: 'MyVault',
  total_notes: 1,
  total_markdown: 1,
  total_converted: 0,
  total_folders: 0,
  total_attachments: 0,
  total_attachment_bytes: 0,
  total_bytes: 512,
  ignored_files: 0,
  conflicts: 0,
  tags: [],
  warnings: [],
  skipped: [],
  preview_truncated: false,
  folders: [],
  items: [
    {
      path: '索引.md',
      title: '索引',
      folder: '',
      size: 512,
      tags: [],
      status: 'new',
      kind: 'markdown',
      existing_document_id: null,
    },
  ],
}

describe('通用导入弹窗', () => {
  it('库模式渲染 Obsidian 库上传表单，可切回文件模式', async () => {
    vi.spyOn(documentsApi, 'vaultAnalyze').mockResolvedValue(VAULT_ANALYSIS)
    renderProviders(<DocumentImportModal open onClose={() => {}} workspaceId={WID} parentId={null} />)

    fireEvent.click(screen.getByRole('radio', { name: 'Obsidian 库' }))
    expect(await screen.findByTestId('vault-import-upload')).toBeInTheDocument()

    // 切回文件夹模式：库表单消失，文件上传区恢复
    fireEvent.click(screen.getByRole('radio', { name: '文件夹' }))
    await waitFor(() => expect(screen.queryByTestId('vault-import-upload')).not.toBeInTheDocument())
    expect(screen.getByTestId('file-import-pick')).toBeInTheDocument()
  })


  it('单文件上传后展示预览与同名冲突提示', async () => {
    renderProviders(<DocumentImportModal open onClose={() => {}} workspaceId={WID} parentId={null} />)
    pick([new File(['# 说明'], '说明.md', { type: 'text/markdown' })])

    const summary = await screen.findByTestId('file-import-summary')
    expect(summary).toHaveTextContent('4 个') // 文件数
    expect(summary).toHaveTextContent('3 篇') // 可导入文档
    expect(summary).toHaveTextContent('原样存档1 个')
    expect(summary).toHaveTextContent('1 篇') // 同名冲突
    expect(screen.getByTestId('file-import-conflict')).toBeInTheDocument()
    expect(screen.getByTestId('file-import-preview')).toHaveTextContent('笔记/设计.docx')
    expect(screen.getByText(/bad.txt：不支持的格式/)).toBeInTheDocument()
    expect(screen.getByTestId('file-import-picked')).toHaveTextContent('已选择 1 个文件')
    expect(documentsApi.fileImportAnalyze).toHaveBeenCalledWith(WID, {
      entries: [{ file: expect.any(File), path: '说明.md' }],
      parentId: null,
    })
  })

  it('预览把 PDF / Office / 图片标为原样存档，accept 覆盖新格式', async () => {
    renderProviders(<DocumentImportModal open onClose={() => {}} workspaceId={WID} />)
    expect(fileInput().getAttribute('accept')).toContain('.pdf')
    expect(fileInput().getAttribute('accept')).toContain('.xlsx')
    expect(fileInput().getAttribute('accept')).toContain('.png')

    pick([new File(['%PDF-1.4'], '报告.pdf', { type: 'application/pdf' })])
    const preview = await screen.findByTestId('file-import-preview')
    expect(preview).toHaveTextContent('报告.pdf')
    expect(screen.getAllByTestId('file-import-asset-tag')[0]).toHaveTextContent('原样存档')
  })

  it('文件夹模式按相对路径提交批次', async () => {
    renderProviders(<DocumentImportModal open onClose={() => {}} workspaceId={WID} parentId={3} />)
    fireEvent.click(screen.getByRole('radio', { name: '文件夹' }))
    // 切换模式后 input 带 webkitdirectory
    await waitFor(() => expect(fileInput()).toHaveAttribute('webkitdirectory'))

    const batch = [
      folderFile('设计.docx', '笔记/设计.docx'),
      folderFile('说明.md', '笔记/说明.md'),
    ]
    pick(batch)

    await waitFor(() => expect(documentsApi.fileImportAnalyze).toHaveBeenCalledTimes(1))
    expect(documentsApi.fileImportAnalyze).toHaveBeenCalledWith(WID, {
      entries: [
        { file: batch[0], path: '笔记/设计.docx' },
        { file: batch[1], path: '笔记/说明.md' },
      ],
      parentId: 3,
    })
    expect(await screen.findByTestId('file-import-picked')).toHaveTextContent('已选择 2 个文件')
  })

  it('按确认的策略与开关导入', async () => {
    renderProviders(
      <DocumentImportModal open onClose={() => {}} workspaceId={WID} parentId={3} parentLabel="收件箱" />,
    )
    pick([new File(['# 说明'], '说明.md', { type: 'text/markdown' })])
    await screen.findByTestId('file-import-summary')

    fireEvent.click(screen.getByLabelText(/跳过同名文档/))
    fireEvent.click(screen.getByLabelText('已发布'))
    fireEvent.click(screen.getByTestId('file-import-attachments'))
    fireEvent.click(screen.getByTestId('file-import-submit'))

    await waitFor(() => expect(documentsApi.fileImport).toHaveBeenCalledTimes(1))
    expect(documentsApi.fileImport).toHaveBeenCalledWith(
      WID,
      expect.objectContaining({
        parentId: 3,
        conflict: 'skip',
        status: 'published',
        importAttachments: false,
        entries: [expect.objectContaining({ path: '说明.md' })],
      }),
    )
  })

  it('导入完成后展示统计、告警与跳过明细', async () => {
    renderProviders(<DocumentImportModal open onClose={() => {}} workspaceId={WID} />)
    pick([new File(['# 说明'], '说明.md', { type: 'text/markdown' })])
    await screen.findByTestId('file-import-summary')
    fireEvent.click(screen.getByTestId('file-import-submit'))

    const result = await screen.findByTestId('file-import-result')
    expect(result).toHaveTextContent('新增 1 篇')
    expect(result).toHaveTextContent('更新 1 篇')
    expect(result).toHaveTextContent('新建文件夹 1 个')
    expect(result).toHaveTextContent('原样存档 1 个')
    expect(result).toHaveTextContent('设计.docx：内嵌图片未导入：image1.png')
    expect(result).toHaveTextContent('bad.txt（不支持的格式：.txt）')
    // 结果态下不再展示上传区
    expect(screen.queryByTestId('file-import-summary')).not.toBeInTheDocument()
  })

  it('解析失败时清空已选文件并禁用提交', async () => {
    vi.spyOn(documentsApi, 'fileImportAnalyze').mockRejectedValue(new Error('解析失败'))
    renderProviders(<DocumentImportModal open onClose={() => {}} workspaceId={WID} />)
    pick([new File(['x'], 'bad.docx', { type: 'application/octet-stream' })])

    await waitFor(() => expect(documentsApi.fileImportAnalyze).toHaveBeenCalled())
    await waitFor(() => expect(screen.queryByTestId('file-import-summary')).not.toBeInTheDocument())
    expect(screen.getByTestId('file-import-submit')).toBeDisabled()
    expect(screen.queryByTestId('file-import-picked')).not.toBeInTheDocument()
  })

  it('未选择文件时提交禁用，且重新选择可复位', async () => {
    renderProviders(<DocumentImportModal open onClose={() => {}} workspaceId={WID} />)
    expect(screen.getByTestId('file-import-submit')).toBeDisabled()

    pick([new File(['# 说明'], '说明.md', { type: 'text/markdown' })])
    await screen.findByTestId('file-import-summary')
    expect(screen.getByTestId('file-import-submit')).toBeEnabled()

    fireEvent.click(screen.getByTestId('file-import-repick'))
    expect(screen.getByTestId('file-import-submit')).toBeDisabled()
    expect(screen.queryByTestId('file-import-summary')).not.toBeInTheDocument()
  })
})
