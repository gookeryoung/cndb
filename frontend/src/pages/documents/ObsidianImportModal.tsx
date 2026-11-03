/**
 * Obsidian 文档库导入弹窗 —— 上传 zip → 预览（只读分析）→ 确认策略 → 落库。
 *
 * 两段式与数据表导入一致：
 * 1. ``POST /import/analyze`` 只解析不写库，用于展示数量、同名冲突、标签与告警；
 * 2. ``POST /import`` 按用户确认的冲突策略 / 附件 / 标签 / 状态真正导入。
 *
 * 落库口径由后端决定（目录 → 文件夹、front-matter title/tags、附件改写为 ``file:`` 引用），
 * 前端只负责把「会发生什么」讲清楚：冲突数、被忽略条目、不能表达的双链锚点/别名。
 */
import { useMemo, useRef, useState } from 'react'
import {
  Alert,
  App as AntApp,
  Button,
  Empty,
  Modal,
  Space,
  Table,
  Tag as AntTag,
  Typography,
} from 'antd'
import { FileZipOutlined } from '@ant-design/icons'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import {
  documentsApi,
  type VaultAnalyzeResult,
  type VaultConflictPolicy,
  type VaultImportResult,
  type VaultPreviewItem,
} from '@/api/documents'
import { formatSize } from '@/utils/formatSize'
import {
  ImportConflictOptions,
  ImportDropzone,
  ImportOptionsPanel,
  ImportStatusRadio,
  ImportSummary,
  ImportSwitch,
  ImportTruncatedHint,
} from './importUi'

interface Props {
  workspaceId: number
  /** 默认导入位置：当前浏览的文件夹（null = 根目录） */
  parentId?: number | null
  /** 当前文件夹标题，仅用于文案 */
  parentLabel?: string
  /** 表单体关闭回调（取消 / 完成） */
  onClose: () => void
}

/** 库导入表单体：上传 zip → 预览 → 确认策略 → 落库，动作按钮内置于表单底部（不依赖 Modal footer） */
export function VaultImportForm({ workspaceId, parentId, parentLabel, onClose }: Props) {
  const { message } = AntApp.useApp()
  const qc = useQueryClient()
  const inputRef = useRef<HTMLInputElement>(null)
  const [file, setFile] = useState<File | null>(null)
  const [analysis, setAnalysis] = useState<VaultAnalyzeResult | null>(null)
  const [result, setResult] = useState<VaultImportResult | null>(null)
  const [conflict, setConflict] = useState<VaultConflictPolicy>('rename')
  const [importAttachments, setImportAttachments] = useState(true)
  const [importTags, setImportTags] = useState(true)
  const [status, setStatus] = useState<'draft' | 'published'>('draft')

  const reset = () => {
    setFile(null)
    setAnalysis(null)
    setResult(null)
  }

  const close = () => {
    reset()
    onClose()
  }

  const analyzeMut = useMutation({
    mutationFn: (payload: { file: File }) => documentsApi.vaultAnalyze(workspaceId, payload.file, parentId),
    onSuccess: data => {
      setAnalysis(data)
      // 有冲突时默认「自动改名」；无冲突时策略无实际影响
      setConflict('rename')
    },
    onError: (err: unknown) => {
      setFile(null)
      message.error(err instanceof Error ? err.message : '解析失败，请确认上传的是 Obsidian 库 zip 包')
    },
  })

  const importMut = useMutation({
    mutationFn: (payload: { file: File }) =>
      documentsApi.vaultImport(workspaceId, payload.file, {
        parentId,
        conflict,
        importAttachments,
        importTags,
        status,
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

  const columns = useMemo(
    () => [
      {
        title: '库内路径',
        dataIndex: 'path',
        key: 'path',
        ellipsis: true,
        render: (value: string) => <Typography.Text style={{ fontSize: 12 }}>{value}</Typography.Text>,
      },
      {
        title: '标题',
        dataIndex: 'title',
        key: 'title',
        width: 200,
        ellipsis: true,
        render: (value: string, item: VaultPreviewItem) =>
          item.kind && item.kind !== 'markdown' ? (
            <Space size={4}>
              <AntTag color="blue">{item.kind === 'canvas' ? 'Canvas' : 'Base'}</AntTag>
              <span>{value}</span>
            </Space>
          ) : (
            value
          ),
      },
      {
        title: '标签',
        dataIndex: 'tags',
        key: 'tags',
        width: 180,
        render: (tags: string[]) =>
          tags.length === 0 ? (
            <Typography.Text type="secondary">—</Typography.Text>
          ) : (
            <Space size={4} wrap>
              {tags.slice(0, 3).map(tag => (
                <AntTag key={tag}>{tag}</AntTag>
              ))}
              {tags.length > 3 && <Typography.Text type="secondary">+{tags.length - 3}</Typography.Text>}
            </Space>
          ),
      },
      {
        title: '状态',
        dataIndex: 'status',
        key: 'status',
        width: 96,
        render: (value: VaultPreviewItem['status']) =>
          value === 'conflict' ? <AntTag color="orange">同名</AntTag> : <AntTag color="green">新建</AntTag>,
      },
    ],
    [],
  )

  const busy = analyzeMut.isPending || importMut.isPending
  const targetText = parentLabel ? `「${parentLabel}」文件夹` : '根目录'

  /** 库解析结果的紧凑统计（口径与合并成一行展示，零值走次要色） */
  const summaryItems = analysis
    ? [
        { key: 'notes', label: '笔记', value: `${analysis.total_markdown} 篇`, zero: analysis.total_markdown === 0 },
        {
          key: 'converted',
          label: '转换文件',
          value: `${analysis.total_converted} 个`,
          zero: analysis.total_converted === 0,
        },
        { key: 'folders', label: '新建文件夹', value: `${analysis.total_folders} 个`, zero: analysis.total_folders === 0 },
        { key: 'conflicts', label: '同名冲突', value: `${analysis.conflicts} 篇`, zero: analysis.conflicts === 0 },
        {
          key: 'attachments',
          label: '附件',
          value: analysis.total_attachments
            ? `${analysis.total_attachments} 个 · ${formatSize(analysis.total_attachment_bytes)}`
            : '0 个',
          zero: analysis.total_attachments === 0,
        },
        {
          key: 'tags',
          label: '标签',
          value: analysis.tags.length
            ? analysis.tags.slice(0, 5).join('、') + (analysis.tags.length > 5 ? '…' : '')
            : '—',
          zero: analysis.tags.length === 0,
        },
        { key: 'ignored', label: '忽略条目', value: `${analysis.ignored_files} 个`, zero: analysis.ignored_files === 0 },
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
        file && analysis ? (
          <Button key="reupload" onClick={reset}>
            重新选择
          </Button>
        ) : null,
        <Button
          key="submit"
          type="primary"
          data-testid="vault-import-submit"
          disabled={!file || !analysis}
          loading={importMut.isPending}
          onClick={() => file && importMut.mutate({ file })}
        >
          开始导入
        </Button>,
      ]

  return (
    <>
      {result ? (
        <Space orientation="vertical" size={12} style={{ width: '100%' }} data-testid="vault-import-result">
          <Alert
            type="success"
            showIcon
            title={`已导入到${targetText}`}
            description={`新增 ${result.created} 篇（其中转换文件 ${result.converted} 个）· 更新 ${result.updated} 篇 · 跳过 ${result.skipped} 篇 · 新建文件夹 ${result.folders_created} 个 · 附件 ${result.attachments} 个`}
          />
          {result.tags_created.length > 0 && (
            <Typography.Text type="secondary">
              新建标签：{result.tags_created.join('、')}
            </Typography.Text>
          )}
          {result.warnings.map(warning => (
            <Alert key={warning.code} type="warning" showIcon title={warning.message} />
          ))}
          {result.skipped_notes.length > 0 && (
            <div>
              <Typography.Text strong>跳过明细</Typography.Text>
              <ul style={{ margin: '4px 0 0', paddingLeft: 18, fontSize: 12 }}>
                {result.skipped_notes.slice(0, 10).map(item => (
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
          {/* 原生 zip input：与单文件 / 文件夹模式共用同一套拖放区样式 */}
          <input
            ref={inputRef}
            type="file"
            accept=".zip"
            style={{ display: 'none' }}
            data-testid="vault-import-input"
            onChange={event => {
              const next = event.target.files?.[0]
              event.target.value = ''
              if (!next) return
              setAnalysis(null)
              setFile(next)
              analyzeMut.mutate({ file: next })
            }}
          />
          <ImportDropzone
            testId="vault-import-upload"
            pickTestId="vault-import-pick"
            helpTestId="vault-import-help"
            icon={<FileZipOutlined />}
            title="上传 Obsidian 库压缩包"
            subtitle={`导入到${targetText} · 先把库文件夹压缩为 .zip，解析后先预览再写入`}
            actionLabel="选择 .zip 文件"
            disabled={busy}
            onPick={() => inputRef.current?.click()}
            helpTitle="库导入说明"
            help={
              <ul style={{ margin: 0, paddingLeft: 18, fontSize: 12, lineHeight: 1.9, maxWidth: 360 }}>
                <li>目录结构还原为文件夹，front-matter 的 title / tags 生效</li>
                <li>附件按引用改写为站内文件，双链转为站内链接</li>
                <li>.canvas / .base 转为文档，无法识别的条目计入「忽略条目」</li>
              </ul>
            }
            selected={
              file ? (
                <Typography.Text type="secondary" style={{ fontSize: 12 }} data-testid="vault-import-picked">
                  已选 {file.name}
                </Typography.Text>
              ) : null
            }
          />

          {analyzeMut.isPending && <Alert type="info" showIcon title="正在解析压缩包…" />}

          {analysis && (
            <>
              <ImportSummary items={summaryItems} testId="vault-import-summary" />

              {analysis.warnings.map(warning => (
                <Alert key={warning.code} type="warning" showIcon title={warning.message} />
              ))}

              {analysis.conflicts > 0 && (
                <ImportConflictOptions
                  testId="vault-import-conflict"
                  value={conflict}
                  onChange={setConflict}
                />
              )}

              <ImportOptionsPanel testId="vault-import-options">
                <ImportSwitch
                  testId="vault-import-attachments"
                  label="导入图片等附件"
                  checked={importAttachments}
                  onChange={setImportAttachments}
                  tooltip="按库内引用把图片等附件导入为站内文件"
                />
                <ImportSwitch
                  testId="vault-import-tags"
                  label="按 front-matter 建标签"
                  checked={importTags}
                  onChange={setImportTags}
                  tooltip="读取笔记 front-matter 的 tags 并自动创建标签"
                />
                <ImportStatusRadio value={status} onChange={setStatus} />
              </ImportOptionsPanel>

              {analysis.items.length === 0 ? (
                <Empty description="压缩包里没有 markdown 文档" />
              ) : (
                <div data-testid="vault-import-preview">
                  <Table<VaultPreviewItem>
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
      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>{footer}</div>
    </>
  )
}

/** 独立弹窗包装：通用导入弹窗内的「库」模式直接复用 VaultImportForm，此包装保留单独打开的入口 */
export default function ObsidianImportModal(props: Props) {
  return (
    <Modal
      title="导入 Obsidian 文档库"
      open
      onCancel={props.onClose}
      width={760}
      destroyOnHidden
      footer={null}
      data-testid="vault-import-modal"
    >
      <VaultImportForm {...props} />
    </Modal>
  )
}
