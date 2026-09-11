/** Grid 单元格组件 — 支持 inline 编辑. */

import React, { useCallback, useEffect, useRef, useState } from 'react'
import { Tag, Tooltip, Typography, Input, InputNumber, Select, Checkbox, DatePicker, Button, Popover, message } from 'antd'
import { SaveOutlined, CloseOutlined } from '@ant-design/icons'
import dayjs, { Dayjs } from 'dayjs'
import type { Field } from '@/api'

interface Props {
  value: unknown
  field: Field
  rowId: number | string
  onSave?: (fieldName: string, value: unknown) => Promise<unknown>
}

/** 可编辑单元格：默认展示态，双击切到编辑态，回车/失焦保存 */
export default function GridCell({ value, field, rowId, onSave }: Props) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState<unknown>(value)
  const [saving, setSaving] = useState(false)
  const inputRef = useRef<HTMLElement | null>(null)

  // 外部 value 变化时同步 draft
  useEffect(() => {
    setDraft(value)
  }, [value])

  // 切到编辑态时自动聚焦
  useEffect(() => {
    if (editing && inputRef.current) {
      const el = inputRef.current
      if ('focus' in el && typeof (el as HTMLElement).focus === 'function') {
        setTimeout(() => (el as HTMLElement).focus(), 30)
      }
    }
  }, [editing])

  const handleStartEdit = useCallback(() => {
    if (isReadonlyField(field)) return
    setDraft(normalizeValueForEdit(value, field))
    setEditing(true)
  }, [value, field])

  const handleSave = useCallback(async () => {
    if (!onSave) { setEditing(false); return }
    setSaving(true)
    try {
      const finalize = finalizeValueFromEdit(draft, field)
      await onSave(field.name, finalize)
      setEditing(false)
      message.success('已保存')
    } catch (err) {
      message.error(err instanceof Error ? err.message : '保存失败')
    } finally {
      setSaving(false)
    }
  }, [draft, field, onSave])

  const handleCancel = useCallback(() => {
    setDraft(value)
    setEditing(false)
  }, [value])

  // 只读字段直接展示
  if (isReadonlyField(field)) {
    return <DisplayCell value={value} field={field} rowId={rowId} />
  }

  if (!editing) {
    return (
      <div
        onDoubleClick={handleStartEdit}
        style={{ padding: '2px 4px', cursor: onSave ? 'pointer' : 'default', minHeight: 22 }}
        title={onSave ? '双击编辑' : undefined}
      >
        <DisplayCell value={value} field={field} rowId={rowId} />
      </div>
    )
  }

  return (
    <EditCell
      field={field}
      draft={draft}
      onChange={setDraft}
      inputRef={inputRef}
      onSave={handleSave}
      onCancel={handleCancel}
      saving={saving}
    />
  )
}

// ─────────────── 展示态 ───────────────

function DisplayCell({ value, field, rowId }: { value: unknown; field: Field; rowId: number | string }) {
  if (value === null || value === undefined || value === '') {
    return <span style={{ color: '#cbd5e1' }}>—</span>
  }
  const ft = field.field_type
  switch (ft) {
    case 'boolean': {
      const v = Boolean(value)
      return <Tag color={v ? 'green' : 'default'}>{v ? '是' : '否'}</Tag>
    }
    case 'number':
    case 'decimal':
      return <span style={{ fontFamily: 'ui-monospace, monospace' }}>{String(value)}</span>
    case 'date':
      return <span>{dayjs(String(value)).format('YYYY-MM-DD')}</span>
    case 'datetime':
      return <span>{dayjs(String(value)).format('YYYY-MM-DD HH:mm')}</span>
    case 'select':
      return <Tag color="blue">{String(value)}</Tag>
    case 'multi_select': {
      const arr = Array.isArray(value) ? value as unknown[] : String(value).split(',').map(s => s.trim()).filter(Boolean)
      return <>{arr.map((v, i) => <Tag key={i}>{String(v)}</Tag>)}</>
    }
    case 'email':
      return <Typography.Link href={`mailto:${value}`}>{String(value)}</Typography.Link>
    case 'url':
      return <Typography.Link href={String(value)} target="_blank" rel="noreferrer">{String(value)}</Typography.Link>
    case 'link': {
      if (Array.isArray(value)) {
        return <span>{value.map((v: Record<string, unknown>, i: number) => <Tag key={i}>{String(v?.value ?? v?.id ?? v)}</Tag>)}</span>
      }
      if (value && typeof value === 'object') {
        const o = value as Record<string, unknown>
        return <Tooltip title={`row ${o.id ?? rowId}`}><Tag>{String(o.value ?? o.id ?? value)}</Tag></Tooltip>
      }
      return <Tag>{String(value)}</Tag>
    }
    case 'attachment':
      return <span>📎 {String(value)}</span>
    case 'long_text': {
      const s = String(value)
      return <Tooltip title={s}><span>{s.length > 40 ? s.slice(0, 40) + '…' : s}</span></Tooltip>
    }
    case 'phone':
      return <span>{String(value)}</span>
    default:
      return <span>{String(value)}</span>
  }
}

// ─────────────── 编辑态 ───────────────

interface EditCellProps {
  field: Field
  draft: unknown
  onChange: (v: unknown) => void
  inputRef: React.MutableRefObject<HTMLElement | null>
  onSave: () => void
  onCancel: () => void
  saving: boolean
}

function EditCell({ field, draft, onChange, inputRef, onSave, onCancel, saving }: EditCellProps) {
  const ft = field.field_type
  const wrap: React.CSSProperties = {
    display: 'flex', gap: 4, alignItems: 'center', padding: '2px 0',
  }
  const actions = (
    <span style={{ display: 'inline-flex', gap: 2 }}>
      <Button size="small" type="primary" icon={<SaveOutlined />} onClick={onSave} loading={saving} />
      <Button size="small" icon={<CloseOutlined />} onClick={onCancel} />
    </span>
  )

  const commonOnKey = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); onSave() }
    if (e.key === 'Escape') { e.preventDefault(); onCancel() }
  }

  switch (ft) {
    case 'text':
    case 'email':
    case 'url':
    case 'phone': {
      return (
        <div style={wrap}>
          <Input
            size="small"
            value={String(draft ?? '')}
            onChange={e => onChange(e.target.value)}
            onKeyDown={commonOnKey}
            ref={el => { if (el) inputRef.current = el.input }}
            style={{ flex: 1 }}
          />
          {actions}
        </div>
      )
    }
    case 'long_text': {
      return (
        <Popover
          content={(
            <Input.TextArea
              value={String(draft ?? '')}
              onChange={e => onChange(e.target.value)}
              rows={4}
              autoSize={{ minRows: 2, maxRows: 6 }}
              onKeyDown={commonOnKey}
              ref={el => { if (el) inputRef.current = el.resizableTextArea?.textArea ?? null }}
            />
          )}
          title="多行文本"
          open
          trigger="click"
          onOpenChange={(open) => { if (!open) onSave() }}
        >
          <div style={wrap}>
            <span style={{ flex: 1, border: '1px dashed #91caff', padding: '1px 4px', borderRadius: 4, minHeight: 22 }}>{String(draft ?? '') || '点击编辑...'}</span>
            {actions}
          </div>
        </Popover>
      )
    }
    case 'number':
    case 'decimal': {
      return (
        <div style={wrap}>
          <InputNumber
            size="small"
            value={draft as number | null}
            onChange={v => onChange(v)}
            onKeyDown={commonOnKey}
            ref={el => { if (el) inputRef.current = el as unknown as HTMLElement }}
            style={{ flex: 1, width: '100%' }}
            step={ft === 'decimal' ? 0.01 : 1}
          />
          {actions}
        </div>
      )
    }
    case 'boolean': {
      return (
        <div style={wrap}>
          <Checkbox
            checked={Boolean(draft)}
            onChange={e => onChange(e.target.checked)}
            ref={el => { if (el) inputRef.current = el as unknown as HTMLElement }}
          />
          {actions}
        </div>
      )
    }
    case 'select': {
      const options = ((field.config?.options as string[]) || []).map(o => ({ value: o, label: o }))
      const merged = options.length ? options : [{ value: String(draft ?? ''), label: String(draft ?? '') }]
      return (
        <div style={wrap}>
          <Select
            size="small"
            value={draft ?? undefined}
            onChange={v => onChange(v)}
            options={merged}
            onKeyDown={commonOnKey}
            style={{ flex: 1 }}
            autoFocus
            popupMatchSelectWidth={false}
          />
          {actions}
        </div>
      )
    }
    case 'multi_select': {
      const options = ((field.config?.options as string[]) || []).map(o => ({ value: o, label: o }))
      return (
        <div style={wrap}>
          <Select
            size="small"
            mode="multiple"
            value={(draft as string[]) || []}
            onChange={v => onChange(v)}
            options={options}
            style={{ flex: 1 }}
            autoFocus
            popupMatchSelectWidth={false}
          />
          {actions}
        </div>
      )
    }
    case 'date': {
      return (
        <div style={wrap}>
          <DatePicker
            size="small"
            value={draft ? dayjs(String(draft)) : null}
            onChange={(_d, dateStr) => onChange(dateStr)}
            ref={el => { if (el) inputRef.current = el as unknown as HTMLElement }}
            style={{ flex: 1 }}
          />
          {actions}
        </div>
      )
    }
    case 'datetime': {
      return (
        <div style={wrap}>
          <DatePicker
            size="small"
            showTime
            value={draft ? dayjs(String(draft)) : null}
            onChange={(_d, dateStr) => onChange(dateStr)}
            ref={el => { if (el) inputRef.current = el as unknown as HTMLElement }}
            style={{ flex: 1 }}
          />
          {actions}
        </div>
      )
    }
    case 'link':
    case 'attachment': {
      // link/attachment inline 编辑暂用纯文本输入（value 存的是 [{id,value}] JSON 或原始值）
      return (
        <div style={wrap}>
          <Input
            size="small"
            value={typeof draft === 'object' ? JSON.stringify(draft) : String(draft ?? '')}
            onChange={e => onChange(e.target.value)}
            placeholder={ft === 'link' ? 'JSON: [{id,value}]' : '附件 URL'}
            onKeyDown={commonOnKey}
            style={{ flex: 1 }}
          />
          {actions}
        </div>
      )
    }
    default: {
      return (
        <div style={wrap}>
          <span style={{ color: '#999' }}>类型 {ft} 暂不支持 inline 编辑</span>
          {actions}
        </div>
      )
    }
  }
}

// ─────────────── 辅助函数 ───────────────

/** 只读字段（系统自动维护的字段）不能 inline 编辑 */
function isReadonlyField(field: Field): boolean {
  const readonly = new Set(['auto_id', 'created_time', 'updated_time', 'created_by', 'updated_by', 'formula'])
  return readonly.has(field.field_type) || Boolean(field.is_primary && field.field_type === 'auto_id')
}

/** 进入编辑态前：把后端值转换成编辑器能吃的 JS 值 */
function normalizeValueForEdit(value: unknown, field: Field): unknown {
  if (value === null || value === undefined) {
    if (field.field_type === 'boolean') return false
    if (field.field_type === 'number' || field.field_type === 'decimal') return null
    if (field.field_type === 'multi_select') return []
    return ''
  }
  if (field.field_type === 'date' || field.field_type === 'datetime') {
    // 后端返回 "2023-01-15"，DatePicker 需要 Dayjs，但 onChange 给 dateStr
    return value  // 在 EditCell 内部再 wrap
  }
  return value
}

/** 离开编辑态保存前：把编辑器的草稿值转换成后端 schema 需要的格式 */
function finalizeValueFromEdit(draft: unknown, field: Field): unknown {
  const ft = field.field_type
  if (draft === '' || draft === null || draft === undefined) {
    // 空值统一 null 让后端处理
    if (field.required) return null
    return null
  }
  switch (ft) {
    case 'number':
    case 'decimal': {
      const n = typeof draft === 'number' ? draft : Number(String(draft).trim())
      return Number.isNaN(n) ? null : n
    }
    case 'multi_select': {
      return Array.isArray(draft) ? draft : []
    }
    case 'date':
    case 'datetime': {
      // 编辑器给的是 dateStr 或 Dayjs
      if (typeof draft === 'string') return draft
      if (dayjs.isDayjs(draft as Dayjs)) return (draft as Dayjs).format(ft === 'date' ? 'YYYY-MM-DD' : 'YYYY-MM-DD HH:mm:ss')
      return draft
    }
    case 'boolean':
      return Boolean(draft)
    case 'link': {
      // 如果用户直接粘了 JSON 尝试 parse
      if (typeof draft === 'string') {
        try { return JSON.parse(draft) } catch { return draft }
      }
      return draft
    }
    default:
      return draft
  }
}
