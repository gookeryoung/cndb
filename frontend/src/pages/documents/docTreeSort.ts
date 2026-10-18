/** 文档结构树排序 — 参考 Obsidian 文件浏览器的「排序方式」.
 *
 * 口径：
 * - **文件夹恒在文件之前**（与 Obsidian 一致，不随升降序反转）；
 * - **置顶恒在最前**（个人偏好，优先级高于所选字段）；
 * - 每个层级（根与各文件夹内部）各自排序，互不影响；
 * - `manual` 档不做任何重排，沿用后端 `sort_order`（拖拽整理后的顺序）。
 *
 * 排序偏好是**本地偏好**（localStorage），不写服务端：与 Obsidian 的全局设置一致。
 */

export type DocSortKey = 'manual' | 'name' | 'created_at' | 'updated_at'
export type DocSortOrder = 'asc' | 'desc'

export interface DocSort {
  key: DocSortKey
  order: DocSortOrder
}

/** 参与排序的最小节点形状（避免与 DocumentTree 组件互相依赖） */
export interface SortableDocNode {
  id: number
  title: string
  is_folder: boolean
  pinned: boolean
  created_at: string
  updated_at: string
  children: this[]
}

export const DEFAULT_DOC_SORT: DocSort = { key: 'manual', order: 'asc' }

/** 下拉菜单项（value 同时作为菜单 key 与持久化串） */
export interface DocSortOption {
  value: string
  label: string
  sort: DocSort
}

export const DOC_SORT_OPTIONS: DocSortOption[] = [
  { value: 'manual', label: '手动排序（拖拽）', sort: { key: 'manual', order: 'asc' } },
  { value: 'name-asc', label: '名称 A → Z', sort: { key: 'name', order: 'asc' } },
  { value: 'name-desc', label: '名称 Z → A', sort: { key: 'name', order: 'desc' } },
  { value: 'created-asc', label: '创建时间 旧 → 新', sort: { key: 'created_at', order: 'asc' } },
  { value: 'created-desc', label: '创建时间 新 → 旧', sort: { key: 'created_at', order: 'desc' } },
  { value: 'updated-asc', label: '修改时间 旧 → 新', sort: { key: 'updated_at', order: 'asc' } },
  { value: 'updated-desc', label: '修改时间 新 → 旧', sort: { key: 'updated_at', order: 'desc' } },
]

export const DOC_SORT_STORAGE_KEY = 'cn-doc-tree-sort'

/** 排序配置 → 菜单 key */
const VALUE_PREFIX: Record<DocSortKey, string> = {
  manual: 'manual',
  name: 'name',
  created_at: 'created',
  updated_at: 'updated',
}

export function sortToValue(sort: DocSort): string {
  return sort.key === 'manual' ? 'manual' : `${VALUE_PREFIX[sort.key]}-${sort.order}`
}

/** 菜单 key → 排序配置（非法值回落默认） */
export function valueToSort(value: string): DocSort {
  const hit = DOC_SORT_OPTIONS.find(o => o.value === value)
  return hit ? hit.sort : DEFAULT_DOC_SORT
}

/** 排序配置的中文描述（Tooltip 文案） */
export function describeSort(sort: DocSort): string {
  const hit = DOC_SORT_OPTIONS.find(o => o.value === sortToValue(sort))
  return hit ? hit.label : '手动排序（拖拽）'
}

/** 中文按拼音 + 数字感知比较（"项目2" 排在 "项目10" 之前） */
const collator = new Intl.Collator('zh-Hans-CN', { numeric: true, sensitivity: 'base' })

function timeValue(raw: string): number {
  const t = Date.parse(raw)
  return Number.isNaN(t) ? 0 : t
}

/** 同级比较：置顶 → 文件夹优先 → 所选字段 → id（保证稳定） */
function compareNodes(a: SortableDocNode, b: SortableDocNode, sort: DocSort): number {
  if (a.pinned !== b.pinned) return a.pinned ? -1 : 1
  if (a.is_folder !== b.is_folder) return a.is_folder ? -1 : 1
  const dir = sort.order === 'asc' ? 1 : -1
  let diff = 0
  if (sort.key === 'name') diff = collator.compare(a.title, b.title)
  else if (sort.key === 'created_at') diff = timeValue(a.created_at) - timeValue(b.created_at)
  else if (sort.key === 'updated_at') diff = timeValue(a.updated_at) - timeValue(b.updated_at)
  if (diff !== 0) return diff * dir
  return a.id - b.id
}

/**
 * 按排序配置重排整棵树（递归处理每个层级）。
 * `manual` 档直接返回原数组（后端已按置顶 + sort_order 排好）。
 */
export function sortDocTree<T extends SortableDocNode>(nodes: T[], sort: DocSort): T[] {
  if (sort.key === 'manual') return nodes
  return nodes
    .map(node => ({ ...node, children: sortDocTree(node.children, sort) }))
    .sort((a, b) => compareNodes(a, b, sort))
}

/** 读取本地排序偏好（非法/不可用时回落默认） */
export function readDocSort(): DocSort {
  try {
    const raw = localStorage.getItem(DOC_SORT_STORAGE_KEY)
    return raw ? valueToSort(raw) : DEFAULT_DOC_SORT
  } catch {
    return DEFAULT_DOC_SORT
  }
}

/** 写入本地排序偏好（隐私模式等异常静默忽略） */
export function writeDocSort(sort: DocSort): void {
  try {
    localStorage.setItem(DOC_SORT_STORAGE_KEY, sortToValue(sort))
  } catch {
    /* 存储不可用时不影响本次会话 */
  }
}
