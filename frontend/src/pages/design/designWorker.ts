/** 设计渲染 Worker —— CSG / 布尔求值移出主线程（ADR 0086 C8）.
 *
 * 协议：
 * - 主线程 → { type: 'eval', gen, nodes }：逐节点求值布尔树，每个节点回一条
 *   { type: 'node', gen, index, hash, geometry }（transferable 数组），末尾回
 *   { type: 'done', gen }。gen 不匹配时静默丢弃——新 IR 到达即取消旧任务。
 * - 缓存：按节点内容哈希（node JSON 的 FNV-1a）缓存序列化几何，未变子树 /
 *   未变参数不重复求值。
 */

import type { DesignIRNode } from '@/api'
import { evalNode, serializeGeometry, type SerializedGeometry } from './renderTree'

/** Worker 上下文（局部断言，避免 reference lib="webworker" 污染全局 DOM lib） */
const ctx = self as unknown as {
  onmessage: ((event: MessageEvent) => void) | null
  postMessage(message: unknown, transfer?: Transferable[]): void
}

/** FNV-1a 32 位（字符串哈希，仅作缓存键，无安全语义） */
function fnv1a(text: string): number {
  let hash = 0x811c9dc5
  for (let i = 0; i < text.length; i += 1) {
    hash ^= text.charCodeAt(i)
    hash = Math.imul(hash, 0x01000193)
  }
  return hash >>> 0
}

/** 节点内容哈希 → 序列化几何缓存 */
const cache = new Map<number, SerializedGeometry>()

/** 当前接受的代际：旧 gen 的求值结果一律不发（新 IR 取消旧任务） */
let currentGen = 0

ctx.onmessage = (event: MessageEvent) => {
  const message = event.data as { type?: string; gen?: number; nodes?: DesignIRNode[] }
  if (message.type !== 'eval' || !Array.isArray(message.nodes)) return
  currentGen = message.gen ?? 0
  const { gen, nodes } = message as { gen: number; nodes: DesignIRNode[] }

  for (let index = 0; index < nodes.length; index += 1) {
    if (gen !== currentGen) return // 已被更新的 eval 取代，停止分片求值
    const node = nodes[index]
    const hash = fnv1a(JSON.stringify(node))
    let payload = cache.get(hash)
    if (!payload) {
      try {
        const geometry = evalNode(node)
        payload = geometry ? serializeGeometry(geometry) : undefined
      } catch {
        payload = undefined
      }
      if (payload) cache.set(hash, payload)
    }
    if (payload) {
      // 拷贝一份用于 transfer，缓存内保留原件
      const transfer: SerializedGeometry = {
        position: payload.position.slice(),
        normal: payload.normal.slice(),
        index: payload.index.slice(),
      }
      ctx.postMessage({ type: 'node', gen, index, hash, geometry: transfer }, [
        transfer.position.buffer,
        transfer.normal.buffer,
        transfer.index.buffer,
      ])
    } else {
      ctx.postMessage({ type: 'node', gen, index, hash, geometry: null })
    }
  }
  if (gen === currentGen) ctx.postMessage({ type: 'done', gen })
}
