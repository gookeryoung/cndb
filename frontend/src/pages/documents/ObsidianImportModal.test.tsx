/**
 * Obsidian 库导入弹窗测试 —— 上传 zip 后先预览再落库。
 *
 * 覆盖：解析结果展示（篇数 / 文件夹 / 同名冲突 / 标签）/ 冲突策略传递 /
 * 附件与标签开关传递 / 导入结果摘要。
 */

import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import ObsidianImportModal from './ObsidianImportModal'
import { renderProviders } from '@/test/render-providers'
import { documentsApi, type VaultAnalyzeResult, type VaultImportResult } from '@/api/documents'

const WID = 7

const ANALYSIS: VaultAnalyzeResult = {
  filename: 'vault.zip',
  root_dir: 'MyVault',
  total_notes: 3,
  total_markdown: 2,
  total_converted: 1,
  total_folders: 1,
  total_attachments: 2,
  total_attachment_bytes: 2048,
  total_bytes: 4096,
  ignored_files: 2,
  conflicts: 1,
  tags: ['项目', '研究'],
  warnings: [{ code: 'wikilink_normalized', message: '2 处双链统一为 [[标题]]', count: 2 }],
  skipped: [],
  preview_truncated: false,
  folders: [{ path: '笔记', title: '笔记', status: 'new' }],
  items: [
    {
      path: '笔记/设计稿.md',
      title: '设计稿',
      folder: '笔记',
      size: 1024,
      tags: ['项目'],
      status: 'conflict',
      kind: 'markdown',
      existing_document_id: 9,
    },
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
    {
      path: '策划.canvas',
      title: '策划',
      folder: '',
      size: 256,
      tags: [],
      status: 'new',
      kind: 'canvas',
      existing_document_id: null,
    },
  ],
}

const RESULT: VaultImportResult = {
  created: 2,
  updated: 1,
  skipped: 0,
  total: 3,
  folders_created: 1,
  converted: 1,
  attachments: 2,
  attachment_bytes: 2048,
  tags_created: ['项目', '研究'],
  documents: [{ id: 11, title: '索引', path: '索引.md' }],
  skipped_notes: [],
  warnings: [{ code: 'unresolved_links', message: '1 处双链未找到目标', count: 1 }],
}

async function upload() {
  // antd Modal 渲染到 portal，需从 document 上找上传输入框
  const input = (await waitFor(() => {
    const found = document.querySelector('input[type="file"]')
    if (!found) throw new Error('上传输入框未渲染')
    return found
  })) as HTMLInputElement
  const file = new File(['zip'], 'vault.zip', { type: 'application/zip' })
  fireEvent.change(input, { target: { files: [file] } })
  return file
}

beforeEach(() => {
  vi.restoreAllMocks()
  vi.spyOn(documentsApi, 'vaultAnalyze').mockResolvedValue(ANALYSIS)
  vi.spyOn(documentsApi, 'vaultImport').mockResolvedValue(RESULT)
})

describe('Obsidian 库导入弹窗', () => {
  it('上传后展示解析预览与同名冲突提示', async () => {
    renderProviders(<ObsidianImportModal open onClose={() => {}} workspaceId={WID} parentId={null} />)
    await upload()

    const summary = await screen.findByTestId('vault-import-summary')
    expect(summary).toHaveTextContent('2 篇') // 原生 markdown
    expect(summary).toHaveTextContent('1 个') // 转换文件（.canvas）
    expect(summary).toHaveTextContent('1 篇') // 同名冲突
    expect(screen.getByTestId('vault-import-conflict')).toBeInTheDocument()
    expect(screen.getByTestId('vault-import-preview')).toHaveTextContent('笔记/设计稿.md')
    expect(screen.getByText('2 处双链统一为 [[标题]]')).toBeInTheDocument()
    expect(documentsApi.vaultAnalyze).toHaveBeenCalledWith(WID, expect.any(File), null)
  })

  it('按确认的策略与开关导入', async () => {
    renderProviders(
      <ObsidianImportModal open onClose={() => {}} workspaceId={WID} parentId={3} parentLabel="收件箱" />,
    )
    await upload()
    await screen.findByTestId('vault-import-summary')

    // 切换到「跳过同名文档」
    fireEvent.click(screen.getByLabelText(/跳过同名文档/))
    fireEvent.click(screen.getByTestId('vault-import-submit'))

    await waitFor(() => expect(documentsApi.vaultImport).toHaveBeenCalledTimes(1))
    expect(documentsApi.vaultImport).toHaveBeenCalledWith(
      WID,
      expect.any(File),
      expect.objectContaining({
        parentId: 3,
        conflict: 'skip',
        importAttachments: true,
        importTags: true,
        status: 'draft',
      }),
    )
  })

  it('导入完成后展示统计与告警', async () => {
    renderProviders(<ObsidianImportModal open onClose={() => {}} workspaceId={WID} />)
    await upload()
    await screen.findByTestId('vault-import-summary')
    fireEvent.click(screen.getByTestId('vault-import-submit'))

    const result = await screen.findByTestId('vault-import-result')
    expect(result).toHaveTextContent('新增 2 篇')
    expect(result).toHaveTextContent('更新 1 篇')
    expect(result).toHaveTextContent('新建标签：项目、研究')
    expect(result).toHaveTextContent('1 处双链未找到目标')
    // 结果态下不再展示上传区
    expect(screen.queryByTestId('vault-import-summary')).not.toBeInTheDocument()
  })

  it('解析失败时清空已选文件', async () => {
    vi.spyOn(documentsApi, 'vaultAnalyze').mockRejectedValue(new Error('不是有效的 zip 压缩包'))
    renderProviders(<ObsidianImportModal open onClose={() => {}} workspaceId={WID} />)
    await upload()
    await waitFor(() => expect(documentsApi.vaultAnalyze).toHaveBeenCalled())
    await waitFor(() =>
      expect(screen.queryByTestId('vault-import-summary')).not.toBeInTheDocument(),
    )
    expect(screen.getByTestId('vault-import-submit')).toBeDisabled()
  })
})
