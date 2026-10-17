/** 图片字段编辑器 —— 选择文件 / 拖拽 / 剪贴板粘贴三种上传入口，缩略图展示 + 删除.
 *
 * 表格内联编辑（EditCell）与行详情抽屉（RowDetailDrawer）共用，保证两条写入
 * 路径（新增 / 更新）的上传、校验、粘贴行为一致。
 *
 * 交互口径（点击 ≠ 上传）：
 * 1. 点击字段任意位置只**聚焦**粘贴区，让用户可以直接 Ctrl+V 粘贴截图，不再
 *    一按就弹系统文件选择框（弹窗挡在前面时必须先取消才能粘贴）；
 * 2. 打开文件选择框只走显式的「选择图片」按钮，避免误触；
 * 3. 整块区域仍可拖拽文件进入，行为与原来一致。
 */

import { useCallback, useRef, type ChangeEvent, type MouseEvent } from 'react'
import { App as AntApp, Button, Image, Tooltip, Upload } from 'antd'
import { DeleteOutlined, UploadOutlined } from '@ant-design/icons'
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
  const accept = allowedMimes.length ? allowedMimes.join(',') : 'image/*'

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

  // 隐藏的原生 file input：只由「选择图片」按钮触发（Dragger 已关闭点击弹窗）
  const pickerRef = useRef<HTMLInputElement>(null)

  const handlePick = (e: ChangeEvent<HTMLInputElement>) => {
    const picked = Array.from(e.target.files ?? [])
    // 清空 value：否则再次选择同一个文件不会触发 change
    e.target.value = ''
    void appendFiles(picked)
  }

  /** 点击字段空白处只聚焦：聚焦即成为 Ctrl+V 的粘贴目标，不打开系统文件选择框。
   *  子控件（按钮 / 隐藏 input / 图片预览）的点击不抢焦点，保留键盘操作与预览行为。 */
  const focusZone = useCallback((e: MouseEvent<HTMLDivElement>) => {
    if (disabled) return
    const target = e.target as HTMLElement | null
    if (target?.closest('button, input, a, .ant-image')) return
    const el = e.currentTarget
    if (document.activeElement !== el) el.focus({ preventScroll: true })
  }, [disabled])

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
      role="group"
      className="cn-image-field"
      data-testid="image-field"
      aria-label={disabled ? undefined : '图片字段：点击聚焦后可按 Ctrl+V 粘贴图片'}
      onClick={focusZone}
    >
      {!disabled && (
        <>
          <Upload.Dragger
            // 关键：点击不再弹系统文件框，点击只用于聚焦粘贴区
            openFileDialogOnClick={false}
            // 内部有显式按钮，Dragger 自身不再当可聚焦按钮（否则多一个按 Enter 无反应的 tab 停靠点）
            hasControlInside
            multiple={multipleAllowed}
            showUploadList={false}
            accept={accept}
            beforeUpload={f => { void appendFiles([f]); return false }}
            style={{ padding: '4px 8px', marginBottom: 8 }}
          >
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                flexWrap: 'wrap',
                gap: 6,
                fontSize: 12,
                color: '#94a3b8',
                margin: '2px 0',
              }}
            >
              <Button
                size="small"
                icon={<UploadOutlined />}
                data-testid="image-field-pick"
                onClick={() => pickerRef.current?.click()}
              >
                选择图片
              </Button>
              <span>或拖拽到此；点击本区域后 Ctrl+V 粘贴</span>
            </div>
          </Upload.Dragger>
          <input
            ref={pickerRef}
            type="file"
            hidden
            multiple={multipleAllowed}
            accept={accept}
            tabIndex={-1}
            data-testid="image-field-input"
            onChange={handlePick}
          />
        </>
      )}
      {disabled && images.length === 0 && (
        // 只读且无图：与展示态一致给占位，避免字段区一片空白
        <span style={{ color: '#cbd5e1' }}>—</span>
      )}
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
