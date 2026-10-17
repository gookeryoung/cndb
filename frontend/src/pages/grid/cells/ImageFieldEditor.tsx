/** 图片字段编辑器 —— 点击 / 拖拽 / 剪贴板粘贴三种上传入口，缩略图展示 + 删除.
 *
 * 表格内联编辑（EditCell）与行详情抽屉（RowDetailDrawer）共用，保证两条写入
 * 路径（新增 / 更新）的上传、校验、粘贴行为一致。
 */

import { useCallback, useRef } from 'react'
import { App as AntApp, Button, Image, Tooltip, Upload } from 'antd'
import { DeleteOutlined, InboxOutlined } from '@ant-design/icons'
import type { AttachmentFile, Field } from '@/api'
import { fileApi } from '@/api'
import { AuthedImage } from '@/components/AuthedFile'
import { useImagePaste } from '@/hooks/useImagePaste'

interface Props {
  /** 工作区 id（上传 / 删除 / 预览都需要） */
  wid?: number | string
  /** 归属表 id（后端据此按表/行权限校验下载） */
  tableId?: number | string
  /** 归属行 id（同上；新增行时通常为空） */
  rowId?: number | string
  field: Field
  /** 当前值：AttachmentFile[] 或后端存储的 JSON 字符串 */
  value: unknown
  onChange: (images: AttachmentFile[]) => void
  /** 只读态：不上传、不删除、不接收粘贴 */
  disabled?: boolean
  /** 缩略图边长 */
  thumbSize?: number
}

/** 把字段值（数组 / JSON 字符串 / null）归一成图片元数据数组 */
function parseImageList(value: unknown): AttachmentFile[] {
  if (Array.isArray(value)) return value as AttachmentFile[]
  try {
    const parsed = JSON.parse(String(value ?? '[]'))
    return Array.isArray(parsed) ? (parsed as AttachmentFile[]) : []
  } catch {
    return []
  }
}

/** 字段配置里的 MIME 白名单是否接受该文件（配置为空即不限，图片字段默认仅收图片） */
function mimeAllowed(file: File, allowed: string[]): boolean {
  if (allowed.length === 0) return true
  const type = (file.type || '').toLowerCase()
  if (allowed.includes(type)) return true
  const major = type.split('/')[0]
  return Boolean(major) && allowed.includes(`${major}/*`)
}

export function ImageFieldEditor({
  wid,
  tableId,
  rowId,
  field,
  value,
  onChange,
  disabled,
  thumbSize = 48,
}: Props) {
  const { message } = AntApp.useApp()
  const images = parseImageList(value)

  // 上传是异步的：本地列表以 ref 为准，pending 期间不被（尚未更新的）props 覆盖，
  // 保证一次粘贴多张图时不会互相覆盖
  const listRef = useRef<AttachmentFile[]>(images)
  const pendingRef = useRef(0)
  if (pendingRef.current === 0) listRef.current = images

  const allowedMimes = ((field.config?.allowed_mime_types as string[] | undefined) ?? []).filter(m => m)
  const multipleAllowed = Boolean(field.config?.multiple ?? true)

  const appendFiles = useCallback(async (files: File[]) => {
    if (!wid || files.length === 0) return
    const accepted = files.filter(f => {
      const ok = mimeAllowed(f, allowedMimes.length ? allowedMimes : ['image/*'])
      if (!ok) message.error(`「${f.name || '剪贴板图片'}」格式不支持（允许：${allowedMimes.join(', ')}）`)
      return ok
    })
    const targets = multipleAllowed ? accepted : accepted.slice(0, 1)
    if (targets.length === 0) return

    pendingRef.current += targets.length
    for (const file of targets) {
      try {
        const meta = await fileApi.upload(wid, file, { tableId, rowId })
        listRef.current = [...listRef.current, meta]
        onChange(listRef.current)
      } catch (err) {
        message.error(err instanceof Error ? err.message : `「${file.name}」上传失败`)
      } finally {
        pendingRef.current -= 1
      }
    }
  }, [wid, tableId, rowId, onChange, message, allowedMimes, multipleAllowed])

  const handlePaste = useCallback((files: File[]) => {
    void appendFiles(files)
  }, [appendFiles])

  // 只读态不注册，避免抢走文档级粘贴事件
  const bindPasteZone = useImagePaste(handlePaste, !disabled)

  const removeAt = (idx: number) => {
    const removed = images[idx]
    if (wid && removed?.file_key) {
      // 行值更新后再清理会有竞争，失败静默
      fileApi.remove(wid, removed.file_key).catch(() => { })
    }
    const next = images.filter((_, i) => i !== idx)
    listRef.current = next
    onChange(next)
  }

  return (
    <div
      ref={bindPasteZone}
      tabIndex={disabled ? undefined : 0}
      style={{ outline: 'none', width: '100%' }}
    >
      <Upload.Dragger
        multiple={multipleAllowed}
        showUploadList={false}
        accept={allowedMimes.length ? allowedMimes.join(',') : 'image/*'}
        beforeUpload={f => { void appendFiles([f]); return false }}
        style={{ padding: '4px 8px', marginBottom: 8 }}
        disabled={disabled}
      >
        <div style={{ fontSize: 12, color: '#94a3b8', margin: '2px 0' }}>
          <InboxOutlined /> 点击或拖拽上传图片
          {!disabled && <span style={{ marginLeft: 4 }}>（支持 Ctrl+V 粘贴）</span>}
        </div>
      </Upload.Dragger>
      {images.length > 0 && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
          <Image.PreviewGroup>
            {images.map((f, i) => (
              <div
                key={f.file_key || `${f.filename}-${i}`}
                style={{ position: 'relative', width: thumbSize, height: thumbSize }}
              >
                <AuthedImage
                  wid={wid}
                  fileKey={f.file_key}
                  width={thumbSize}
                  height={thumbSize}
                  alt={f.filename}
                  style={{ objectFit: 'cover', borderRadius: 4 }}
                />
                {!disabled && (
                  <Tooltip title="删除该图片">
                    <Button
                      type="text"
                      size="small"
                      danger
                      icon={<DeleteOutlined />}
                      onClick={() => removeAt(i)}
                      style={{
                        position: 'absolute',
                        top: -4,
                        right: -4,
                        padding: 0,
                        background: 'var(--cn-bg-container)',
                      }}
                    />
                  </Tooltip>
                )}
              </div>
            ))}
          </Image.PreviewGroup>
        </div>
      )}
    </div>
  )
}
