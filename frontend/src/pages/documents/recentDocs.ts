/** 「最近打开」文档 —— 本地（按浏览器）访问历史.
 *
 * 说明：文档模块后端没有「谁在何时看过哪篇」的访问记录，而最近打开属于**个人浏览偏好**，
 * 因此存 localStorage（按工作区分键、上限 N 条、去重后置顶），刷新/重启浏览器仍在。
 * 读写全部 try/catch 兜底：隐私模式或配额不足时退化为「无历史」，不影响编辑。
 */

export interface RecentDocEntry {
  id: number
  title: string
  /** 最近一次打开时间（毫秒时间戳） */
  at: number
}

/** 每个工作区最多保留的条数 */
export const RECENT_DOCS_LIMIT = 8

const KEY_PREFIX = 'cndb_recent_docs_v1'

function storageKey(workspaceId: number | string): string {
  return `${KEY_PREFIX}:${workspaceId}`
}

function safeStorage(): Storage | null {
  try {
    return typeof window !== 'undefined' ? window.localStorage : null
  } catch {
    return null
  }
}

/** 读取最近打开列表（最新在前）；数据损坏时返回空数组 */
export function loadRecentDocs(workspaceId: number | string): RecentDocEntry[] {
  const store = safeStorage()
  if (!store) return []
  try {
    const raw = store.getItem(storageKey(workspaceId))
    if (!raw) return []
    const parsed: unknown = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    return parsed
      .filter((it): it is RecentDocEntry => (
        !!it && typeof it === 'object'
        && typeof (it as RecentDocEntry).id === 'number'
        && typeof (it as RecentDocEntry).title === 'string'
      ))
      .slice(0, RECENT_DOCS_LIMIT)
  } catch {
    return []
  }
}

/** 记录一次打开：同 id 去重置顶，超出上限截断；返回写入后的列表 */
export function pushRecentDoc(
  workspaceId: number | string,
  doc: { id: number; title: string },
  now: number = Date.now(),
): RecentDocEntry[] {
  const next: RecentDocEntry[] = [
    { id: doc.id, title: doc.title, at: now },
    ...loadRecentDocs(workspaceId).filter(it => it.id !== doc.id),
  ].slice(0, RECENT_DOCS_LIMIT)

  const store = safeStorage()
  if (store) {
    try {
      store.setItem(storageKey(workspaceId), JSON.stringify(next))
    } catch {
      // 配额/隐私模式：忽略写入失败，仍返回内存中的结果
    }
  }
  return next
}

/** 清空当前工作区的最近打开记录 */
export function clearRecentDocs(workspaceId: number | string): void {
  const store = safeStorage()
  if (!store) return
  try {
    store.removeItem(storageKey(workspaceId))
  } catch {
    // 忽略
  }
}
