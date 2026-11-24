/** 批量查找替换对话框（需求 0149）.
 *
 * 流程：选字段 + 填查找 / 替换 → 「预览」拿到匹配行数与前后值样例 → 「确认替换」落库。
 * 只列文本类字段（后端还会再校验：lookup / formula / 数字等一律 400）。
 * 预览与落库都只作用于当前视图筛选范围（后端用与列表同一份 WHERE）。
 */

import { useState } from 'react'
import { Alert, Button, Form, Input, Modal, Select, Space, Table, Typography, App as AntApp } from 'antd'

import { recordApi } from '@/api'
import type { BulkReplaceResult, Field } from '@/api'

/** 可参与查找替换的字段类型（与后端 `bulk_replace` 的允许集合一致） */
export const TEXT_LIKE_FIELD_TYPES = ['text', 'email', 'url', 'phone'] as const

/** 匹配模式（与后端 `MATCH_MODES` 对齐） */
export const MATCH_OPTIONS = [
  { value: 'contains', label: '包含（子串）' },
  { value: 'exact', label: '整值相等' },
  { value: 'regex', label: '正则表达式' },
] as const

type MatchMode = (typeof MATCH_OPTIONS)[number]['value']

interface Props {
  open: boolean
  wid: number | string
  tid: number | string
  fields: Field[]
  /** 当前视图筛选（与列表同源），预览与替换都限定在这个范围 */
  filters?: Array<Record<string, unknown>>
  filterLogic?: 'AND' | 'OR'
  onClose: () => void
  onApplied?: (result: BulkReplaceResult) => void
}

export default function BulkReplaceDialog({ open, wid, tid, fields, filters, filterLogic, onClose, onApplied }: Props) {
  const { message } = AntApp.useApp()
  const [fieldName, setFieldName] = useState<string | undefined>(undefined)
  const [find, setFind] = useState('')
  const [replace, setReplace] = useState('')
  const [match, setMatch] = useState<MatchMode>('contains')
  const [preview, setPreview] = useState<BulkReplaceResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [applying, setApplying] = useState(false)

  const candidates = fields.filter(
    f => !f.trashed && (TEXT_LIKE_FIELD_TYPES as readonly string[]).includes(f.field_type),
  )

  const reset = () => {
    setFieldName(undefined)
    setFind('')
    setReplace('')
    setMatch('contains')
    setPreview(null)
  }

  const close = () => {
    reset()
    onClose()
  }

  const run = async (dryRun: boolean) => {
    if (!fieldName) {
      message.warning('请先选择字段')
      return
    }
    if (!find) {
      message.warning('请填写要查找的内容')
      return
    }
    const payload = {
      field: fieldName,
      find,
      replace,
      match,
      filters: filters?.length ? filters : undefined,
      filter_logic: filterLogic,
      dry_run: dryRun,
    }
    if (dryRun) setLoading(true)
    else setApplying(true)
    try {
      const result = await recordApi.bulkReplace(wid, tid, payload)
      setPreview(result)
      if (!dryRun) {
        message.success(`已替换 ${result.updated} 行${result.skipped ? `，跳过 ${result.skipped} 行` : ''}`)
        onApplied?.(result)
        close()
      }
    } catch (err) {
      message.error(err instanceof Error ? err.message : '批量替换失败')
    } finally {
      setLoading(false)
      setApplying(false)
    }
  }

  return (
    <Modal
      open={open}
      title="批量查找替换"
      onCancel={close}
      afterClose={reset}
      width={720}
      data-testid="bulk-replace-dialog"
      footer={
        <Space>
          <Typography.Text type="secondary" style={{ fontSize: 'var(--cn-text-xs)', marginRight: 8 }}>
            只作用于当前视图筛选范围内的文本字段
          </Typography.Text>
          <Button onClick={close}>取消</Button>
          <Button data-testid="bulk-replace-preview-btn" loading={loading} onClick={() => void run(true)}>
            预览
          </Button>
          <Button
            type="primary"
            danger
            data-testid="bulk-replace-apply-btn"
            loading={applying}
            disabled={!preview || preview.matched === 0}
            onClick={() => void run(false)}
          >
            确认替换
          </Button>
        </Space>
      }
    >
      <Form layout="vertical" size="small">
        <Form.Item label="字段" required>
          <Select
            data-testid="bulk-replace-field"
            placeholder="选择要替换的文本字段"
            value={fieldName}
            onChange={(value) => {
              setFieldName(value)
              setPreview(null)
            }}
            options={candidates.map(f => ({ value: f.name, label: f.name }))}
            showSearch
          />
        </Form.Item>
        <div style={{ display: 'flex', gap: 12 }}>
          <Form.Item label="查找" required style={{ flex: 1 }}>
            <Input
              data-testid="bulk-replace-find"
              value={find}
              onChange={e => {
                setFind(e.target.value)
                setPreview(null)
              }}
              placeholder="要查找的内容"
            />
          </Form.Item>
          <Form.Item label="替换为" style={{ flex: 1 }}>
            <Input
              data-testid="bulk-replace-with"
              value={replace}
              onChange={e => {
                setReplace(e.target.value)
                setPreview(null)
              }}
              placeholder="留空表示删除匹配内容"
            />
          </Form.Item>
          <Form.Item label="匹配方式" style={{ width: 170 }}>
            <Select
              data-testid="bulk-replace-match"
              value={match}
              onChange={(value) => {
                setMatch(value)
                setPreview(null)
              }}
              options={[...MATCH_OPTIONS]}
            />
          </Form.Item>
        </div>
      </Form>

      {preview && (
        <div data-testid="bulk-replace-preview">
          <Alert
            type={preview.matched ? 'info' : 'warning'}
            showIcon
            style={{ marginBottom: 8 }}
            title={
              preview.matched
                ? `将替换 ${preview.matched} 行${preview.skipped ? `（其中 ${preview.skipped} 行因字段规则被跳过）` : ''}`
                : '没有匹配到可替换的内容'
            }
          />
          {preview.preview.length > 0 && (
            <Table
              size="small"
              rowKey="row_id"
              pagination={false}
              dataSource={preview.preview}
              columns={[
                { title: '行', dataIndex: 'row_id', width: 80, render: (v: number) => `#${v}` },
                { title: '替换前', dataIndex: 'old', ellipsis: true },
                { title: '替换后', dataIndex: 'new', ellipsis: true },
              ]}
            />
          )}
        </div>
      )}
    </Modal>
  )
}
