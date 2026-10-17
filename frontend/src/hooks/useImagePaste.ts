/**
 * 剪贴板图片粘贴 —— 图片字段「新增 / 更新」时支持 Ctrl+V 直接上传.
 *
 * 交互口径：
 * 1. 图片字段编辑区（`bindPasteZone` 绑定的容器）获得焦点后，整个文档范围内的
 *    粘贴事件都归它处理，用户不必精确点中上传框；
 * 2. 剪贴板同时带**非空文本**时不动手 —— Excel / Word / 网页复制会同时给出位图
 *    与文本，此时按粘贴文本处理，避免用户的文字凭空消失；
 * 3. 同屏可能存在多个图片字段（整行编辑 / 详情抽屉多列）：优先派发给最近获得
 *    焦点的实例；只有一个实例时直接派发；多实例且都没焦点则忽略，不做猜测。
 */

import { useCallback, useEffect, useRef } from 'react'

interface PasteZone {
  handler: (files: File[]) => void
  /** 该实例的包裹容器，用于判断焦点归属 */
  el: HTMLElement | null
}

const zones = new Set<PasteZone>()
let activeZone: PasteZone | null = null
let listening = false

/** 剪贴板里偶尔给不出 MIME 的文件，用扩展名兜底识别图片 */
const IMAGE_NAME_RE = /\.(png|jpe?g|gif|webp|bmp|avif|svg)$/i

/** 空文件名的剪贴板图片补一个可读名（后端要求 filename 非空） */
function withFileName(file: File, index: number): File {
  if (file.name) return file
  const ext = file.type === 'image/jpeg' ? 'jpg' : (file.type.split('/')[1] || 'png')
  return new File([file], `paste-${Date.now()}-${index}.${ext}`, { type: file.type || 'image/png' })
}

/** 从剪贴板数据中提取图片文件（带非空文本时返回空数组，视为粘贴文本） */
export function clipboardImageFiles(data: DataTransfer | null | undefined): File[] {
  if (!data) return []
  let text = ''
  try {
    text = data.getData?.('text/plain') ?? ''
  } catch {
    // 个别浏览器在非 paste 时机读 getData 会抛错，忽略即可
  }
  if (text.trim()) return []

  const files: File[] = []
  for (const item of Array.from(data.items ?? [])) {
    if (item.kind !== 'file') continue
    const file = item.getAsFile()
    if (!file) continue
    const isImage = file.type.startsWith('image/') || IMAGE_NAME_RE.test(file.name || '')
    if (!isImage) continue
    files.push(withFileName(file, files.length))
  }
  // types 声明为 Files 但 items 为空（部分平台）时按 files 兜底
  if (files.length === 0) {
    for (const file of Array.from(data.files ?? [])) {
      if (file.type.startsWith('image/') || IMAGE_NAME_RE.test(file.name || '')) {
        files.push(withFileName(file, files.length))
      }
    }
  }
  return files
}

function resolveZone(): PasteZone | null {
  if (activeZone && zones.has(activeZone)) return activeZone
  if (zones.size === 1) return zones.values().next().value ?? null
  return null
}

function handlePaste(e: ClipboardEvent) {
  if (e.defaultPrevented) return
  const files = clipboardImageFiles(e.clipboardData)
  if (files.length === 0) return
  const zone = resolveZone()
  if (!zone) return
  // 阻止默认：否则浏览器会把图片当作待粘贴文件/文件名文本处理
  e.preventDefault()
  zone.handler(files)
}

function handleFocusIn(e: FocusEvent) {
  const target = e.target as Node | null
  activeZone = null
  if (!target) return
  for (const zone of zones) {
    if (zone.el?.contains(target)) {
      activeZone = zone
      return
    }
  }
}

/** 按需挂载 / 卸载文档级监听，无实例时不打扰全局粘贴 */
function syncListeners() {
  const need = zones.size > 0
  if (need === listening) return
  listening = need
  if (need) {
    document.addEventListener('paste', handlePaste)
    document.addEventListener('focusin', handleFocusIn)
  } else {
    document.removeEventListener('paste', handlePaste)
    document.removeEventListener('focusin', handleFocusIn)
    activeZone = null
  }
}

/**
 * 注册图片粘贴接收区.
 *
 * @param handler 收到剪贴板图片时的回调（可能一次多张）
 * @param enabled 关闭后不再接收（只读态 / 非图片字段）
 * @returns 绑定到容器元素的 ref 回调，容器获得焦点即成为粘贴目标
 */
export function useImagePaste(
  handler: (files: File[]) => void,
  enabled = true,
): (el: HTMLElement | null) => void {
  const handlerRef = useRef(handler)
  const elRef = useRef<HTMLElement | null>(null)

  useEffect(() => {
    handlerRef.current = handler
  }, [handler])

  useEffect(() => {
    if (!enabled) return
    // el 用 getter 读 ref：ref 回调与 effect 的执行顺序不影响绑定结果
    const zone: PasteZone = {
      handler: files => handlerRef.current(files),
      get el() { return elRef.current },
    }
    zones.add(zone)
    syncListeners()
    return () => {
      zones.delete(zone)
      if (activeZone === zone) activeZone = null
      syncListeners()
    }
  }, [enabled])

  return useCallback((el: HTMLElement | null) => {
    elRef.current = el
  }, [])
}
