/** 文档列表排序 —— 纯函数层.
 *
 * 与后端 `GET /documents?order=sort|updated|created|title` 保持同一口径；
 * 前端再排一次的原因：顶层散文档由全量树派生（不经 list 端点），且分页上限 200 时页内顺序要一致。
 * 置顶优先在所有排序下都成立（与后端 `sort_pinned_first` 一致）。
 */

export type DocumentOrder = 'sort' | 'updated' | 'created' | 'title'

export const DOCUMENT_ORDER_OPTIONS: { value: DocumentOrder; label: string }[] = [
  { value: 'sort', label: '手动顺序' },
  { value: 'updated', label: '最近更新' },
  { value: 'created', label: '创建时间' },
  { value: 'title', label: '标题' },
]

export interface SortableDocument {
  title: string
  sort_order?: number
  updated_at?: string
  created_at?: string
  /** 个人置顶：始终排在同级最前 */
  pinned?: boolean
}

/** 时间戳解析：非法/缺失一律视为最旧（排在后面） */
function timeValue(raw?: string): number {
  if (!raw) return -Infinity
  const t = Date.parse(raw)
  return Number.isNaN(t) ? -Infinity : t
}

/**
 * 排序文档：置顶优先，其次按所选口径；`sort` 口径保持传入顺序（后端已按 sort_order, id 排好）。
 * 采用稳定排序（`Array.prototype.sort` 在现代引擎中稳定），因此同键项保持原相对顺序。
 */
export function sortDocuments<T extends SortableDocument>(items: T[], order: DocumentOrder): T[] {
  const pinnedFirst = (a: T, b: T) => Number(Boolean(b.pinned)) - Number(Boolean(a.pinned))
  if (order === 'sort') {
    // 传入顺序即手动顺序（sort_order 已由后端排定）；仅在置顶分组上做一次稳定重排
    return [...items].sort(pinnedFirst)
  }
  if (order === 'title') {
    return [...items].sort(
      (a, b) =>
        pinnedFirst(a, b) ||
        a.title.localeCompare(b.title, 'zh-Hans-CN', { numeric: true, sensitivity: 'base' }),
    )
  }
  const key = order === 'updated' ? 'updated_at' : 'created_at'
  return [...items].sort((a, b) => pinnedFirst(a, b) || timeValue(b[key]) - timeValue(a[key]))
}
