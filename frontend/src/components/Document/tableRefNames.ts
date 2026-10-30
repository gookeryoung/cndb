/**
 * 数据表引用占位符的可读名解析（0071）：进程内缓存 + 失败标记 + 变更订阅.
 *
 * 编辑器 live 模式的徽章装饰在构建装饰时同步取名称：命中缓存直接展示，
 * 未命中触发异步拉取并先以源码占位显示，名称到位后经 {@link subscribeRefNames}
 * 通知编辑器重建装饰。拉取失败缓存 error 态（本会话内不重试），调用方回退
 * `#<ID>` 并加警示标识。
 */

import { tableApi, viewApi } from '@/api'
import type { TableRef } from './tableRef'
import { DEFAULT_TABLE_REF_LIMIT } from './tableRef'

type NameEntry = { status: 'pending' | 'ok' | 'error'; name?: string }

/** 表名缓存：`${wid}:${tid}` → 条目 */
const tableCache = new Map<string, NameEntry>()
/** 视图名缓存：`${wid}:${tid}:${vid}` → 条目 */
const viewCache = new Map<string, NameEntry>()

const listeners = new Set<() => void>()

function notify(): void {
  for (const cb of listeners) cb()
}

/** 拉取并缓存名称；fire-and-forget，成功/失败都通知订阅方 */
function fetchInto(key: string, cache: Map<string, NameEntry>, loader: () => Promise<string>): void {
  cache.set(key, { status: 'pending' })
  // Promise.resolve().then 兜底 loader 同步抛错，统一走失败分支
  Promise.resolve().then(loader).then(
    name => {
      cache.set(key, { status: 'ok', name })
      notify()
    },
    () => {
      cache.set(key, { status: 'error' })
      notify()
    },
  )
}

/** 取表名；未命中缓存时触发拉取并返回 null（调用方先按占位处理） */
function tableName(wid: number | string, tid: number): { name?: string; error?: boolean } {
  const key = `${wid}:${tid}`
  const entry = tableCache.get(key)
  if (!entry) {
    fetchInto(key, tableCache, () => tableApi.get(wid, tid).then(t => t.name))
    return {}
  }
  if (entry.status === 'error') return { error: true }
  return { name: entry.name }
}

/** 取视图名；语义同 {@link tableName} */
function viewName(
  wid: number | string, tid: number, vid: number,
): { name?: string; error?: boolean } {
  const key = `${wid}:${tid}:${vid}`
  const entry = viewCache.get(key)
  if (!entry) {
    fetchInto(key, viewCache, () => viewApi.get(wid, tid, vid).then(v => v.name))
    return {}
  }
  if (entry.status === 'error') return { error: true }
  return { name: entry.name }
}

/** 徽章文案解析结果：label 为 null 表示名称仍在加载（调用方暂不渲染徽章） */
export interface RefBadgeInfo {
  /** 徽章文案；null = 名称加载中，保持源码展示 */
  label: string | null
  /** 任一名称拉取失败（回退 `#<ID>`），徽章加警示样式 */
  invalid: boolean
}

/**
 * 组装徽章文案：`表名 · 视图名 · 每页 N`。
 *
 * 无 view 不显示视图段；limit 与默认值相同时不显示每页段；名称失败回退
 * `#<ID>` 并标记 invalid；workspaceId 缺失或名称仍在加载返回 label=null。
 */
export function tableRefBadge(
  ref: TableRef,
  workspaceId: number | string | undefined | null,
): RefBadgeInfo {
  if (workspaceId === undefined || workspaceId === null) return { label: null, invalid: false }

  const table = tableName(workspaceId, ref.tableId)
  if (!table.name && !table.error) return { label: null, invalid: false }

  const parts: string[] = []
  let invalid = false
  if (table.error) {
    parts.push(`#${ref.tableId}`)
    invalid = true
  } else {
    parts.push(table.name!)
    if (ref.view) {
      const view = viewName(workspaceId, ref.tableId, ref.view)
      if (!view.name && !view.error) return { label: null, invalid: false }
      if (view.error) {
        parts.push(`视图 #${ref.view}`)
        invalid = true
      } else {
        parts.push(view.name!)
      }
    }
  }
  if (ref.limit !== DEFAULT_TABLE_REF_LIMIT) parts.push(`每页 ${ref.limit}`)
  return { label: parts.join(' · '), invalid }
}

/** 订阅名称解析完成（成功或失败），返回退订函数；编辑器据此重建装饰 */
export function subscribeRefNames(cb: () => void): () => void {
  listeners.add(cb)
  return () => listeners.delete(cb)
}

/** 清空缓存与订阅（测试隔离用） */
export function resetRefNames(): void {
  tableCache.clear()
  viewCache.clear()
  listeners.clear()
}
