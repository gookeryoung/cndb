/**
 * 通用文件导入弹窗 —— 单文件 / 文件夹模式，支持 md、docx、html、mhtml。
 *
 * 两段式与数据表/Obsidian 导入一致：
 * 1. ``POST /import/files/analyze`` 只解析（本地读取 + 转换）不写库，展示篇数 / 文件夹 / 冲突 / 跳过；
 * 2. ``POST /import/files`` 按确认的冲突策略 / 状态 / 附件开关真正导入。
 *
 * 格式化口径由后端决定（docx / html → Markdown、标题识别、清理多余空白；docx 可选原件存档），前端只把「会发生什么」
 * 讲清楚：可导入篇数、待建文件夹、同名冲突、被跳过的文件与告警。
 */
import { useMemo, useRef, useState } from 'react'
import {
  Alert,
  App as AntApp,
  Button,
  Empty,
  Modal,
  Radio,
  Space,
  Table,
  Tag as AntTag,
  Typography,
} from 'antd'
import { FileTextOutlined, FileZipOutlined, FolderOpenOutlined } from '@ant-design/icons'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { VaultImportForm } from './ObsidianImportModal'
import {
  ImportConflictOptions,
  ImportDropzone,
  ImportOptionsPanel,
  ImportStatusRadio,
  ImportSummary,
  ImportSwitch,
  ImportTruncatedHint,
} from './importUi'
import {
  documentsApi,
  FILE_IMPORT_ACCEPT,
  type FileImportAnalyzeResult,
  type FileImportEntry,
  type FileImportPreviewItem,
  type DocxImportMode,
  type FileImportResult,
  type MhtmlImportMode,
  type VaultConflictPolicy,
} from '@/api/documents'

interface Props {
  open: boolean
  onClose: () => void
  workspaceId: number
  /** 默认导入位置：当前浏览的文件夹（null = 根目录） */
  parentId?: number | null
  /** 当前文件夹标题，仅用于文案 */
  parentLabel?: string
}

type ImportMode = 'single' | 'folder' | 'vault'

const FORMAT_LABEL: Record<string, string> = {
  '.md': 'Markdown',
  '.markdown': 'Markdown',
  '.docx': 'Word',
  '.html': 'HTML',
  '.htm': 'HTML',
  '.mhtml': 'MHTML',
  '.mht': 'MHTML',
  '.pdf': 'PDF',
  '.xlsx': 'Excel',
  '.xls': 'Excel',
  '.pptx': 'PPT',
  '.ppt': 'PPT',
  '.png': '图片',
  '.jpg': '图片',
  '.jpeg': '图片',
  '.gif': '图片',
  '.webp': '图片',
  '.svg': '图片',
  '.bmp': '图片',
}

/** 把浏览器选中的文件整理为批次条目：文件夹模式取相对路径，单文件模式取文件名 */
function toEntries(files: FileList | null, mode: ImportMode): FileImportEntry[] {
  if (!files) return []
  return Array.from(files).map(file => {
    const relative = (file as File & { webkitRelativePath?: string }).webkitRelativePath
    const path = mode === 'folder' ? relative || file.name : file.name
    return { file, path }
  })
}

export default function DocumentImportModal({ open, onClose, workspaceId, parentId, parentLabel }: Props) {
  const { message } = AntApp.useApp()
  const qc = useQueryClient()
  const inputRef = useRef<HTMLInputElement>(null)
  const [mode, setMode] = useState<ImportMode>('single')
  const [entries, setEntries] = useState<FileImportEntry[]>([])
  const [analysis, setAnalysis] = useState<FileImportAnalyzeResult | null>(null)
  const [result, setResult] = useState<FileImportResult | null>(null)
  const [conflict, setConflict] = useState<VaultConflictPolicy>('rename')
  const [importAttachments, setImportAttachments] = useState(true)
  /** MHTML 处理模式：默认原样存档，打开后转 Markdown（0061 C6） */
  const [mhtmlMode, setMhtmlMode] = useState<MhtmlImportMode>('archive')
  /** Word 处理模式：默认转 Markdown（兼容 0010），打开后原件存档 + 在线预览（0087 C2） */
  const [docxMode, setDocxMode] = useState<DocxImportMode>('convert')
  const [status, setStatus] = useState<'draft' | 'published'>('draft')

  /** 批次里是否含 MHTML（.mhtml / .mht）：不含时「MHTML 转 Markdown」开关禁用（仅对 MHTML 生效） */
  const hasMhtml = entries.some(entry => /\.(mhtml|mht)$/i.test(entry.path))
  /** 批次里是否含 Word（.docx）：不含时「Word 原样存档」开关禁用（仅对 docx 生效） */
  const hasDocx = entries.some(entry => /\.docx$/i.test(entry.path))
  /** 内嵌图片开关只在「MHTML 原样存档」时无意义（素材已随原件保留），其余批次均可用 */
  const attachmentsDisabled = hasMhtml && mhtmlMode === 'archive'

  const reset = () => {
    setEntries([])
    setAnalysis(null)
    setResult(null)
    if (inputRef.current) inputRef.current.value = ''
  }

  const close = () => {
    reset()
    onClose()
  }

  const analyzeMut = useMutation({
    mutationFn: (payload: { batch: FileImportEntry[]; mhtmlMode: MhtmlImportMode; docxMode: DocxImportMode }) =>
      documentsApi.fileImportAnalyze(workspaceId, {
        entries: payload.batch,
        parentId,
        mhtmlMode: payload.mhtmlMode,
        docxMode: payload.docxMode,
      }),
    onSuccess: data => {
      setAnalysis(data)
      setConflict('rename')
    },
    onError: (err: unknown) => {
      reset()
      message.error(
        err instanceof Error ? err.message : '解析失败，请确认文件格式在支持范围内（md / docx / html / mhtml / pdf / Office / 图片）',
      )
    },
  })

  const importMut = useMutation({
    mutationFn: (batch: FileImportEntry[]) =>
      documentsApi.fileImport(workspaceId, {
        entries: batch,
        parentId,
        conflict,
        status,
        importAttachments,
        mhtmlMode,
        docxMode,
      }),
    onSuccess: data => {
      setResult(data)
      void qc.invalidateQueries({ queryKey: ['documents', workspaceId] })
      message.success(
        `导入完成：新增 ${data.created} 篇、更新 ${data.updated} 篇、跳过 ${data.skipped} 篇`,
      )
    },
    onError: (err: unknown) => {
      message.error(err instanceof Error ? err.message : '导入失败')
    },
  })

  const pick = (files: FileList | null) => {
    const batch = toEntries(files, mode)
    if (batch.length === 0) return
    setEntries(batch)
    setAnalysis(null)
    setResult(null)
    analyzeMut.mutate({ batch, mhtmlMode, docxMode })
  }

  /** 切换 MHTML 模式后预览口径随之变化（is_asset / format），已选批次需要重新解析 */
  const changeMhtmlMode = (next: MhtmlImportMode) => {
    setMhtmlMode(next)
    if (entries.length > 0) {
      setAnalysis(null)
      analyzeMut.mutate({ batch: entries, mhtmlMode: next, docxMode })
    }
  }

  /** 切换 Word 模式同样会改变落库渲染族（markdown ↔ word），已选批次需要重新解析 */
  const changeDocxMode = (next: DocxImportMode) => {
    setDocxMode(next)
    if (entries.length > 0) {
      setAnalysis(null)
      analyzeMut.mutate({ batch: entries, mhtmlMode, docxMode: next })
    }
  }

  const switchMode = (next: ImportMode) => {
    setMode(next)
    reset()
  }

  const columns = useMemo(
    () => [
      {
        title: '路径',
        dataIndex: 'path',
        key: 'path',
        ellipsis: true,
        render: (value: string) => <Typography.Text style={{ fontSize: 12 }}>{value}</Typography.Text>,
      },
      {
        title: '标题',
        dataIndex: 'title',
        key: 'title',
        width: 180,
        ellipsis: true,
      },
      {
        title: '格式',
        dataIndex: 'suffix',
        key: 'suffix',
        width: 160,
        render: (value: string, record: FileImportPreviewItem) => {
          const label = FORMAT_LABEL[value] ?? value
          return (
            <Space size={4} wrap>
              <AntTag color="blue">{label}</AntTag>
              {record.is_asset && (
                <AntTag color="default" data-testid="file-import-asset-tag">
                  原样存档
                </AntTag>
              )}
            </Space>
          )
        },
      },
      {
        title: '状态',
        dataIndex: 'status',
        key: 'status',
        width: 96,
        render: (value: FileImportPreviewItem['status']) =>
          value === 'conflict' ? <AntTag color="orange">同名</AntTag> : <AntTag color="green">新建</AntTag>,
      },
    ],
    [],
  )

  const busy = analyzeMut.isPending || importMut.isPending
  const targetText = parentLabel ? `「${parentLabel}」文件夹` : '根目录'

  /** 解析结果的紧凑统计：零值走次要色，避免一行里全是 0 抢注意力 */
  const summaryItems = analysis
    ? [
        { key: 'files', label: '文件', value: `${analysis.total_files} 个`, zero: analysis.total_files === 0 },
        { key: 'docs', label: '可导入', value: `${analysis.total_documents} 篇`, zero: analysis.total_documents === 0 },
        { key: 'assets', label: '原样存档', value: `${analysis.assets ?? 0} 个`, zero: (analysis.assets ?? 0) === 0 },
        { key: 'folders', label: '新建文件夹', value: `${analysis.total_folders} 个`, zero: analysis.total_folders === 0 },
        { key: 'conflicts', label: '同名冲突', value: `${analysis.conflicts} 篇`, zero: analysis.conflicts === 0 },
        { key: 'skipped', label: '跳过', value: `${analysis.skipped.length} 个`, zero: analysis.skipped.length === 0 },
        { key: 'warnings', label: '告警', value: `${analysis.warnings.length} 条`, zero: analysis.warnings.length === 0 },
      ]
    : []

  const footer = result
    ? [
        <Button key="close" type="primary" onClick={close}>
          完成
        </Button>,
      ]
    : [
        <Button key="cancel" onClick={close}>
          取消
        </Button>,
        entries.length > 0 && analysis ? (
          <Button key="repick" onClick={reset} data-testid="file-import-repick">
            重新选择
          </Button>
        ) : null,
        <Button
          key="submit"
          type="primary"
          data-testid="file-import-submit"
          disabled={entries.length === 0 || !analysis}
          loading={importMut.isPending}
          onClick={() => importMut.mutate(entries)}
        >
          开始导入
        </Button>,
      ]

  /** 模式选择器：单文件 / 文件夹 / Obsidian 库，库模式下也常驻以便随时切回 */
  const modeSelector = (
    <Space size={16} wrap>
      <Typography.Text type="secondary">导入模式</Typography.Text>
      <Radio.Group
        value={mode}
        onChange={e => switchMode(e.target.value as ImportMode)}
        optionType="button"
        data-testid="file-import-mode"
        options={[
          {
            value: 'single',
            label: (
              <Space size={6}>
                <span aria-hidden>
                  <FileTextOutlined />
                </span>
                单文件
              </Space>
            ),
          },
          {
            value: 'folder',
            label: (
              <Space size={6}>
                <span aria-hidden>
                  <FolderOpenOutlined />
                </span>
                文件夹
              </Space>
            ),
          },
          {
            value: 'vault',
            label: (
              <Space size={6}>
                <span aria-hidden>
                  <FileZipOutlined />
                </span>
                Obsidian 库
              </Space>
            ),
          },
        ]}
      />
    </Space>
  )

  return (
    <Modal
      title="导入"
      open={open}
      onCancel={close}
      width={760}
      destroyOnHidden
      mask={{ closable: !busy }}
      footer={mode === 'vault' ? null : footer}
      data-testid="file-import-modal"
    >
      {mode === 'vault' ? (
        /* Obsidian 库导入：独立表单体，自带动作按钮与落库流程 */
        <>
          {modeSelector}
          <div style={{ marginTop: 12 }}>
            <VaultImportForm
              workspaceId={workspaceId}
              parentId={parentId}
              parentLabel={parentLabel}
              onClose={close}
            />
          </div>
        </>
      ) : result ? (
        <Space orientation="vertical" size={12} style={{ width: '100%' }} data-testid="file-import-result">
          <Alert
            type="success"
            showIcon
            title={`已导入到${targetText}`}
            description={
              `新增 ${result.created} 篇 · 更新 ${result.updated} 篇 · 跳过 ${result.skipped} 个 · ` +
              `新建文件夹 ${result.folders_created} 个 · 原样存档 ${result.assets ?? 0} 个 · 内嵌图片 ${result.attachments} 个`
            }
          />
          {result.warnings.map(item => (
            <Alert key={`${item.path}:${item.message}`} type="warning" showIcon title={`${item.path}：${item.message}`} />
          ))}
          {result.skipped_files.length > 0 && (
            <div>
              <Typography.Text strong>跳过明细</Typography.Text>
              <ul style={{ margin: '4px 0 0', paddingLeft: 18, fontSize: 12 }}>
                {result.skipped_files.slice(0, 10).map(item => (
                  <li key={item.path}>
                    {item.path}（{item.reason}）
                  </li>
                ))}
              </ul>
            </div>
          )}
        </Space>
      ) : (
        <Space orientation="vertical" size={12} style={{ width: '100%' }}>
          {modeSelector}

          {/* 原生 file input：单文件模式选一个，文件夹模式带 webkitRelativePath */}
          <input
            ref={inputRef}
            type="file"
            accept={FILE_IMPORT_ACCEPT}
            multiple={mode === 'folder'}
            // webkitdirectory 非标准属性，React 需按字符串挂载
            {...(mode === 'folder' ? { webkitdirectory: '' } : {})}
            style={{ display: 'none' }}
            data-testid="file-import-input"
            onChange={event => {
              const files = event.target.files
              pick(files)
              // 清空 value：重选同一批文件也能触发 change
              event.target.value = ''
            }}
          />
          <ImportDropzone
            testId="file-import-dropzone"
            pickTestId="file-import-pick"
            helpTestId="file-import-help"
            icon={mode === 'folder' ? <FolderOpenOutlined /> : <FileTextOutlined />}
            title={mode === 'folder' ? '选择文件夹导入' : '选择文件导入'}
            subtitle={`导入到${targetText} · 支持 Markdown / Word / HTML / MHTML / PDF / Excel / PPT / 图片`}
            actionLabel={mode === 'folder' ? '选择文件夹' : '选择文件'}
            disabled={busy}
            onPick={() => inputRef.current?.click()}
            helpTitle="格式与处理方式"
            help={
              <ul style={{ margin: 0, paddingLeft: 18, fontSize: 12, lineHeight: 1.9, maxWidth: 360 }}>
                <li>转换：Markdown / HTML 直接转换；Word、MHTML 可勾选转换后编辑</li>
                <li>原样存档：PDF / Excel / PPT / 图片，以及勾选存档的 Word、MHTML；可预览、可下载，不可编辑</li>
                <li>旧版 .xls / .ppt / .doc 无在线预览，仅可下载</li>
              </ul>
            }
            selected={
              entries.length > 0 ? (
                <Typography.Text type="secondary" style={{ fontSize: 12 }} data-testid="file-import-picked">
                  已选 {entries.length} 个文件
                </Typography.Text>
              ) : null
            }
          />

          {analyzeMut.isPending && <Alert type="info" showIcon title="正在解析文件…" />}

          {analysis && (
            <>
              <ImportSummary items={summaryItems} testId="file-import-summary" />

              {analysis.skipped.map(item => (
                <Alert key={item.path} type="warning" showIcon title={`${item.path}：${item.reason}`} />
              ))}

              {analysis.conflicts > 0 && (
                <ImportConflictOptions
                  testId="file-import-conflict"
                  value={conflict}
                  onChange={setConflict}
                />
              )}

              <ImportOptionsPanel testId="file-import-options">
                <ImportSwitch
                  testId="file-import-mhtml-convert"
                  label="MHTML 转 Markdown"
                  checked={mhtmlMode === 'convert'}
                  onChange={checked => changeMhtmlMode(checked ? 'convert' : 'archive')}
                  disabled={!hasMhtml}
                  tooltip="MHTML 默认原样存档；开启后按网页转换链路转成可编辑文档"
                />
                <ImportSwitch
                  testId="file-import-docx-archive"
                  label="Word 原样存档"
                  checked={docxMode === 'archive'}
                  onChange={checked => changeDocxMode(checked ? 'archive' : 'convert')}
                  disabled={!hasDocx}
                  tooltip="Word 默认转 Markdown；开启后保留原件，阅读器内预览、不可编辑"
                />
                <ImportSwitch
                  testId="file-import-attachments"
                  label="导入内嵌图片"
                  checked={importAttachments}
                  onChange={setImportAttachments}
                  disabled={attachmentsDisabled}
                  tooltip="转换 Word / HTML / MHTML 时一并导入内嵌图片；MHTML 原样存档时素材已随原件保留"
                />
                <ImportStatusRadio value={status} onChange={setStatus} />
              </ImportOptionsPanel>

              {analysis.items.length === 0 ? (
                <Empty description="没有可导入的文件" />
              ) : (
                <div data-testid="file-import-preview">
                  <Table<FileImportPreviewItem>
                    size="small"
                    rowKey="path"
                    columns={columns}
                    dataSource={analysis.items}
                    pagination={{ pageSize: 8, size: 'small', hideOnSinglePage: true }}
                    scroll={{ y: 220 }}
                  />
                  {analysis.preview_truncated && <ImportTruncatedHint count={analysis.items.length} />}
                </div>
              )}
            </>
          )}
        </Space>
      )}
    </Modal>
  )
}
