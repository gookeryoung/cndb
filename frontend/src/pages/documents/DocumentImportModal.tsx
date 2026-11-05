/**
 * 通用文件导入弹窗 —— 单文件 / 文件夹模式，支持 md、docx、html、mhtml。
 *
 * 两段式与数据表/Obsidian 导入一致：
 * 1. ``POST /import/files/analyze`` 只解析（本地读取 + 转换）不写库，展示篇数 / 文件夹 / 冲突 / 跳过；
 * 2. ``POST /import/files`` 按确认的冲突策略 / 状态 / 附件开关真正导入。
 *
 * 格式化口径由后端决定（docx / html → Markdown、标题识别、清理多余空白；docx 可选原件存档），前端只把「会发生什么」
 * 讲清楚：转 Markdown / 原样存档的篇数、待建文件夹、同名冲突、被跳过的文件与告警。
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
  Spin,
  Table,
  Tag as AntTag,
  Typography,
} from 'antd'
import { AppstoreOutlined, FileTextOutlined, FileZipOutlined } from '@ant-design/icons'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { VaultImportForm } from './ObsidianImportModal'
import {
  ImportChoice,
  ImportConflictOptions,
  ImportDropzone,
  ImportFooter,
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

type ImportMode = 'single' | 'archive' | 'vault'

/** 处理方式（互斥）：把源格式转成可编辑 Markdown，或保留原件原样存档 */
type ProcessMode = 'convert' | 'archive'

const PROCESS_OPTIONS: Array<{ value: ProcessMode; label: string }> = [
  { value: 'convert', label: '转 Markdown' },
  { value: 'archive', label: '原样存档' },
]

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

/** 把浏览器选中的文件整理为批次条目（单文件模式取文件名） */
function toEntries(files: FileList | null): FileImportEntry[] {
  if (!files) return []
  return Array.from(files).map(file => ({ file, path: file.name }))
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
  /** 处理方式：转 Markdown / 原样存档（互斥，统一作用于 Word 与 MHTML） */
  const [processMode, setProcessMode] = useState<ProcessMode>('convert')
  /** 最近一次请求的处理方式：切换分段后旧请求晚到时不覆盖新结果 */
  const latestModeRef = useRef<ProcessMode>('convert')
  const [status, setStatus] = useState<'draft' | 'published'>('draft')

  /** 批次里是否含 MHTML（.mhtml / .mht） */
  const hasMhtml = entries.some(entry => /\.(mhtml|mht)$/i.test(entry.path))
  /** 批次里是否含 Word（.docx） */
  const hasDocx = entries.some(entry => /\.docx$/i.test(entry.path))
  /** 只有 Word / MHTML 支持两种处理方式；Markdown / HTML 固定转 Markdown，PDF / Office / 图片固定原样存档 */
  const hasProcessChoice = hasDocx || hasMhtml
  /** 内嵌图片开关只在「MHTML 原样存档」时无意义（素材已随原件保留），其余批次均可用 */
  const attachmentsDisabled = hasMhtml && processMode === 'archive'

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
    mutationFn: (payload: { batch: FileImportEntry[]; processMode: ProcessMode }) =>
      documentsApi.fileImportAnalyze(workspaceId, {
        entries: payload.batch,
        parentId,
        // 统一处理方式：Word 与 MHTML 同取一个值（互斥项，不再各配一个开关）
        mhtmlMode: payload.processMode,
        docxMode: payload.processMode,
      }),
    onSuccess: (data, variables) => {
      // 只接受与当前选择一致的结果；切换分段期间保留旧预览原地刷新，不卸载选项区
      if (variables.processMode !== latestModeRef.current) return
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
        mhtmlMode: processMode,
        docxMode: processMode,
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
    const batch = toEntries(files)
    if (batch.length === 0) return
    latestModeRef.current = processMode
    setEntries(batch)
    setAnalysis(null)
    setResult(null)
    analyzeMut.mutate({ batch, processMode })
  }

  /** 切换处理方式会改变落库渲染族（markdown ↔ 原件），已选批次需要重新解析.
   *
   * 不把 analysis 置空：选项区与预览保持挂载，只进入 loading 态，解析回来后原地替换，
   * 避免弹窗内容「消失再出现」的闪烁；旧请求晚到的结果由 latestModeRef 丢弃。
   */
  const changeProcessMode = (next: ProcessMode) => {
    setProcessMode(next)
    latestModeRef.current = next
    if (entries.length > 0) {
      analyzeMut.mutate({ batch: entries, processMode: next })
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
              {record.is_asset ? (
                <AntTag color="default" data-testid="file-import-asset-tag">原样存档</AntTag>
              ) : (
                <AntTag color="green" data-testid="file-import-convert-tag">转 Markdown</AntTag>
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
        { key: 'docs', label: '转 Markdown', value: `${analysis.total_documents} 篇`, zero: analysis.total_documents === 0 },
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
          disabled={entries.length === 0 || !analysis || analyzeMut.isPending}
          loading={importMut.isPending}
          onClick={() => importMut.mutate(entries)}
        >
          开始导入
        </Button>,
      ]

  /** 模式选择器：单文件 / 压缩包 / Obsidian 库（压缩包与 Obsidian 库均上传 .zip，与导出对齐） */
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
            value: 'archive',
            label: (
              <Space size={6}>
                <span aria-hidden>
                  <FileZipOutlined />
                </span>
                压缩包
              </Space>
            ),
          },
          {
            value: 'vault',
            label: (
              <Space size={6}>
                <span aria-hidden>
                  <AppstoreOutlined />
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
      footer={null}
      data-testid="file-import-modal"
    >
      {/* 统一纵向节奏：三种模式同一容器 + 12px 间距，首个元素贴齐弹窗内容顶部 */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12, width: '100%' }}>
        {mode === 'archive' || mode === 'vault' ? (
          /* 压缩包 / Obsidian 库导入：独立表单体，自带动作按钮与落库流程 */
          <>
            {modeSelector}
            <VaultImportForm
              workspaceId={workspaceId}
              parentId={parentId}
              parentLabel={parentLabel}
              style={mode === 'vault' ? 'obsidian' : 'archive'}
              onClose={close}
            />
          </>
        ) : mode === 'single' && result ? (
          <div
            data-testid="file-import-result"
            style={{ display: 'flex', flexDirection: 'column', gap: 12 }}
          >
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
            <ImportFooter>{footer}</ImportFooter>
          </div>
        ) : (
          <>
            {modeSelector}

            {/* 原生 file input：单文件模式选一个；压缩包 / 库模式走 VaultImportForm 的 zip 输入 */}
            <input
              ref={inputRef}
              type="file"
              accept={FILE_IMPORT_ACCEPT}
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
              icon={<FileTextOutlined />}
              title="选择文件导入"
              subtitle={`导入到${targetText} · 支持 Markdown / Word / HTML / MHTML / PDF / Excel / PPT / 图片`}
              actionLabel="选择文件"
              disabled={busy}
              onPick={() => inputRef.current?.click()}
              helpTitle="格式与处理方式"
              help={
                <ul style={{ margin: 0, paddingLeft: 18, fontSize: 12, lineHeight: 1.9, maxWidth: 360 }}>
                  <li>转 Markdown：Markdown / HTML 直接转换；Word、MHTML 选「转 Markdown」后转为可编辑文档</li>
                  <li>原样存档：PDF / Excel / PPT / 图片固定原样存档；Word、MHTML 选「原样存档」时保留原件，可预览、可下载，不可编辑</li>
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
                  <ImportChoice<ProcessMode>
                    label="处理方式"
                    value={processMode}
                    onChange={changeProcessMode}
                    options={PROCESS_OPTIONS}
                    disabled={!hasProcessChoice}
                    tooltip="仅对 Word / MHTML 生效：转 Markdown 得到可编辑文档；原样存档保留原件，可预览 / 下载、不可编辑。Markdown / HTML 始终转 Markdown，PDF / Office / 图片始终原样存档。"
                    testId="file-import-process-mode"
                  />
                  <ImportSwitch
                    testId="file-import-attachments"
                    label="导入内嵌图片"
                    checked={importAttachments}
                    onChange={setImportAttachments}
                    disabled={attachmentsDisabled}
                    tooltip="转 Markdown 的 Word / HTML / MHTML 一并导入内嵌图片；原样存档时素材已随原件保留"
                  />
                  <ImportStatusRadio value={status} onChange={setStatus} />
                </ImportOptionsPanel>

                {analysis.items.length === 0 ? (
                  <Empty description="没有可导入的文件" />
                ) : (
                  <Spin spinning={analyzeMut.isPending} size="small">
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
                  </Spin>
                )}
              </>
            )}
            <ImportFooter>{footer}</ImportFooter>
          </>
        )}
      </div>
    </Modal>
  )
}
