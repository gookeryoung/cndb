/**
 * 通用导入弹窗测试 —— 单文件 / 文件夹 / Obsidian 库三种模式。
 *
 * 覆盖：预览摘要与冲突提示 / 模式切换与相对路径 / 库模式切到 VaultImportForm /
 * 冲突策略与开关传递 / 导入结果摘要与跳过明细 / 解析失败清空 / 未选文件时禁用提交。
 */

import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, screen, waitFor, within } from '@testing-library/react'
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
  it('模式选择器与拖放区共用一套图标（单文件 / 文件夹 / zip 库）', async () => {
    renderProviders(<DocumentImportModal open onClose={() => {}} workspaceId={WID} parentId={null} />)
    const modeIcons = () =>
      Array.from(
        screen.getByTestId('file-import-mode').querySelectorAll('.ant-radio-button-wrapper .anticon'),
      ).map(node => node.getAttribute('class'))
    expect(modeIcons()).toEqual([
      expect.stringContaining('anticon-file-text'),
      expect.stringContaining('anticon-folder-open'),
      expect.stringContaining('anticon-file-zip'),
    ])

    // 单文件 → 文件夹：拖放区图标随模式切换，且与选择器同源（Modal 渲染在 portal 里）
    const zoneIcon = (name: string) =>
      document.querySelector(`[data-testid="file-import-dropzone"] .anticon-${name}`)
    expect(zoneIcon('file-text')).toBeTruthy()
    fireEvent.click(screen.getByRole('radio', { name: '文件夹' }))
    expect(zoneIcon('folder-open')).toBeTruthy()

    // 库模式：拖放区同样是压缩包图标，不再是独立的 Dragger 样式
    fireEvent.click(screen.getByRole('radio', { name: 'Obsidian 库' }))
    const vaultZone = await screen.findByTestId('vault-import-upload')
    expect(vaultZone.querySelector('.anticon-file-zip')).toBeTruthy()
    expect(vaultZone).toHaveTextContent('上传 Obsidian 库压缩包')
    expect(screen.getByTestId('vault-import-pick')).toHaveTextContent('选择 .zip 文件')
  })

  it('三种模式的底部动作条与文字块结构一致（切模式不跳动）', async () => {
    renderProviders(<DocumentImportModal open onClose={() => {}} workspaceId={WID} parentId={null} />)
    const footers = () => document.querySelectorAll('[data-testid="import-footer"]')
    const subtitle = () =>
      within(screen.getByTestId('file-import-dropzone')).getByTitle(/导入到/)

    expect(footers()).toHaveLength(1)
    expect(subtitle()).toHaveStyle({ whiteSpace: 'nowrap', textOverflow: 'ellipsis' })

    fireEvent.click(screen.getByRole('radio', { name: '文件夹' }))
    expect(footers()).toHaveLength(1)
    expect(subtitle()).toHaveStyle({ whiteSpace: 'nowrap' })

    // 库模式复用同一动作条与同一文字块，不额外套一层弹窗 footer
    fireEvent.click(screen.getByRole('radio', { name: 'Obsidian 库' }))
    const vaultZone = await screen.findByTestId('vault-import-upload')
    expect(footers()).toHaveLength(1)
    expect(within(vaultZone).getByTitle(/导入到/)).toHaveStyle({ whiteSpace: 'nowrap' })
    // 已选行常驻占位（未选时也保留高度）
    expect(vaultZone.querySelector('[data-testid="vault-import-picked"]')).toBeNull()
  })

  it('库模式纵向节奏与文件 / 文件夹一致（同一 flex 容器 + 12px 间距）', async () => {
    renderProviders(<DocumentImportModal open onClose={() => {}} workspaceId={WID} parentId={null} />)
    const bodyRoot = () =>
      document.querySelector('[data-testid="file-import-modal"] .ant-modal-body > div') as HTMLElement

    // 文件 / 文件夹：选择器与上传卡同属一个 flex column，底部动作条收尾
    expect(bodyRoot()).toHaveStyle({ display: 'flex', flexDirection: 'column', gap: '12px' })
    expect(bodyRoot().lastElementChild).toBe(screen.getByTestId('import-footer'))

    // Obsidian 库：外层容器不变，库表单根节点用同一套 flex column（不再套 marginTop / 行内 Space）
    fireEvent.click(screen.getByRole('radio', { name: 'Obsidian 库' }))
    const zone = await screen.findByTestId('vault-import-upload')
    expect(bodyRoot().style.gap).toBe('12px')
    const vaultRoot = zone.parentElement as HTMLElement
    expect(vaultRoot).toHaveStyle({ display: 'flex', flexDirection: 'column', gap: '12px' })
    const visibleChildren = Array.from(vaultRoot.children).filter(
      node => (node as HTMLElement).style.display !== 'none',
    )
    expect(visibleChildren[0]).toBe(zone)
    expect(vaultRoot.lastElementChild).toBe(screen.getByTestId('import-footer'))
  })

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
    expect(summary).toHaveTextContent('文件 4 个')
    expect(summary).toHaveTextContent('可导入 3 篇')
    expect(summary).toHaveTextContent('原样存档 1 个')
    expect(summary).toHaveTextContent('同名冲突 1 篇')
    expect(screen.getByTestId('file-import-conflict')).toBeInTheDocument()
    expect(screen.getByTestId('file-import-preview')).toHaveTextContent('笔记/设计.docx')
    expect(screen.getByText(/bad.txt：不支持的格式/)).toBeInTheDocument()
    expect(screen.getByTestId('file-import-picked')).toHaveTextContent('已选 1 个文件')
    expect(documentsApi.fileImportAnalyze).toHaveBeenCalledWith(WID, {
      entries: [{ file: expect.any(File), path: '说明.md' }],
      parentId: null,
      mhtmlMode: 'archive',
      docxMode: 'convert',
    })
  })

  it('整个上传区可点击，格式说明与选择互不干扰', async () => {
    renderProviders(<DocumentImportModal open onClose={() => {}} workspaceId={WID} />)
    const inputClick = vi.spyOn(HTMLInputElement.prototype, 'click')
    const zone = screen.getByTestId('file-import-dropzone')

    fireEvent.click(zone)
    expect(inputClick).toHaveBeenCalledTimes(1)

    // 点「格式说明」只开说明气泡，不触发文件选择
    fireEvent.click(screen.getByTestId('file-import-help'))
    expect(inputClick).toHaveBeenCalledTimes(1)
    expect(await screen.findByText('格式与处理方式')).toBeInTheDocument()
    expect(screen.getByText(/原样存档：PDF \/ Excel \/ PPT \/ 图片/)).toBeInTheDocument()
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
      mhtmlMode: 'archive',
      docxMode: 'convert',
    })
    expect(await screen.findByTestId('file-import-picked')).toHaveTextContent('已选 2 个文件')
  })

  it('按确认的策略与开关导入', async () => {
    renderProviders(
      <DocumentImportModal open onClose={() => {}} workspaceId={WID} parentId={3} parentLabel="收件箱" />,
    )
    pick([new File(['# 说明'], '说明.md', { type: 'text/markdown' }), new File(['x'], '网页.mhtml')])
    await screen.findByTestId('file-import-summary')

    // 先切到转换模式（重解析期间开关行卸载），稳定后再点选项与关闭内嵌图片开关
    fireEvent.click(screen.getByTestId('file-import-mhtml-convert'))
    const attachmentsSwitch = await screen.findByTestId('file-import-attachments')
    expect(attachmentsSwitch).toBeEnabled()
    fireEvent.click(screen.getByLabelText(/跳过同名文档/))
    fireEvent.click(screen.getByLabelText('已发布'))
    fireEvent.click(attachmentsSwitch)
    fireEvent.click(screen.getByTestId('file-import-submit'))

    await waitFor(() => expect(documentsApi.fileImport).toHaveBeenCalledTimes(1))
    expect(documentsApi.fileImport).toHaveBeenCalledWith(
      WID,
      expect.objectContaining({
        parentId: 3,
        conflict: 'skip',
        status: 'published',
        importAttachments: false,
        mhtmlMode: 'convert',
        entries: [expect.objectContaining({ path: '说明.md' }), expect.objectContaining({ path: '网页.mhtml' })],
      }),
    )
  })

  it('MHTML 模式开关：默认关、切换传 convert 并重解析、归档态禁用内嵌图片开关', async () => {
    renderProviders(<DocumentImportModal open onClose={() => {}} workspaceId={WID} />)
    pick([new File(['# 说明'], '说明.md', { type: 'text/markdown' }), new File(['x'], '网页.mhtml')])
    await screen.findByTestId('file-import-summary')

    // 开关行随预览出现：默认关，archive 态内嵌图片开关禁用（原样存档时不适用）
    const convertSwitch = screen.getByTestId('file-import-mhtml-convert')
    expect(convertSwitch).not.toBeChecked()
    expect(screen.getByTestId('file-import-attachments')).toBeDisabled()

    fireEvent.click(convertSwitch)
    await waitFor(() => expect(documentsApi.fileImportAnalyze).toHaveBeenCalledTimes(2))
    expect(documentsApi.fileImportAnalyze).toHaveBeenLastCalledWith(
      WID,
      expect.objectContaining({ mhtmlMode: 'convert' }),
    )
    // convert 态：内嵌图片开关恢复可用（默认开）
    expect(screen.getByTestId('file-import-attachments')).toBeEnabled()

    fireEvent.click(screen.getByTestId('file-import-submit'))
    await waitFor(() => expect(documentsApi.fileImport).toHaveBeenCalledTimes(1))
    expect(documentsApi.fileImport).toHaveBeenCalledWith(
      WID,
      expect.objectContaining({ importAttachments: true, mhtmlMode: 'convert' }),
    )
  })

  it('Word 原样存档开关：默认关、切换传 archive 并重解析、导入带 docxMode', async () => {
    renderProviders(<DocumentImportModal open onClose={() => {}} workspaceId={WID} />)
    pick([new File(['PK'], '说明书.docx', { type: 'application/octet-stream' })])
    await screen.findByTestId('file-import-summary')

    const archiveSwitch = screen.getByTestId('file-import-docx-archive')
    expect(archiveSwitch).not.toBeChecked()

    fireEvent.click(archiveSwitch)
    await waitFor(() => expect(documentsApi.fileImportAnalyze).toHaveBeenCalledTimes(2))
    expect(documentsApi.fileImportAnalyze).toHaveBeenLastCalledWith(
      WID,
      expect.objectContaining({ docxMode: 'archive' }),
    )

    fireEvent.click(screen.getByTestId('file-import-submit'))
    await waitFor(() => expect(documentsApi.fileImport).toHaveBeenCalledTimes(1))
    expect(documentsApi.fileImport).toHaveBeenCalledWith(
      WID,
      expect.objectContaining({ docxMode: 'archive' }),
    )
  })

  it('批次无 Word（如 PDF）时「Word 原样存档」开关禁用', async () => {
    renderProviders(<DocumentImportModal open onClose={() => {}} workspaceId={WID} />)
    pick([new File(['%PDF'], '报告.pdf', { type: 'application/pdf' })])
    await screen.findByTestId('file-import-summary')

    expect(screen.getByTestId('file-import-docx-archive')).toBeDisabled()
    expect(screen.getByText('Word 原样存档')).toBeInTheDocument()
  })

  it('批次无 MHTML（如 PDF）时「MHTML 转 Markdown」开关禁用', async () => {
    renderProviders(<DocumentImportModal open onClose={() => {}} workspaceId={WID} />)
    pick([new File(['%PDF'], '报告.pdf', { type: 'application/pdf' })])
    await screen.findByTestId('file-import-summary')

    const convertSwitch = screen.getByTestId('file-import-mhtml-convert')
    expect(convertSwitch).toBeDisabled()
    expect(screen.getByText('MHTML 转 Markdown')).toBeInTheDocument()
    // 内嵌图片开关与 MHTML 无关的批次保持可用（原样存档不适用只针对批次含 MHTML 时）
    expect(screen.getByTestId('file-import-attachments')).toBeEnabled()
  })

  it('批次仅含 .mht（MHTML 别名）时「MHTML 转 Markdown」开关可用', async () => {
    renderProviders(<DocumentImportModal open onClose={() => {}} workspaceId={WID} />)
    pick([new File(['x'], '网页存档.mht')])
    await screen.findByTestId('file-import-summary')

    expect(screen.getByTestId('file-import-mhtml-convert')).toBeEnabled()
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
