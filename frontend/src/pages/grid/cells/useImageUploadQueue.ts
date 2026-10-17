/** 图片上传队列 —— 本地预览 + 并发上传 + 进度 + 失败重试 / 取消.
 *
 * 为什么要单独抽 hook：
 * 1. 上传是异步的，且一次可能多张；用「队列 + 并发上限」而不是 for-await 串行，
 *    大图上传时不至于一张失败就阻塞后面所有图片；
 * 2. 上传中要有本地预览、进度、失败重试/取消这些状态，散在组件里会和字段值
 *    同步逻辑纠缠；
 * 3. 单图字段的「替换」语义要等新图上传成功才丢弃旧图，避免取消后旧图没了。
 *
 * 字段值约定：`items` 里 `status === 'meta'` 的项按数组顺序就是字段值
 * （上传成功后原位替换，保证用户选择顺序 = 存储顺序）。
 */

import { useEffect, useRef, useState } from 'react'
import type { AttachmentFile } from '@/api'
import { fileApi } from '@/api'

export type ImageQueueItem =
  | { key: string; status: 'meta'; meta: AttachmentFile }
  | {
      key: string
      status: 'queued' | 'uploading' | 'error'
      file: File
      /** 本地 objectURL；环境不支持时为空串 */
      previewUrl: string
      progress: number
      error?: string
      /** 单图字段替换：成功后 old 图由 onReplaced 回调清理 */
      replace?: boolean
      /** 指定替换某一张（comfortable 模式的逐图替换），值为被替换项的 key */
      replaceKey?: string
    }

interface Options {
  wid?: number | string
  tableId?: number | string
  rowId?: number | string
  /** 归属字段 id：后端据此执行字段级大小 / MIME 校验 */
  fieldId?: number | string
  /** 外部字段值（数组 / JSON 字符串 / null） */
  value: unknown
  onChange: (images: AttachmentFile[]) => void
  /** 单图替换成功后回调（由组件负责清理旧文件的物理存储） */
  onReplaced?: (replaced: AttachmentFile[]) => void
  /** 同时上传数量上限；图片较大，默认 2 */
  maxConcurrent?: number
}

/** 把字段值（数组 / JSON 字符串 / null）归一成图片元数据数组 */
export function parseImageList(value: unknown): AttachmentFile[] {
  if (Array.isArray(value)) return value as AttachmentFile[]
  try {
    const parsed = JSON.parse(String(value ?? '[]'))
    return Array.isArray(parsed) ? (parsed as AttachmentFile[]) : []
  } catch {
    return []
  }
}

function metaItems(images: AttachmentFile[]): ImageQueueItem[] {
  return images.map((meta, index) => ({
    key: `m${index}:${meta.file_key || ''}`,
    status: 'meta',
    meta,
  }))
}

function metasOf(items: ImageQueueItem[]): AttachmentFile[] {
  return items.filter((item): item is Extract<ImageQueueItem, { status: 'meta' }> => item.status === 'meta').map(item => item.meta)
}

function sameMetas(a: AttachmentFile[], b: AttachmentFile[]): boolean {
  return a.length === b.length && a.every((meta, i) => meta.file_key === b[i]?.file_key)
}

/** jsdom / 老环境可能没有 objectURL API，降级为空串（预览块由 CSS 兜底） */
function createPreviewUrl(file: File): string {
  try {
    return typeof URL.createObjectURL === 'function' ? URL.createObjectURL(file) : ''
  } catch {
    return ''
  }
}

function revokePreviewUrl(url: string) {
  if (!url) return
  try {
    URL.revokeObjectURL(url)
  } catch {
    /* 忽略：测试环境可能未实现 */
  }
}

export function useImageUploadQueue({
  wid,
  tableId,
  rowId,
  fieldId,
  value,
  onChange,
  onReplaced,
  maxConcurrent = 2,
}: Options) {
  const [items, setItems] = useState<ImageQueueItem[]>(() => metaItems(parseImageList(value)))
  const itemsRef = useRef(items)
  itemsRef.current = items

  const onChangeRef = useRef(onChange)
  onChangeRef.current = onChange
  const onReplacedRef = useRef(onReplaced)
  onReplacedRef.current = onReplaced
  const ctxRef = useRef({ wid, tableId, rowId, fieldId })
  ctxRef.current = { wid, tableId, rowId, fieldId }

  const queueRef = useRef<Array<{ key: string; file: File; replace?: boolean; replaceKey?: string }>>([])
  const activeRef = useRef(0)
  const controllersRef = useRef(new Map<string, AbortController>())
  const seqRef = useRef(0)

  const busy = items.some(item => item.status !== 'meta')

  // 用 ref 同步外部值：只有在「外部值确实变化」且没有进行中任务时才回填，
  // 避免上传成功 -> onChange -> 父级回写 的循环。
  const lastValueRef = useRef(value)
  const pendingValueRef = useRef<unknown>(undefined)
  useEffect(() => {
    if (value !== lastValueRef.current) {
      lastValueRef.current = value
      if (busy) {
        pendingValueRef.current = value
        return
      }
      applyExternal(value)
      return
    }
    if (!busy && pendingValueRef.current !== undefined) {
      const pending = pendingValueRef.current
      pendingValueRef.current = undefined
      applyExternal(pending)
    }
    // applyExternal 只读写 ref，不参与依赖比较
  }, [value, busy])

  function applyExternal(nextValue: unknown) {
    const incoming = parseImageList(nextValue)
    const current = metasOf(itemsRef.current)
    if (sameMetas(incoming, current)) return
    const next = metaItems(incoming)
    itemsRef.current = next
    setItems(next)
  }

  /** 只更新 items（不触发 onChange）：用于进度、状态等中间态 */
  function patchItem(key: string, patch: Record<string, unknown>) {
    const next = itemsRef.current.map(item => (item.key === key ? ({ ...item, ...patch } as ImageQueueItem) : item))
    itemsRef.current = next
    setItems(next)
  }

  /** 更新 items 并回写字段值（成功 / 删除 / 取消） */
  function commit(next: ImageQueueItem[]) {
    itemsRef.current = next
    setItems(next)
    onChangeRef.current(metasOf(next))
  }

  function finishTask(
    key: string,
    options: { replace?: boolean; replaceKey?: string },
    meta: AttachmentFile,
  ) {
    const before = itemsRef.current.find(item => item.key === key)
    if (!before || before.status === 'meta') {
      // 任务已被用户删除 / 取消：丢弃结果
      return
    }
    revokePreviewUrl(before.previewUrl)

    let next: ImageQueueItem[]
    let replaced: AttachmentFile[] = []
    if (options.replaceKey) {
      // 逐图替换：新图占据旧图位置，上传占位项从末尾移除
      const target = itemsRef.current.find(item => item.key === options.replaceKey)
      if (target && target.status === 'meta') {
        replaced = [target.meta]
        next = itemsRef.current
          .filter(item => item.key !== key)
          .map(item => (item.key === options.replaceKey ? { key: options.replaceKey, status: 'meta', meta } : item))
      } else {
        // 目标已不存在：退化为追加，避免上传结果丢失
        next = itemsRef.current.map(item => (item.key === key ? { key, status: 'meta', meta } : item))
      }
    } else if (options.replace) {
      replaced = metasOf(itemsRef.current)
      next = [{ key, status: 'meta', meta }]
    } else {
      next = itemsRef.current.map(item => (item.key === key ? { key, status: 'meta', meta } : item))
    }
    // 队列里若有被替换掉的旧图，一并移除（单图模式下同时只允许一个上传）
    commit(next)
    if (replaced.length > 0) onReplacedRef.current?.(replaced)
  }

  function failTask(key: string, err: unknown) {
    const item = itemsRef.current.find(it => it.key === key)
    if (!item || item.status === 'meta') return
    const message = err instanceof Error ? err.message : '上传失败'
    patchItem(key, { status: 'error', error: message })
  }

  function pump() {
    if (!ctxRef.current.wid) return
    while (activeRef.current < maxConcurrent && queueRef.current.length > 0) {
      const task = queueRef.current.shift()
      if (!task) break
      if (!itemsRef.current.some(item => item.key === task.key)) continue
      activeRef.current += 1
      void runTask(task).finally(() => {
        activeRef.current -= 1
        pump()
      })
    }
  }

  async function runTask(task: { key: string; file: File; replace?: boolean; replaceKey?: string }) {
    const { wid: workspaceId, tableId: tid, rowId: rid, fieldId: fid } = ctxRef.current
    if (!workspaceId) return
    const controller = new AbortController()
    controllersRef.current.set(task.key, controller)
    patchItem(task.key, { status: 'uploading', progress: 0, error: undefined })
    try {
      const meta = await fileApi.upload(
        workspaceId,
        task.file,
        { tableId: tid, rowId: rid, fieldId: fid },
        {
          signal: controller.signal,
          onProgress: percent => {
            const current = itemsRef.current.find(item => item.key === task.key)
            if (current && current.status === 'uploading') patchItem(task.key, { progress: percent })
          },
        },
      )
      controllersRef.current.delete(task.key)
      finishTask(task.key, { replace: task.replace, replaceKey: task.replaceKey }, meta)
    } catch (err) {
      controllersRef.current.delete(task.key)
      // 主动取消：取消逻辑已经把 item 移除了，不再落错误态
      if (controller.signal.aborted) return
      failTask(task.key, err)
    }
  }

  /** 加入上传队列；`replace` 用于单图字段替换（成功后只保留新图），
   *  `replaceKey` 用于逐图替换（新图占据指定旧图的位置） */
  function addFiles(files: File[], options?: { replace?: boolean; replaceKey?: string }) {
    if (!wid || files.length === 0) return
    const next = [...itemsRef.current]
    for (const file of files) {
      seqRef.current += 1
      const key = `u${seqRef.current}`
      next.push({
        key,
        status: 'queued',
        file,
        previewUrl: createPreviewUrl(file),
        progress: 0,
        replace: options?.replace,
        replaceKey: options?.replaceKey,
      })
      queueRef.current.push({ key, file, replace: options?.replace, replaceKey: options?.replaceKey })
    }
    itemsRef.current = next
    setItems(next)
    pump()
  }

  /** 重试失败项：沿用原 file / key，重新入队 */
  function retry(key: string) {
    const item = itemsRef.current.find(it => it.key === key)
    if (!item || item.status === 'meta' || item.status === 'queued' || item.status === 'uploading') return
    patchItem(key, { status: 'queued', progress: 0, error: undefined })
    queueRef.current.push({ key, file: item.file, replace: item.replace, replaceKey: item.replaceKey })
    pump()
  }

  /** 拖拽排序：把 activeKey 移动到 overKey 的位置（仅 meta 项参与） */
  function reorder(activeKey: string, overKey: string) {
    const current = itemsRef.current
    const from = current.findIndex(item => item.key === activeKey)
    const to = current.findIndex(item => item.key === overKey)
    if (from < 0 || to < 0 || from === to) return
    if (current[from].status !== 'meta' || current[to].status !== 'meta') return
    const next = [...current]
    const [moved] = next.splice(from, 1)
    next.splice(to, 0, moved)
    commit(next)
  }

  /** 删除 / 取消一项（上传中的会 abort） */
  function remove(key: string) {
    const item = itemsRef.current.find(it => it.key === key)
    if (!item) return
    const controller = controllersRef.current.get(key)
    if (controller) {
      controller.abort()
      controllersRef.current.delete(key)
    }
    if (item.status !== 'meta') revokePreviewUrl(item.previewUrl)
    commit(itemsRef.current.filter(it => it.key !== key))
  }

  // 卸载：取消在途请求并释放本地预览 URL
  useEffect(() => {
    const controllers = controllersRef.current
    return () => {
      for (const controller of controllers.values()) controller.abort()
      controllers.clear()
      for (const item of itemsRef.current) {
        if (item.status !== 'meta') revokePreviewUrl(item.previewUrl)
      }
      queueRef.current = []
    }
  }, [])

  return { items, busy, addFiles, retry, remove, reorder }
}
