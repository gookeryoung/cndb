/** Grid 单元格组件 — 支持 inline 编辑. */

import React, { useCallback, useEffect, useRef, useState } from 'react'
import { Tag, Tooltip, Typography, Input, InputNumber, Select, Checkbox, DatePicker, Button, Popover, message, Upload, Image } from 'antd'
import { SaveOutlined, CloseOutlined, InboxOutlined, DeleteOutlined } from '@ant-design/icons'
import dayjs, { Dayjs } from 'dayjs'
import { useQuery } from '@tanstack/react-query'
import type { AttachmentFile, Field, RowResponse } from '@/api'
import { recordApi, fileApi } from '@/api'
import { getTagColorName, resolveTagColor } from '@/utils/tagColors'

interface Props {
  value: unknown
  field: Field
  rowId: number | string
  wid?: number | string
  /** 传统按单元格编辑：双击进入编辑态，回车/失焦调用该回调保存单个字段 */
  onSave?: (fieldName: string, value: unknown) => Promise<unknown>
  /** 受控编辑模式：为 true 时强制渲染编辑态，value 作为受控草稿值，供"行内新增/整行编辑"复用 */
  editing?: boolean
  /** 受控模式下草稿变化回调 */
  onDraftChange?: (value: unknown) => void
  /** 受控模式下回车确认（行级编辑时通常为 noop，父级统一保存） */
  onDraftCommit?: (fieldName: string, value: unknown) => void
  /** 受控模式下取消 */
  onDraftCancel?: () => void
  /** 是否渲染单元格底部自带的"保存/取消"按钮（行级编辑时由行操作列统一承载，置 false） */
  showActionButtons?: boolean
}

/**
 * 可编辑单元格。
 * - 传统模式（无 editing prop）：双击切到编辑态，回车/失焦通过 onSave 保存单个字段。
 * - 受控模式（editing 为布尔值）：由父级把控编辑态与草稿值，value 即当前草稿。
 */
export default function GridCell({ value, field, rowId, wid, onSave, editing: controlledEditing, onDraftChange, onDraftCommit, onDraftCancel, showActionButtons }: Props) {
  // 说明：prop `editing`（受控模式）与内部 state `editing`（传统模式）同名，
  // 这里在解构时把 prop 重命名为 `controlledEditing`，内部 state 沿用 `editing` 变量名（传统模式）。
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState<unknown>(value)
  const [saving, setSaving] = useState(false)
  const inputRef = useRef<HTMLElement | null>(null)

  // 受控模式：编辑态与草稿值完全交由父级
  const controlled = typeof controlledEditing === 'boolean'
  // 受控模式下编辑态由 prop 决定，否则用内部 state
  const isEditing = controlled ? controlledEditing : editing

  // 外部 value 变化时同步 draft（仅传统模式用）
  useEffect(() => {
    if (!controlled) setDraft(value)
  }, [value, controlled])

  // 切到编辑态时自动聚焦。受控模式（行级新增/整行编辑）由父级统一聚焦第一个可编辑单元格，
  // 避免一行内多个 GridCell 同时进入编辑态时互相争抢焦点。
  useEffect(() => {
    if (controlled) return
    if (isEditing && inputRef.current) {
      const el = inputRef.current
      if ('focus' in el && typeof (el as HTMLElement).focus === 'function') {
        setTimeout(() => (el as HTMLElement).focus(), 30)
      }
    }
  }, [isEditing, controlled])

  const handleStartEdit = useCallback(() => {
    // 受控模式由父级把控首个焦点，无需在此处理
    if (controlled) return
    if (isReadonlyField(field)) return
    setDraft(normalizeValueForEdit(value, field))
    setEditing(true)
  }, [controlled, value, field])

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
    return <DisplayCell value={value} field={field} rowId={rowId} wid={wid} />
  }

  // 受控模式：编辑态与草稿值由父级决定
  if (controlled) {
    // 草稿值即 value（父级传入的当前值）；回车提交走 onDraftCommit（行级保存统一由父级处理）
    return (
      <EditCell
        field={field}
        draft={value}
        onChange={onDraftChange ?? (() => {})}
        inputRef={inputRef}
        onSave={() => onDraftCommit?.(field.name, finalizeValueFromEdit(value, field))}
        onCancel={() => onDraftCancel?.()}
        saving={false}
        wid={wid}
        showActions={!!showActionButtons}
        enableAutoFocus={false}
      />
    )
  }

  if (!editing) {
    return (
      <div
        onDoubleClick={handleStartEdit}
        style={{ padding: '2px 4px', cursor: onSave ? 'pointer' : 'default', minHeight: 22 }}
        title={onSave ? '双击编辑' : undefined}
      >
        <DisplayCell value={value} field={field} rowId={rowId} wid={wid} />
      </div>
    )
  }

  return (
    <EditCell
      field={field}
      draft={isEditing ? draft : value}
      onChange={setDraft}
      inputRef={inputRef}
      onSave={handleSave}
      onCancel={handleCancel}
      saving={saving}
      wid={wid}
    />
  )
}

// ─────────────── 展示态 ───────────────

/** 自动配色 Tag — 直接用 antd 预设色名 */
function ColoredTag({ value }: { value: string }) {
  return <Tag color={getTagColorName(value)}>{value}</Tag>
}

function DisplayCell({ value, field, rowId, wid }: { value: unknown; field: Field; rowId: number | string; wid?: number | string }) {
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
    case 'float': {
      // 小数位数根据 config 决定，默认保留全部
      const cfg = (field.config as Record<string, unknown> | undefined) || {}
      const decimals = cfg.decimals as number | undefined
      const num = Number(value)
      if (!Number.isNaN(num) && decimals !== undefined) {
        return <span className="font-num">{num.toFixed(decimals)}</span>
      }
      return <span className="font-num">{String(value)}</span>
    }
    case 'percentage': {
      const num = Number(value)
      if (!Number.isNaN(num)) {
        const cfg = (field.config as Record<string, unknown> | undefined) || {}
        const decimals = (cfg.decimals as number | undefined) ?? 0
        return <span className="font-num">{(num * 100).toFixed(decimals)}%</span>
      }
      return <span>{String(value)}</span>
    }
    case 'date':
      return <span>{dayjs(String(value)).format('YYYY-MM-DD')}</span>
    case 'datetime':
      return <span>{dayjs(String(value)).format('YYYY-MM-DD HH:mm')}</span>
    case 'timestamp': {
      const n = Number(value)
      if (!Number.isNaN(n) && n > 0) {
        return <span>{dayjs.unix(n).format('YYYY-MM-DD HH:mm:ss')}</span>
      }
      return <span>{String(value)}</span>
    }
    case 'select': {
      const options = field.config?.options
      const v = String(value)
      const color = resolveTagColor(v, options)
      return <Tag color={color}>{v}</Tag>
    }
    case 'multi_select':
    case 'multiselect': {
      const options = field.config?.options
      const arr = Array.isArray(value) ? value as unknown[] : String(value).split(',').map(s => s.trim()).filter(Boolean)
      return <>{arr.map((v, i) => {
        const sv = String(v)
        return <Tag key={i} color={resolveTagColor(sv, options, i)}>{sv}</Tag>
      })}</>
    }
    case 'email':
      return <Typography.Link href={`mailto:${value}`}>{String(value)}</Typography.Link>
    case 'url':
      return <Typography.Link href={String(value)} target="_blank" rel="noreferrer">{String(value)}</Typography.Link>
    case 'link': {
      if (Array.isArray(value)) {
        return <span>{value.map((v: Record<string, unknown>, i: number) => <ColoredTag key={i} value={String(v?.value ?? v?.id ?? v)} />)}</span>
      }
      if (value && typeof value === 'object') {
        const o = value as Record<string, unknown>
        return <Tooltip title={`row ${o.id ?? rowId}`}><ColoredTag value={String(o.value ?? o.id ?? value)} /></Tooltip>
      }
      return <ColoredTag value={String(value)} />
    }
    case 'attachment': {
      // 值可能是 JSON 字符串或已经解析好的数组
      let files: AttachmentFile[] = []
      try {
        files = Array.isArray(value) ? (value as AttachmentFile[]) : JSON.parse(String(value || '[]'))
      } catch { files = [] }
      if (!files.length) return <span style={{ color: '#cbd5e1' }}>—</span>
      return (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
          {files.map(f => {
            const isImg = (f.mime_type || f.filename).match(/image\/|\.(png|jpe?g|gif|webp|svg)$/i)
            if (isImg && wid) {
              return (
                <Image key={f.file_key} width={48} height={48}
                  src={fileApi.getUrl(wid, f.file_key, true)}
                  alt={f.filename} style={{ objectFit: 'cover', borderRadius: 4 }} />
              )
            }
            return (
              <Typography.Link key={f.file_key}
                href={wid ? fileApi.getUrl(wid, f.file_key) : undefined}
                target="_blank" rel="noreferrer"
                style={{ fontSize: 12 }}>
                📎 {f.filename}
              </Typography.Link>
            )
          })}
        </div>
      )
    }
    case 'long_text':
    case 'longtext': {
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
  wid?: number | string
  /** 是否渲染单元格自带的"保存/取消"按钮，行级编辑时由行操作列承载，置 false */
  showActions?: boolean
  /** 是否允许控件内部自动聚焦（行级新增/整行编辑时由父级统一聚焦，置 false） */
  enableAutoFocus?: boolean
}

function EditCell({ field, draft, onChange, inputRef, onSave, onCancel, saving, wid, showActions = true, enableAutoFocus = true }: EditCellProps) {
  const ft = field.field_type
  const wrap: React.CSSProperties = {
    display: 'flex', gap: 4, alignItems: 'center', padding: '2px 0',
  }
  const actions = showActions ? (
    <span style={{ display: 'inline-flex', gap: 2 }}>
      <Button size="small" type="primary" icon={<SaveOutlined />} onClick={onSave} loading={saving} />
      <Button size="small" icon={<CloseOutlined />} onClick={onCancel} />
    </span>
  ) : null

  const commonOnKey = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); onSave() }
    if (e.key === 'Escape') { e.preventDefault(); onCancel() }
  }

  // link 字段用的 query —— 必须在组件顶层调用，enabled 控制非 link 类型时不执行
  const targetTableId = (field.config?.target_table_id as number | undefined)
  const multiple = Boolean(field.config?.multiple ?? true)
  const { data: targetRowsData, isLoading: linkLoading } = useQuery({
    queryKey: ['link-target-rows', targetTableId],
    queryFn: () => recordApi.list(wid!, targetTableId!, { limit: 500 }),
    enabled: !!wid && !!targetTableId,
  })
  const targetRows: RowResponse[] = (targetRowsData as any)?.items || []

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
    case 'long_text':
    case 'longtext': {
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
    case 'decimal':
    case 'float':
    case 'percentage': {
      return (
        <div style={wrap}>
          <InputNumber
            size="small"
            value={draft as number | null}
            onChange={v => onChange(v)}
            onKeyDown={commonOnKey}
            ref={el => { if (el) inputRef.current = el as unknown as HTMLElement }}
            style={{ flex: 1, width: '100%' }}
            step={ft === 'decimal' || ft === 'float' || ft === 'percentage' ? 0.01 : 1}
          />
          {actions}
        </div>
      )
    }
    case 'timestamp': {
      return (
        <div style={wrap}>
          <InputNumber
            size="small"
            value={draft as number | null}
            onChange={v => onChange(v)}
            onKeyDown={commonOnKey}
            ref={el => { if (el) inputRef.current = el as unknown as HTMLElement }}
            style={{ flex: 1, width: '100%' }}
            step={1}
            placeholder="Unix 时间戳（秒）"
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
      const options = ((field.config?.options as string[] | Array<{ label: string; value: string }>) || []).map(o => {
        if (typeof o === 'string') return { value: o, label: o }
        return { value: String(o.value ?? o.label), label: String(o.label ?? o.value) }
      })
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
            autoFocus={enableAutoFocus}
            popupMatchSelectWidth={false}
          />
          {actions}
        </div>
      )
    }
    case 'multi_select':
    case 'multiselect': {
      const options = ((field.config?.options as string[] | Array<{ label: string; value: string }>) || []).map(o => {
        if (typeof o === 'string') return { value: o, label: o }
        return { value: String(o.value ?? o.label), label: String(o.label ?? o.value) }
      })
      return (
        <div style={wrap}>
          <Select
            size="small"
            mode="multiple"
            value={(draft as string[]) || []}
            onChange={v => onChange(v)}
            options={options}
            style={{ flex: 1 }}
            autoFocus={enableAutoFocus}
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
    case 'link': {
      // link 字段：从 field.config.target_table_id 拉目标表行，用 Select 选择
      // （query 已移到组件顶层调用）

      // 从 draft（可能是 [{id, value}] 或 id 数组）提取纯 id 数组给 Select
      const ids = extractLinkIds(draft)

      const options = targetRows.map((r: any) => ({
        value: r.id,
        label: extractRowLabel(r),
      }))

      return (
        <div style={wrap}>
          <Select
            size="small"
            mode={multiple ? 'multiple' : undefined}
            value={ids as any}
            onChange={(v) => onChange(Array.isArray(v) ? v : v !== undefined && v !== null ? [v] : [])}
            options={options}
            placeholder={linkLoading ? '加载中...' : (targetTableId ? '选择关联行' : '未配置目标表')}
            loading={linkLoading}
            style={{ flex: 1 }}
            allowClear
            showSearch
            optionFilterProp="label"
            disabled={!targetTableId}
          />
          {actions}
        </div>
      )
    }
    case 'attachment': {
      const files: AttachmentFile[] = Array.isArray(draft)
        ? (draft as AttachmentFile[])
        : (() => {
          try { return JSON.parse(String(draft || '[]')) } catch { return [] }
        })()

      const upload = async (file: File): Promise<AttachmentFile> => {
        if (!wid) throw new Error('缺少 wid')
        const meta = await fileApi.upload(wid, file)
        onChange([...files, meta])
        return meta
      }
      const removeAt = (idx: number) => {
        const removed = files[idx]
        // 尝试硬清理物理文件（忽略错误）
        if (wid && removed?.file_key) {
          fileApi.remove(wid, removed.file_key).catch(() => { /* 行值更新后再清理会有竞争，静默 */ })
        }
        const next = files.filter((_, i) => i !== idx)
        onChange(next)
      }

      return (
        <div style={{ ...wrap, flexDirection: 'column', alignItems: 'stretch' }}>
          <Upload.Dragger
            multiple={Boolean(field.config?.multiple ?? true)}
            showUploadList={false}
            accept={(field.config?.allowed_mime_types as string[])?.join(',') || undefined}
            beforeUpload={f => { upload(f); return false }}
            style={{ padding: '4px 8px', marginBottom: 4 }}
          >
            <div style={{ fontSize: 12, color: '#94a3b8', margin: '2px 0' }}>
              <InboxOutlined /> 点击或拖拽上传
            </div>
          </Upload.Dragger>
          {files.length > 0 && (
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
              {files.map((f, i) => (
                <span key={f.file_key} style={{ fontSize: 12, padding: '2px 6px', border: '1px solid #e2e8f0', borderRadius: 4 }}>
                  📎 {f.filename}
                  <Button type="text" size="small" danger icon={<DeleteOutlined />}
                    onClick={() => removeAt(i)} style={{ marginLeft: 2 }} />
                </span>
              ))}
            </div>
          )}
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
    if (['number', 'decimal', 'float', 'percentage', 'timestamp'].includes(field.field_type)) return null
    if (['multi_select', 'multiselect'].includes(field.field_type)) return []
    if (field.field_type === 'link') return []  // link 从 [{id, value}] 转为空数组，由 ExtractLinkIds 在 EditCell 内部处理
    if (field.field_type === 'attachment') return []
    return ''
  }
  if (field.field_type === 'link') {
    // API 返回 [{id, value}]，编辑器消费纯 id 数组
    return extractLinkIds(value)
  }
  if (field.field_type === 'attachment') {
    // 后端存 JSON 字符串，前端编辑器消费 AttachmentFile[]
    if (Array.isArray(value)) return value
    try { return JSON.parse(String(value || '[]')) } catch { return [] }
  }
  if (field.field_type === 'date' || field.field_type === 'datetime') {
    return value
  }
  return value
}

/** 从 link 字段 API 返回值中提取纯 id 数组. */
function extractLinkIds(value: unknown): number[] {
  if (value === null || value === undefined) return []
  if (Array.isArray(value)) {
    return value.map((item: any) => {
      if (typeof item === 'number') return item
      if (item && typeof item === 'object') return item.id
      return Number(item)
    }).filter((n: number) => !Number.isNaN(n) && n > 0)
  }
  if (typeof value === 'number') return [value]
  return []
}

/** 从目标行数据中提取可读的标签文本用于 Select 选项. */
function extractRowLabel(r: RowResponse | Record<string, unknown>): string {
  // 优先用 text 字段，否则用 id
  const text = String(r.id ?? '')
  return text ? `#${text}` : '行'
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
    case 'decimal':
    case 'float':
    case 'percentage':
    case 'timestamp': {
      const n = typeof draft === 'number' ? draft : Number(String(draft).trim())
      return Number.isNaN(n) ? null : n
    }
    case 'multi_select':
    case 'multiselect': {
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

/**
 * 导出的字段值归一化：把编辑器草稿值转成后端接受的格式。
 * 供 GridPage 行内新增/整行编辑在保存时统一复用。
 */
export function finalizeCellValue(draft: unknown, field: Field): unknown {
  return finalizeValueFromEdit(draft, field)
}

/**
 * 导出的字段值归一化（编辑态）：把后端值转成编辑器可消费的草稿。
 * 供 GridPage 行内新增/整行编辑初始化草稿时复用（与单元格双击编辑的转换保持一致）。
 */
export function normalizeCellValueForEdit(value: unknown, field: Field): unknown {
  return normalizeValueForEdit(value, field)
}

/**
 * 判断草稿是否为空（不参与提交）。
 * 空串 / null / undefined / 空数组 视为空。
 */
export function isBlankCellValue(v: unknown): boolean {
  if (v === null || v === undefined || v === '') return true
  if (Array.isArray(v)) return v.length === 0
  return false
}

/**
 * 该字段是否在行内编辑中可编辑（与展示/单元格双击判定一致）。
 */
export function isEditableInlineField(field: Field): boolean {
  return !isReadonlyField(field) && !field.trashed
}
