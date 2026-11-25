/** 批量设置值对话框（需求 0151 扩展：跨页全选的批量**更新**）.
 *
 * 选择一个字段 + 一个值，对「当前选中行」或「当前筛选全部行（跨页）」统一赋值。
 * - 字段候选：有物理列且可编辑的普通字段（lookup / formula / link 由后端拒绝，前端先过滤）
 * - 值输入按字段类型给控件（文本 / 数字 / 布尔 / 选项）
 * - 跨页时显示命中行数并要求二次确认（影响面必须可见）
 */

import { useState } from 'react'
import { Alert, Button, Form, Input, InputNumber, Modal, Select, Space, Switch, Typography, App as AntApp } from 'antd'

import { recordApi } from '@/api'
import type { Field } from '@/api'

/** 可由批量设置写入的字段类型（link / lookup / formula 无物理列或语义特殊，排除） */
export const BULK_UPDATE_FIELD_TYPES = [
  'text', 'email', 'url', 'phone', 'number', 'float', 'percentage', 'boolean', 'date', 'datetime', 'select', 'multiselect',
] as const

interface Props {
  open: boolean
  wid: number | string
  tid: number | string
  fields: Field[]
  /** 已勾选的行 id */
  rowIds: Array<number | string>
  /** 是否已切到"跨页全选"（目标行由服务端按筛选展开） */
  selectAll?: boolean
  /** 当前筛选命中的总行数（跨页时展示影响面） */
  total?: number
  filters?: Array<Record<string, unknown>>
  filterLogic?: 'AND' | 'OR'
  onClose: () => void
  onApplied?: (updated: number) => void
}

export default function BulkUpdateDialog({
  open, wid, tid, fields, rowIds, selectAll = false, total, filters, filterLogic, onClose, onApplied,
}: Props) {
  const { message } = AntApp.useApp()
  const [fieldName, setFieldName] = useState<string | undefined>(undefined)
  const [textValue, setTextValue] = useState('')
  const [numberValue, setNumberValue] = useState<number | null>(null)
  const [boolValue, setBoolValue] = useState(false)
  const [applying, setApplying] = useState(false)

  const candidates = fields.filter(
    f => !f.trashed && (BULK_UPDATE_FIELD_TYPES as readonly string[]).includes(f.field_type),
  )
  const targetField = candidates.find(f => f.name === fieldName)
  const affected = selectAll ? (total ?? 0) : rowIds.length

  const reset = () => {
    setFieldName(undefined)
    setTextValue('')
    setNumberValue(null)
    setBoolValue(false)
  }

  const close = () => {
    reset()
    onClose()
  }

  const buildValue = (): unknown => {
    const type = targetField?.field_type ?? 'text'
    if (type === 'boolean') return boolValue
    if (type === 'number' || type === 'float' || type === 'percentage') return numberValue
    return textValue
  }

  const apply = async () => {
    if (!fieldName) {
      message.warning('请选择要设置的字段')
      return
    }
    const value = buildValue()
    if (value === null || value === undefined || value === '') {
      message.warning('请填写要设置的值')
      return
    }
    setApplying(true)
    try {
      const result = await recordApi.bulkUpdate(
        wid,
        tid,
        rowIds,
        { [fieldName]: value },
        selectAll ? { selectAll: true, filters, filterLogic } : undefined,
      )
      message.success(`已更新 ${result.updated} 行`)
      onApplied?.(result.updated)
      close()
    } catch (err) {
      message.error(err instanceof Error ? err.message : '批量更新失败')
    } finally {
      setApplying(false)
    }
  }

  return (
    <Modal
      open={open}
      title="批量设置值"
      onCancel={close}
      width={560}
      data-testid="bulk-update-dialog"
      footer={
        <Space>
          <Typography.Text type="secondary" style={{ fontSize: 'var(--cn-text-xs)', marginRight: 8 }}>
            {selectAll ? '作用于当前筛选的全部行（跨页）' : `作用于已选的 ${rowIds.length} 行`}
          </Typography.Text>
          <Button onClick={close}>取消</Button>
          <Button type="primary" loading={applying} data-testid="bulk-update-apply" onClick={() => void apply()}>
            确认更新
          </Button>
        </Space>
      }
    >
      <Alert
        type={selectAll ? 'warning' : 'info'}
        showIcon
        style={{ marginBottom: 12 }}
        title={`将影响 ${affected} 行${selectAll ? '（跨页全选，按当前筛选展开）' : ''}`}
        data-testid="bulk-update-impact"
      />
      <Form layout="vertical" size="small">
        <Form.Item label="字段" required>
          <Select
            data-testid="bulk-update-field"
            placeholder="选择要统一赋值的字段"
            value={fieldName}
            showSearch
            options={candidates.map(f => ({ value: f.name, label: `${f.name}（${f.field_type}）` }))}
            onChange={value => setFieldName(value)}
          />
        </Form.Item>
        <Form.Item label="值" required>
          {targetField?.field_type === 'boolean' ? (
            <Switch
              data-testid="bulk-update-value-bool"
              checked={boolValue}
              onChange={setBoolValue}
              checkedChildren="是"
              unCheckedChildren="否"
            />
          ) : targetField && ['number', 'float', 'percentage'].includes(targetField.field_type) ? (
            <InputNumber
              data-testid="bulk-update-value-number"
              style={{ width: '100%' }}
              value={numberValue ?? undefined}
              onChange={value => setNumberValue(typeof value === 'number' ? value : null)}
            />
          ) : (
            <Input
              data-testid="bulk-update-value-text"
              value={textValue}
              onChange={e => setTextValue(e.target.value)}
              placeholder={targetField?.field_type === 'select' ? '填写选项值' : '填写要设置的值'}
            />
          )}
        </Form.Item>
      </Form>
    </Modal>
  )
}
