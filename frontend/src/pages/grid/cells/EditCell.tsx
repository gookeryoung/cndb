/** 单元格编辑态 —— 按字段类型渲染对应编辑器 + 保存/取消操作. */

import React from 'react'
import { Tooltip, Input, InputNumber, Select, Checkbox, DatePicker, Button, Popover, Upload, Image } from 'antd'
import { SaveOutlined, CloseOutlined, InboxOutlined, DeleteOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import type { AttachmentFile, Field, RowResponse } from '@/api'
import { recordApi, fileApi, fieldApi } from '@/api'
import { AuthedImage } from '@/components/AuthedFile'
import { getFieldTypeLabel } from '@/utils/fieldTypeMeta'
import { pickLinkLabelFieldName, buildLinkRowLabel } from './fieldValueFormat'
import dayjs from 'dayjs'
import { extractLinkIds } from './cellValueUtils'

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

export function EditCell({ field, draft, onChange, inputRef, onSave, onCancel, saving, wid, showActions = true, enableAutoFocus = true }: EditCellProps) {
  const ft = field.field_type
  const wrap: React.CSSProperties = {
    display: 'flex', gap: 4, alignItems: 'center', padding: '2px 0',
  }
  const actions = showActions ? (
    <span style={{ display: 'inline-flex', gap: 2 }}>
      <Tooltip title="保存（回车）">
        <Button size="small" type="primary" icon={<SaveOutlined />} onClick={onSave} loading={saving} />
      </Tooltip>
      <Tooltip title="取消编辑（Esc）">
        <Button size="small" icon={<CloseOutlined />} onClick={onCancel} />
      </Tooltip>
    </span>
  ) : null

  const commonOnKey = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); onSave() }
    if (e.key === 'Escape') { e.preventDefault(); onCancel() }
  }

  // link 字段用的 query —— 必须在组件顶层调用，enabled 控制非 link 类型时不执行
  const targetTableId = (field.config?.target_table_id as number | undefined)
  const multiple = Boolean(field.config?.multiple ?? true)
  const isLink = ft === 'link'
  const { data: targetRowsData, isLoading: linkLoading } = useQuery({
    queryKey: ['link-target-rows', targetTableId],
    queryFn: () => recordApi.list(wid!, targetTableId!, { limit: 500 }),
    enabled: isLink && !!wid && !!targetTableId,
  })
  const targetRows: RowResponse[] = (targetRowsData as any)?.items || []
  // 目标表字段列表 —— 找主字段做下拉选项标签，避免纯 #id 数字标签
  const { data: targetFields } = useQuery({
    queryKey: ['link-target-fields', targetTableId],
    queryFn: () => fieldApi.list(wid!, targetTableId!),
    enabled: isLink && !!wid && !!targetTableId,
  })
  const labelField = isLink ? pickLinkLabelFieldName(targetFields ?? []) : null

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
        label: buildLinkRowLabel(r, labelField),
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
                  <Tooltip title="删除该附件">
                    <Button type="text" size="small" danger icon={<DeleteOutlined />}
                      onClick={() => removeAt(i)} style={{ marginLeft: 2 }} />
                  </Tooltip>
                </span>
              ))}
            </div>
          )}
          {actions}
        </div>
      )
    }
    case 'image': {
      // 图片字段：上传仅收图片，展示为缩略图（点击可预览大图）
      const images: AttachmentFile[] = Array.isArray(draft)
        ? (draft as AttachmentFile[])
        : (() => {
          try { return JSON.parse(String(draft || '[]')) } catch { return [] }
        })()

      const upload = async (file: File): Promise<AttachmentFile> => {
        if (!wid) throw new Error('缺少 wid')
        const meta = await fileApi.upload(wid, file)
        onChange([...images, meta])
        return meta
      }
      const removeAt = (idx: number) => {
        const removed = images[idx]
        if (wid && removed?.file_key) {
          fileApi.remove(wid, removed.file_key).catch(() => { /* 行值更新后再清理会有竞争，静默 */ })
        }
        onChange(images.filter((_, i) => i !== idx))
      }

      const allowedMimes = (field.config?.allowed_mime_types as string[] | undefined)?.filter(m => m)
      return (
        <div style={{ ...wrap, flexDirection: 'column', alignItems: 'stretch' }}>
          <Upload.Dragger
            multiple={Boolean(field.config?.multiple ?? true)}
            showUploadList={false}
            accept={allowedMimes?.length ? allowedMimes.join(',') : 'image/*'}
            beforeUpload={f => { upload(f); return false }}
            style={{ padding: '4px 8px', marginBottom: 4 }}
          >
            <div style={{ fontSize: 12, color: '#94a3b8', margin: '2px 0' }}>
              <InboxOutlined /> 点击或拖拽上传图片
            </div>
          </Upload.Dragger>
          {images.length > 0 && (
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
              <Image.PreviewGroup>
                {images.map((f, i) => (
                  <span key={f.file_key || `${f.filename}-${i}`} style={{ position: 'relative' }}>
                    <AuthedImage
                      wid={wid}
                      fileKey={f.file_key}
                      width={48}
                      height={48}
                      alt={f.filename}
                      style={{ objectFit: 'cover', borderRadius: 4 }}
                    />
                    <Tooltip title="删除该图片">
                      <Button type="text" size="small" danger icon={<DeleteOutlined />}
                        onClick={() => removeAt(i)}
                        style={{ position: 'absolute', top: -6, right: -6, padding: 0, background: 'var(--cn-bg-container)' }} />
                    </Tooltip>
                  </span>
                ))}
              </Image.PreviewGroup>
            </div>
          )}
          {actions}
        </div>
      )
    }
    default: {
      return (
        <div style={wrap}>
          <span style={{ color: '#999' }}>「{getFieldTypeLabel(ft)}」暂不支持在表格里直接编辑</span>
          {actions}
        </div>
      )
    }
  }
}
