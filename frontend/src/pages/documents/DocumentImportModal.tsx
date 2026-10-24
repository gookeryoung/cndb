/**
 * 通用文件导入弹窗 —— 单文件 / 文件夹模式，支持 md、docx、html。
 *
 * 两段式与数据表/Obsidian 导入一致：
 * 1. ``POST /import/files/analyze`` 只解析（本地读取 + 转换）不写库，展示篇数 / 文件夹 / 冲突 / 跳过；
 * 2. ``POST /import/files`` 按确认的冲突策略 / 状态 / 附件开关真正导入。
 *
 * 格式化口径由后端决定（docx / html → Markdown、标题识别、清理多余空白），前端只把「会发生什么」
 * 讲清楚：可导入篇数、待建文件夹、同名冲突、被跳过的文件与告警。
 */
import { useMemo, useRef, useState } from 'react'
import {
  Alert,
  App as AntApp,
  Button,
  Descriptions,
  Empty,
  Modal,
  Radio,
  Space,
  Switch,
  Table,
  Tag as AntTag,
  Typography,
} from 'antd'
import { FileAddOutlined, FolderOpenOutlined, InboxOutlined } from '@ant-design/icons'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import {
  documentsApi,
  FILE_IMPORT_ACCEPT,
  type FileImportAnalyzeResult,
  type FileImportEntry,
  type FileImportPreviewItem,
  type FileImportResult,
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

type ImportMode = 'single' | 'folder'

const CONFLICT_OPTIONS: { value: VaultConflictPolicy; label: string; hint: string }[] = [
  { value: 'rename', label: '保留两份（自动改名）', hint: '同名文档追加「 (2)」' },
  { value: 'overwrite', label: '覆盖已有文档', hint: '生成新版本，历史可回溯' },
  { value: 'skip', label: '跳过同名文档', hint: '只导入新增的文件' },
]

const FORMAT_LABEL: Record<string, string> = {
  '.md': 'Markdown',
  '.markdown': 'Markdown',
  '.docx': 'Word',
  '.html': 'HTML',
  '.htm': 'HTML',
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
  const [status, setStatus] = useState<'draft' | 'published'>('draft')

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
    mutationFn: (batch: FileImportEntry[]) =>
      documentsApi.fileImportAnalyze(workspaceId, { entries: batch, parentId }),
    onSuccess: data => {
      setAnalysis(data)
      setConflict('rename')
    },
    onError: (err: unknown) => {
      reset()
      message.error(
        err instanceof Error ? err.message : '解析失败，请确认文件格式在支持范围内（md / docx / html / pdf / Office / 图片）',
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
    analyzeMut.mutate(batch)
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

  return (
    <Modal
      title="导入文件"
      open={open}
      onCancel={close}
      width={760}
      destroyOnHidden
      maskClosable={!busy}
      footer={footer}
      data-testid="file-import-modal"
    >
      {result ? (
        <Space direction="vertical" size={12} style={{ width: '100%' }} data-testid="file-import-result">
          <Alert
            type="success"
            showIcon
            message={`已导入到${targetText}`}
            description={
              `新增 ${result.created} 篇 · 更新 ${result.updated} 篇 · 跳过 ${result.skipped} 个 · ` +
              `新建文件夹 ${result.folders_created} 个 · 原样存档 ${result.assets ?? 0} 个 · 内嵌图片 ${result.attachments} 个`
            }
          />
          {result.warnings.map(item => (
            <Alert key={`${item.path}:${item.message}`} type="warning" showIcon message={`${item.path}：${item.message}`} />
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
        <Space direction="vertical" size={12} style={{ width: '100%' }}>
          <Space size={16} wrap>
            <Typography.Text type="secondary">导入模式</Typography.Text>
            <Radio.Group
              value={mode}
              onChange={e => switchMode(e.target.value as ImportMode)}
              optionType="button"
              data-testid="file-import-mode"
              options={[
                { value: 'single', label: '单个文件' },
                { value: 'folder', label: '文件夹' },
              ]}
            />
          </Space>

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
            onChange={e => pick(e.target.files)}
          />
          <div
            style={{
              border: '1px dashed var(--cn-border)',
              borderRadius: 8,
              padding: '24px 16px',
              textAlign: 'center',
            }}
          >
            <p style={{ fontSize: 32, margin: 0, color: 'var(--cn-text-muted)' }}>
              {mode === 'folder' ? <FolderOpenOutlined /> : <InboxOutlined />}
            </p>
            <p style={{ margin: '8px 0' }}>
              {mode === 'folder' ? '选择一个文件夹' : '选择一个文件'}
            </p>
            <Button
              icon={mode === 'folder' ? <FolderOpenOutlined /> : <FileAddOutlined />}
              disabled={busy}
              data-testid="file-import-pick"
              onClick={() => inputRef.current?.click()}
            >
              {mode === 'folder' ? '选择文件夹' : '选择文件'}
            </Button>
            <p style={{ margin: '8px 0 0', fontSize: 12, color: 'var(--cn-text-muted)' }}>
              支持 Markdown（.md）、Word（.docx）、HTML（.html）——导入时自动转换为 Markdown 并清理空白；
              PDF、Excel（.xlsx/.xls）、PowerPoint（.pptx/.ppt）与图片（png/jpg/gif/webp/svg/bmp）
              原样存档，导入后在阅读器里预览、可下载原件（不参与编辑）。导入到{targetText}。
            </p>
            {entries.length > 0 && (
              <Typography.Text type="secondary" style={{ fontSize: 12 }} data-testid="file-import-picked">
                已选择 {entries.length} 个文件
              </Typography.Text>
            )}
          </div>

          {analyzeMut.isPending && <Alert type="info" showIcon message="正在解析文件…" />}

          {analysis && (
            <>
              <Descriptions
                size="small"
                column={3}
                bordered
                data-testid="file-import-summary"
                items={[
                  { key: 'files', label: '文件', children: `${analysis.total_files} 个` },
                  { key: 'docs', label: '可导入文档', children: `${analysis.total_documents} 篇` },
                  { key: 'folders', label: '新建文件夹', children: `${analysis.total_folders} 个` },
                  { key: 'assets', label: '原样存档', children: `${analysis.assets ?? 0} 个` },
                  { key: 'conflicts', label: '同名冲突', children: `${analysis.conflicts} 篇` },
                  { key: 'skipped', label: '跳过', children: `${analysis.skipped.length} 个` },
                  { key: 'warnings', label: '告警', children: `${analysis.warnings.length} 条` },
                ]}
              />

              {analysis.skipped.map(item => (
                <Alert key={item.path} type="warning" showIcon message={`${item.path}：${item.reason}`} />
              ))}

              {analysis.conflicts > 0 && (
                <div data-testid="file-import-conflict">
                  <Typography.Text strong>同名文档处理方式</Typography.Text>
                  <Radio.Group
                    value={conflict}
                    onChange={e => setConflict(e.target.value as VaultConflictPolicy)}
                    style={{ display: 'flex', flexDirection: 'column', gap: 6, marginTop: 6 }}
                  >
                    {CONFLICT_OPTIONS.map(option => (
                      <Radio key={option.value} value={option.value}>
                        {option.label}
                        <Typography.Text type="secondary" style={{ marginLeft: 8, fontSize: 12 }}>
                          {option.hint}
                        </Typography.Text>
                      </Radio>
                    ))}
                  </Radio.Group>
                </div>
              )}

              <Space size={24} wrap>
                <Space size={8}>
                  <Switch
                    checked={importAttachments}
                    onChange={setImportAttachments}
                    data-testid="file-import-attachments"
                  />
                  <Typography.Text>导入内嵌图片</Typography.Text>
                </Space>
                <Space size={8}>
                  <Typography.Text type="secondary">文档状态</Typography.Text>
                  <Radio.Group
                    value={status}
                    onChange={e => setStatus(e.target.value as 'draft' | 'published')}
                    optionType="button"
                    size="small"
                    options={[
                      { value: 'draft', label: '草稿' },
                      { value: 'published', label: '已发布' },
                    ]}
                  />
                </Space>
              </Space>

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
                  {analysis.preview_truncated && (
                    <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                      预览仅展示前 {analysis.items.length} 篇，其余同样会被导入。
                    </Typography.Text>
                  )}
                </div>
              )}
            </>
          )}
        </Space>
      )}
    </Modal>
  )
}
