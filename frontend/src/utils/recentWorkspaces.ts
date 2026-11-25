/** 「最近访问」工作区（需求 0160 C4）—— 主页 rail 首屏「继续上次」的数据源.
 *
 * 口径：
 *  - 只存本地 `localStorage`：`{wid, path, ts}`，不建表、不进工作区备份、不上传服务端；
 *  - 只接受 `/w/<数字 id>/<模块段>` 形态的落地路径（查询串 / hash 一律丢弃），
 *    非法路径直接忽略，避免把一次性参数（`?view=` / `?create=`）写进历史；
 *  - 同一工作区只保留最近一条（新记录前移），上限 5 条，按最近使用排序。
 */

import { readPersisted, writePersisted } from '@/utils/persistedState'
export const RECENT_WORKSPACES_KEY = 'cn:recent-workspaces'
export const RECENT_WORKSPACES_LIMIT = 5

export interface RecentWorkspaceEntry {
  /** 工作区 id（字符串，与路由段一致） */
  wid: string
  /** 落地路径（不含查询串 / hash），如 `/w/12/tables` */
  path: string
  /** 记录时间（毫秒时间戳），用于「N 分钟前」展示与排序兜底 */
  ts: number
}

/** 规范化落地路径：只接受 `/w/<id>[/...]`，丢弃查询串与 hash；不合法返回 null */
export function normalizeRecentPath(path: string | null | undefined): string | null {
  if (!path) return null
  const clean = path.split(/[?#]/)[0]
  const match = /^\/w\/(\d+)(\/[^/]+(?:\/[^/]+)*)?\/?$/.exec(clean)
  if (!match) return null
  const rest = (match[2] ?? '').replace(/\/$/, '')
  return `/w/${match[1]}${rest}`
}

/** 从路径里取工作区 id；不是工作区路径返回 null */
export function workspaceIdFromPath(path: string | null | undefined): string | null {
  const normalized = normalizeRecentPath(path)
  return normalized ? normalized.split('/')[2] : null
}

/** 合并一条记录：同 wid 去重后前移，并按上限截断（纯函数，便于单测） */
export function pushRecentWorkspace(
  list: readonly RecentWorkspaceEntry[],
  entry: RecentWorkspaceEntry,
  limit = RECENT_WORKSPACES_LIMIT,
): RecentWorkspaceEntry[] {
  const rest = list.filter(item => item.wid !== entry.wid)
  return [entry, ...rest].slice(0, Math.max(1, limit))
}

/** 读取最近访问（损坏 / 不可用时返回空数组，过滤非法条目） */
export function readRecentWorkspaces(): RecentWorkspaceEntry[] {
  const raw = readPersisted<unknown>(RECENT_WORKSPACES_KEY, [])
  if (!Array.isArray(raw)) return []
  const out: RecentWorkspaceEntry[] = []
  for (const item of raw) {
    if (!item || typeof item !== 'object') continue
    const candidate = item as Partial<RecentWorkspaceEntry>
    const path = normalizeRecentPath(candidate.path)
    const wid = String(candidate.wid ?? workspaceIdFromPath(path) ?? '')
    if (!path || !/^\d+$/.test(wid)) continue
    const ts = Number(candidate.ts)
    out.push({ wid, path, ts: Number.isFinite(ts) ? ts : 0 })
  }
  return out.slice(0, RECENT_WORKSPACES_LIMIT)
}

/** 记录一次工作区访问（导航时调用；非法路径直接忽略，不写存储） */
export function recordRecentWorkspace(path: string | null | undefined, now = Date.now()): void {
  const normalized = normalizeRecentPath(path)
  if (!normalized) return
  const wid = workspaceIdFromPath(normalized)
  if (!wid) return
  const next = pushRecentWorkspace(readRecentWorkspaces(), { wid, path: normalized, ts: now })
  writePersisted(RECENT_WORKSPACES_KEY, next)
}

/** 清空最近访问（切换账号 / 退出登录时调用，避免串号） */
export function clearRecentWorkspaces(): void {
  writePersisted<RecentWorkspaceEntry[]>(RECENT_WORKSPACES_KEY, [])
}
