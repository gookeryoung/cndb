/** 图片字段编辑器 —— 紧凑缩略图网格 + 本地预览 / 进度 / 失败重试 + 单图替换语义.
 *
 * 交互口径（点击 ≠ 上传）：
 * 1. 点击字段任意位置只**聚焦**粘贴区，让用户可以直接 Ctrl+V 粘贴截图，不再
 *    一按就弹系统文件选择框（弹窗挡在前面时必须先取消才能粘贴）；
 * 2. 打开文件选择框只走显式的「+ / 添加（替换）」按钮，避免误触；
 * 3. 整块区域仍可拖拽文件进入，删除 / 取消只在悬停时露出，窄屏和平板常显。
 *
 * 这次 P0 优化的点：
 * - 去掉常驻的大块 Upload.Dragger，编辑态只占一行瓦片的高度；
 * - 每张图有独立的「上传中 / 失败 / 重试 / 取消」状态，本地 objectURL 先出预览；
 * - 单图字段（multiple=false）改为「替换」语义：新图上传成功后才丢弃旧图；
 * - 上传前按字段配置校验 MIME 与 max_size_mb，不再让后端 413/415 才暴露。
 */

import { useCallback, useRef, useState, type ChangeEvent, type CSSProperties, type DragEvent, type MouseEvent } from 'react'
import { App as AntApp, Image, Tooltip } from 'antd'
import { DeleteOutlined, PlusOutlined, ReloadOutlined, SwapOutlined } from '@ant-design/icons'
import { DndContext, PointerSensor, closestCenter, useSensor, useSensors, type DragEndEvent } from '@dnd-kit/core'
import { SortableContext, rectSortingStrategy, useSortable } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import type { AttachmentFile, Field } from '@/api'
import { fileApi } from '@/api'
import { AuthedImage } from '@/components/AuthedFile'
import { useImagePaste } from '@/hooks/useImagePaste'
import { formatSize } from '@/utils/formatSize'
import { useImageUploadQueue, type ImageQueueItem } from './useImageUploadQueue'

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
  /** 缩略图边长（表格内联 32；行详情抽屉传 56） */
  thumbSize?: number
}

/** 字段配置里的 MIME 白名单是否接受该文件（配置为空即不限，图片字段默认仅收图片） */
function mimeAllowed(file: File, allowed: string[]): boolean {
  if (allowed.length === 0) return true
  const type = (file.type || '').toLowerCase()
  if (allowed.includes(type)) return true
  const major = type.split('/')[0]
  return Boolean(major) && allowed.includes(`${major}/*`)
}

/** 已上传图片的瓦片：comfortable 模式支持逐图替换 + 拖拽排序 */
function MetaTile({
  itemKey,
  meta,
  wid,
  thumbSize,
  disabled,
  comfortable,
  sortable,
  onRemove,
  onReplace,
}: {
  itemKey: string
  meta: AttachmentFile
  wid?: number | string
  thumbSize: number
  disabled?: boolean
  comfortable: boolean
  sortable: boolean
  onRemove: (key: string) => void
  onReplace: (key: string) => void
}) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: itemKey,
    disabled: !sortable,
  })
  const style: CSSProperties = {
    width: thumbSize,
    height: thumbSize,
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.55 : undefined,
    zIndex: isDragging ? 2 : undefined,
  }
  const metaTitle = `${meta.filename}${meta.size ? ` · ${formatSize(meta.size)}` : ''}`

  return (
    <div
      ref={setNodeRef}
      style={style}
      className={`cn-image-field__tile${isDragging ? ' is-dragging-tile' : ''}`}
      {...attributes}
      {...listeners}
    >
      <Tooltip title={metaTitle}>
        <AuthedImage
          wid={wid}
          fileKey={meta.file_key}
          width={thumbSize}
          height={thumbSize}
          alt={meta.filename}
          style={{ objectFit: 'cover', width: '100%', height: '100%' }}
        />
      </Tooltip>
      {!disabled && (
        <div className="cn-image-field__ops">
          {comfortable && (
            <Tooltip title="替换该图片">
              <button
                type="button"
                className="cn-image-field__op"
                aria-label={`替换 ${meta.filename}`}
                onPointerDown={e => e.stopPropagation()}
                onClick={e => { e.stopPropagation(); onReplace(itemKey) }}
              >
                <SwapOutlined />
              </button>
            </Tooltip>
          )}
          <Tooltip title="删除该图片">
            <button
              type="button"
              className="cn-image-field__op is-danger"
              aria-label="删除该图片"
              onPointerDown={e => e.stopPropagation()}
              onClick={e => { e.stopPropagation(); onRemove(itemKey) }}
            >
              <DeleteOutlined />
            </button>
          </Tooltip>
        </div>
      )}
    </div>
  )
}

export function ImageFieldEditor({
  wid,
  tableId,
  rowId,
  field,
  value,
  onChange,
  disabled,
  thumbSize = 32,
}: Props) {
  const { message } = AntApp.useApp()

  const allowedMimes = ((field.config?.allowed_mime_types as string[] | undefined) ?? []).filter(m => m)
  const multipleAllowed = Boolean(field.config?.multiple ?? true)
  const accept = allowedMimes.length ? allowedMimes.join(',') : 'image/*'
  const maxSizeMb = Math.max(0, Number(field.config?.max_size_mb ?? 10) || 0)
  const maxSizeBytes = maxSizeMb * 1024 * 1024

  // 单图字段替换成功后，旧文件由这里做物理清理（行值已切换到新图）
  const handleReplaced = useCallback((replaced: AttachmentFile[]) => {
    if (!wid) return
    for (const meta of replaced) {
      if (meta.file_key) fileApi.remove(wid, meta.file_key).catch(() => { /* 行值已切换，清理失败静默 */ })
    }
  }, [wid])

  const queue = useImageUploadQueue({ wid, tableId, rowId, value, onChange, onReplaced: handleReplaced })
  const { items } = queue

  const metaItems = items.filter((item): item is Extract<ImageQueueItem, { status: 'meta' }> => item.status === 'meta')
  const hasMeta = metaItems.length > 0
  const uploading = items.some(item => item.status === 'queued' || item.status === 'uploading')
  const comfortable = thumbSize >= 48
  // 拖拽排序只在「行详情大图模式 + 多图 + 空闲」时开启：小瓦片拖拽体验差且易误触
  const sortable = comfortable && multipleAllowed && !disabled && !queue.busy && metaItems.length > 1

  const [dragging, setDragging] = useState(false)
  const dragDepth = useRef(0)
  const pickerRef = useRef<HTMLInputElement>(null)
  /** 逐图替换的目标 key：由「替换」按钮设置，下次选文件时消费 */
  const replaceKeyRef = useRef<string | null>(null)
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 6 } }))

  /** 上传前校验：MIME 白名单 + 字段级 max_size_mb + 单/多图约束 */
  const validateFiles = useCallback((files: File[]): File[] => {
    const accepted: File[] = []
    for (const file of files) {
      const name = file.name || '剪贴板图片'
      if (!mimeAllowed(file, allowedMimes.length ? allowedMimes : ['image/*'])) {
        message.error(`「${name}」格式不支持（允许：${allowedMimes.length ? allowedMimes.join(', ') : '图片'}）`)
        continue
      }
      if (maxSizeBytes > 0 && file.size > maxSizeBytes) {
        message.error(`「${name}」为 ${formatSize(file.size)}，超过单张 ${maxSizeMb}MB 限制`)
        continue
      }
      accepted.push(file)
    }
    if (!multipleAllowed && accepted.length > 1) {
      message.info('单图字段只保留第一张图片')
    }
    return multipleAllowed ? accepted : accepted.slice(0, 1)
  }, [allowedMimes, maxSizeBytes, maxSizeMb, message, multipleAllowed])

  const enqueueFiles = useCallback((files: File[], replaceKey?: string | null) => {
    const accepted = validateFiles(files)
    if (accepted.length === 0) return
    if (replaceKey) {
      // 逐图替换：只取第一张，成功后再清理被替换的那张
      queue.addFiles([accepted[0]], { replaceKey })
      if (accepted.length > 1) message.info('替换只使用第一张图片')
      return
    }
    // 单图字段已有图：走替换（新图成功后才删旧图）
    queue.addFiles(accepted, { replace: !multipleAllowed && hasMeta })
  }, [queue, validateFiles, multipleAllowed, hasMeta, message])

  /** 打开文件选择框；传入 key 表示替换指定图片（而不是追加） */
  const openPicker = (replaceKey?: string) => {
    replaceKeyRef.current = replaceKey ?? null
    pickerRef.current?.click()
  }

  // 只读态不注册，避免抢走文档级粘贴事件
  const bindPasteZone = useImagePaste(files => enqueueFiles(files), !disabled)

  const handlePick = (e: ChangeEvent<HTMLInputElement>) => {
    const picked = Array.from(e.target.files ?? [])
    const replaceKey = replaceKeyRef.current
    replaceKeyRef.current = null
    // 清空 value：否则再次选择同一个文件不会触发 change
    e.target.value = ''
    enqueueFiles(picked, replaceKey)
  }

  const handleDragEnd = (event: DragEndEvent) => {
    const { active, over } = event
    if (!over || active.id === over.id) return
    queue.reorder(String(active.id), String(over.id))
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

  const handleDragEnter = (e: DragEvent<HTMLDivElement>) => {
    if (disabled) return
    e.preventDefault()
    dragDepth.current += 1
    setDragging(true)
  }
  const handleDragOver = (e: DragEvent<HTMLDivElement>) => {
    if (disabled) return
    e.preventDefault()
    if (e.dataTransfer) e.dataTransfer.dropEffect = 'copy'
  }
  const handleDragLeave = (e: DragEvent<HTMLDivElement>) => {
    if (disabled) return
    e.preventDefault()
    dragDepth.current = Math.max(0, dragDepth.current - 1)
    if (dragDepth.current === 0) setDragging(false)
  }
  const handleDrop = (e: DragEvent<HTMLDivElement>) => {
    if (disabled) return
    e.preventDefault()
    dragDepth.current = 0
    setDragging(false)
    const files = Array.from(e.dataTransfer?.files ?? [])
    if (files.length > 0) enqueueFiles(files)
  }

  const removeItem = (key: string) => {
    const item = items.find(it => it.key === key)
    if (item?.status === 'meta' && wid && item.meta.file_key) {
      // 行值更新后再清理会有竞争，失败静默
      fileApi.remove(wid, item.meta.file_key).catch(() => { })
    }
    queue.remove(key)
  }

  const tileStyle = { width: thumbSize, height: thumbSize }
  const addLabel = multipleAllowed ? '添加图片' : hasMeta ? '替换图片' : '选择图片'

  return (
    <div
      ref={bindPasteZone}
      tabIndex={disabled ? undefined : 0}
      role="group"
      className={`cn-image-field${dragging ? ' is-dragging' : ''}`}
      data-testid="image-field"
      aria-label={disabled ? undefined : '图片字段：点击聚焦后可按 Ctrl+V 粘贴图片'}
      onClick={focusZone}
      onDragEnter={handleDragEnter}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
    >
      {disabled && items.length === 0 && (
        // 只读且无图：与展示态一致给占位，避免字段区一片空白
        <span style={{ color: '#cbd5e1' }}>—</span>
      )}

      {items.length > 0 && (
        <div className="cn-image-field__tiles">
          <Image.PreviewGroup>
            <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
              <SortableContext items={metaItems.map(item => item.key)} strategy={rectSortingStrategy}>
                {items.map(item => item.status === 'meta' ? (
                  <MetaTile
                    key={item.key}
                    itemKey={item.key}
                    meta={item.meta}
                    wid={wid}
                    thumbSize={thumbSize}
                    disabled={disabled}
                    comfortable={comfortable}
                    sortable={sortable}
                    onRemove={removeItem}
                    onReplace={key => openPicker(key)}
                  />
                ) : (
                  <div key={item.key} className={`cn-image-field__tile is-${item.status}`} style={tileStyle}>
                    {item.previewUrl ? (
                      <img src={item.previewUrl} alt="" className="cn-image-field__preview" />
                    ) : (
                      <span className="cn-image-field__preview cn-image-field__preview--empty" />
                    )}
                    {item.status === 'error' ? (
                      <div className="cn-image-field__err">
                        <span>上传失败</span>
                        <button
                          type="button"
                          className="cn-image-field__retry"
                          onClick={e => { e.stopPropagation(); queue.retry(item.key) }}
                        >
                          <ReloadOutlined /> 重试
                        </button>
                      </div>
                    ) : (
                      <div className="cn-image-field__mask">
                        <span className="cn-image-field__spinner" aria-hidden />
                        <span className="cn-image-field__pct">
                          {item.status === 'queued' ? '等待' : `${item.progress}%`}
                        </span>
                      </div>
                    )}
                    <button
                      type="button"
                      className="cn-image-field__del"
                      aria-label="取消上传"
                      onClick={e => { e.stopPropagation(); queue.remove(item.key) }}
                    >
                      <DeleteOutlined />
                    </button>
                  </div>
                ))}
              </SortableContext>
            </DndContext>
          </Image.PreviewGroup>
        </div>
      )}

      {!disabled && (
        <div className="cn-image-field__actions">
          <button
            type="button"
            className="cn-image-field__add"
            style={tileStyle}
            data-testid="image-field-pick"
            title={addLabel}
            aria-label={addLabel}
            disabled={!multipleAllowed && uploading}
            onClick={() => openPicker()}
          >
            {!multipleAllowed && hasMeta ? <SwapOutlined /> : <PlusOutlined />}
            {comfortable && <span className="cn-image-field__add-text">{multipleAllowed ? '添加' : hasMeta ? '替换' : '选择'}</span>}
          </button>
          {items.length === 0 && (
            <div className="cn-image-field__hint">
              点击 + 选择图片，或拖拽到此；聚焦后按 Ctrl+V 粘贴
            </div>
          )}
          {comfortable && sortable && (
            <div className="cn-image-field__hint">拖动缩略图可调整顺序</div>
          )}
        </div>
      )}

      {!disabled && (
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
      )}
    </div>
  )
}
