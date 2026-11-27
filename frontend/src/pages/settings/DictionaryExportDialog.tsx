/** 导出字段文档对话框（ADR 0188 C11）.
 *
 * 两种导出范围共用同一个对话框：
 * - 单表：当前表（`dictionaryApi.exportTable`）
 * - 合订：本工作区全部表 / 指定表（`dictionaryApi.exportWorkspace`）
 *
 * 交互范式与 `pages/import-export` 的导出面板一致：格式记忆在 localStorage，
 * 生成后用 Blob 触发下载（文件名从 `Content-Disposition` 解析）。
 */
import { useEffect, useMemo, useState } from 'react'
import { Modal, Form, Radio, Checkbox, Select, Alert, Button, Space, App as AntApp } from 'antd'
import { DownloadOutlined, FileTextOutlined, TableOutlined, CodeOutlined, FileWordOutlined, FilePdfOutlined } from '@ant-design/icons'
import { dictionaryApi } from '@/api'
import type { TableDictionaryFormat, TableSummary } from '@/api'

/** 上次选择的格式（单键记忆，与行导出的 `cndb_export_format` 分开存） */
const FORMAT_KEY = 'cndb_dictionary_format'

export const DICTIONARY_FORMATS: Array<{ value: TableDictionaryFormat; label: string; icon: React.ReactNode }> = [
  { value: 'md', label: 'Markdown', icon: <FileTextOutlined /> },
  { value: 'xlsx', label: 'Excel（多表）', icon: <TableOutlined /> },
  { value: 'docx', label: 'Word', icon: <FileWordOutlined /> },
  { value: 'pdf', label: 'PDF', icon: <FilePdfOutlined /> },
  { value: 'json', label: 'JSON 契约', icon: <CodeOutlined /> },
]

/** docx / pdf 可用的内置排版模板（与后端 BUILTIN_TEMPLATES 对齐） */
export const DICTIONARY_TEMPLATES: Array<{ value: string; label: string }> = [
  { value: 'builtin:research', label: '研究报告（默认）' },
  { value: 'builtin:techreport', label: '技术报告' },
  { value: 'builtin:official', label: '公文' },
  { value: 'builtin:thesis', label: '论文' },
]

export type DictionaryScope = 'table' | 'workspace'

export interface DictionaryExportDialogProps {
  open: boolean
  onClose: () => void
  wid: string
  /** 当前表（单表导出用） */
  tid: string
  tableName?: string
  /** 可合订的表清单（工作区级导出用；缺省时只允许单表） */
  tables?: TableSummary[]
  /** 默认范围 */
  defaultScope?: DictionaryScope
  /** 结构是否已变更（用于提示重新导出） */
  stale?: boolean
  /** 导出成功后回调（父层记录结构指纹，用于下次「结构已变更」比对） */
  onExported?: () => void
}

function readSavedFormat(): TableDictionaryFormat {
  try {
    const saved = localStorage.getItem(FORMAT_KEY)
    if (saved && DICTIONARY_FORMATS.some(f => f.value === saved)) return saved as TableDictionaryFormat
  } catch { /* localStorage 不可用时用默认 */ }
  return 'md'
}

/** 触发浏览器下载（Blob + 临时 a 标签） */
export function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  // 延迟释放：部分浏览器在 click 同步返回前仍需要 url 有效
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

export default function DictionaryExportDialog({
  open, onClose, wid, tid, tableName, tables = [], defaultScope = 'table', stale = false, onExported,
}: DictionaryExportDialogProps) {
  const { message } = AntApp.useApp()
  const [format, setFormat] = useState<TableDictionaryFormat>(readSavedFormat)
  const [scope, setScope] = useState<DictionaryScope>(defaultScope)
  const [includeInternal, setIncludeInternal] = useState(false)
  const [template, setTemplate] = useState<string>('builtin:research')
  const [tableIds, setTableIds] = useState<Array<string>>([])
  const [pending, setPending] = useState(false)

  // 每次打开重置范围（格式记忆保留，其余回到默认）
  useEffect(() => {
    if (!open) return
    setScope(defaultScope)
    setIncludeInternal(false)
    setTableIds([])
  }, [open, defaultScope])

  const needsTemplate = format === 'docx' || format === 'pdf'
  const tableOptions = useMemo(
    () => tables.map(t => ({ value: String(t.id), label: t.name })),
    [tables],
  )

  const handleExport = async () => {
    setPending(true)
    try {
      const params = {
        format,
        include_internal: includeInternal,
        ...(needsTemplate ? { template } : {}),
      }
      const { blob, filename } = scope === 'table'
        ? await dictionaryApi.exportTable(wid, tid, params)
        : await dictionaryApi.exportWorkspace(wid, { ...params, tableIds })
      downloadBlob(blob, filename)
      try { localStorage.setItem(FORMAT_KEY, format) } catch { /* 忽略配额错误 */ }
      onExported?.()
      message.success('已生成字段文档')
      onClose()
    } catch (err) {
      // 503 = docx/pdf 渲染器不可用（未启用文档模块）：明确引导改用 md / xlsx
      const detail = (err as { response?: { data?: { detail?: string }; status?: number } })
      const status = detail?.response?.status
      const text = detail?.response?.data?.detail
      message.error(text || (status === 503 ? '当前实例没有 Word / PDF 渲染能力，请改用 Markdown 或 Excel' : '导出失败，请重试'))
    } finally {
      setPending(false)
    }
  }

  return (
    <Modal
      title="导出字段文档"
      open={open}
      onCancel={onClose}
      width={560}
      destroyOnHidden
      footer={(
        <Space>
          <Button onClick={onClose}>取消</Button>
          <Button
            type="primary"
            icon={<DownloadOutlined />}
            loading={pending}
            onClick={() => { void handleExport() }}
            data-testid="dictionary-export-confirm"
          >
            导出
          </Button>
        </Space>
      )}
    >
      {stale && (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 12 }}
          message="上次导出后表结构已变更"
          description="字段有增删或类型 / 约束 / 顺序变化，建议重新导出以保持文档与实现一致。"
          data-testid="dictionary-stale-hint"
        />
      )}
      <Form layout="vertical">
        <Form.Item label="导出范围" style={{ marginBottom: 12 }}>
          <Radio.Group
            value={scope}
            onChange={e => setScope(e.target.value as DictionaryScope)}
            data-testid="dictionary-scope"
          >
            <Radio.Button value="table">当前表{tableName ? `（${tableName}）` : ''}</Radio.Button>
            <Radio.Button value="workspace" disabled={tables.length === 0}>整个工作区</Radio.Button>
          </Radio.Group>
        </Form.Item>

        {scope === 'workspace' && tables.length > 0 && (
          <Form.Item
            label="限定表（留空 = 全部未删除表）"
            style={{ marginBottom: 12 }}
          >
            <Select
              mode="multiple"
              allowClear
              placeholder="全部表"
              value={tableIds}
              onChange={setTableIds}
              options={tableOptions}
              data-testid="dictionary-table-ids"
            />
          </Form.Item>
        )}

        <Form.Item label="格式" style={{ marginBottom: 12 }}>
          <Radio.Group
            value={format}
            onChange={e => setFormat(e.target.value as TableDictionaryFormat)}
            data-testid="dictionary-format"
          >
            {DICTIONARY_FORMATS.map(f => (
              <Radio.Button key={f.value} value={f.value}>
                {f.icon} {f.label}
              </Radio.Button>
            ))}
          </Radio.Group>
        </Form.Item>

        {needsTemplate && (
          <Form.Item label="排版模板" style={{ marginBottom: 12 }}>
            <Select value={template} onChange={setTemplate} options={DICTIONARY_TEMPLATES} data-testid="dictionary-template" />
          </Form.Item>
        )}

        <Form.Item style={{ marginBottom: 0 }}>
          <Checkbox
            checked={includeInternal}
            onChange={e => setIncludeInternal(e.target.checked)}
            data-testid="dictionary-include-internal"
          >
            包含内部实现细节（物理表名 / 物理列名 / 字段顺序）
          </Checkbox>
        </Form.Item>
      </Form>
      <div style={{ marginTop: 12, color: 'var(--cn-text-secondary)', fontSize: 'var(--cn-text-xs)' }}>
        文档只描述字段结构，不含任何行数据；机密字段的口径与示例值默认脱敏为「（受限）」。
      </div>
    </Modal>
  )
}
