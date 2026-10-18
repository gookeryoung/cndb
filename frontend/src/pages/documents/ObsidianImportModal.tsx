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
import { useMemo, useState } from 'react'
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
  Upload,
} from 'antd'
import { InboxOutlined } from '@ant-design/icons'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import {
  documentsApi,
  type VaultAnalyzeResult,
  type VaultConflictPolicy,
  type VaultImportResult,
  type VaultPreviewItem,
} from '@/api/documents'
import { formatSize } from '@/utils/formatSize'

interface Props {
  open: boolean
  onClose: () => void
  workspaceId: number
  /** 默认导入位置：当前浏览的文件夹（null = 根目录） */
  parentId?: number | null
  /** 当前文件夹标题，仅用于文案 */
  parentLabel?: string
}

const CONFLICT_OPTIONS: { value: VaultConflictPolicy; label: string; hint: string }[] = [
  { value: 'rename', label: '保留两份（自动改名）', hint: '同名文档追加「 (2)」' },
  { value: 'overwrite', label: '覆盖已有文档', hint: '生成新版本，历史可回溯' },
  { value: 'skip', label: '跳过同名文档', hint: '只导入库里新增的笔记' },
]

export default function ObsidianImportModal({ open, onClose, workspaceId, parentId, parentLabel }: Props) {
  const { message } = AntApp.useApp()
  const qc = useQueryClient()
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
    <Modal
      title="导入 Obsidian 文档库"
      open={open}
      onCancel={close}
      width={760}
      destroyOnHidden
      maskClosable={!busy}
      footer={footer}
      data-testid="vault-import-modal"
    >
      {result ? (
        <Space direction="vertical" size={12} style={{ width: '100%' }} data-testid="vault-import-result">
          <Alert
            type="success"
            showIcon
            message={`已导入到${targetText}`}
            description={`新增 ${result.created} 篇（其中转换文件 ${result.converted} 个）· 更新 ${result.updated} 篇 · 跳过 ${result.skipped} 篇 · 新建文件夹 ${result.folders_created} 个 · 附件 ${result.attachments} 个`}
          />
          {result.tags_created.length > 0 && (
            <Typography.Text type="secondary">
              新建标签：{result.tags_created.join('、')}
            </Typography.Text>
          )}
          {result.warnings.map(warning => (
            <Alert key={warning.code} type="warning" showIcon message={warning.message} />
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
        <Space direction="vertical" size={12} style={{ width: '100%' }}>
          <Upload.Dragger
            accept=".zip"
            maxCount={1}
            fileList={file ? [{ uid: 'vault', name: file.name, status: 'done' }] : []}
            beforeUpload={next => {
              setAnalysis(null)
              setFile(next)
              analyzeMut.mutate({ file: next })
              return false
            }}
            onRemove={() => {
              reset()
              return true
            }}
            disabled={busy}
            data-testid="vault-import-upload"
          >
            <p className="ant-upload-drag-icon">
              <InboxOutlined />
            </p>
            <p className="ant-upload-text">把 Obsidian 库文件夹压缩为 .zip 后拖到这里</p>
            <p className="ant-upload-hint">
              解析后会先展示预览（篇数 / 文件夹 / 附件 / 同名冲突），确认后才写入文档库；
              导入到{targetText}。
            </p>
          </Upload.Dragger>

          {analyzeMut.isPending && <Alert type="info" showIcon message="正在解析压缩包…" />}

          {analysis && (
            <>
              <Descriptions
                size="small"
                column={3}
                bordered
                data-testid="vault-import-summary"
                items={[
                  { key: 'notes', label: '笔记', children: `${analysis.total_markdown} 篇` },
                  {
                    key: 'converted',
                    label: '转换文件',
                    children: `${analysis.total_converted} 个`,
                  },
                  { key: 'folders', label: '新建文件夹', children: `${analysis.total_folders} 个` },
                  { key: 'conflicts', label: '同名冲突', children: `${analysis.conflicts} 篇` },
                  {
                    key: 'attachments',
                    label: '附件',
                    children: `${analysis.total_attachments} 个（${formatSize(analysis.total_attachment_bytes)}）`,
                  },
                  {
                    key: 'tags',
                    label: '标签',
                    children: analysis.tags.length
                      ? analysis.tags.slice(0, 5).join('、') + (analysis.tags.length > 5 ? '…' : '')
                      : '—',
                  },
                  {
                    key: 'ignored',
                    label: '忽略条目',
                    children: `${analysis.ignored_files} 个`,
                  },
                ]}
              />

              {analysis.warnings.map(warning => (
                <Alert key={warning.code} type="warning" showIcon message={warning.message} />
              ))}

              {analysis.conflicts > 0 && (
                <div data-testid="vault-import-conflict">
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
                    data-testid="vault-import-attachments"
                  />
                  <Typography.Text>导入图片等附件</Typography.Text>
                </Space>
                <Space size={8}>
                  <Switch checked={importTags} onChange={setImportTags} data-testid="vault-import-tags" />
                  <Typography.Text>按 front-matter 建标签</Typography.Text>
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
