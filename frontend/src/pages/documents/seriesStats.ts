/** 文档系列（顶层文件夹）聚合统计 —— 卡片总览与系列详情头部共用. */

import type { DocumentItem } from '@/api/documents'
import { buildDocTree } from './DocumentTree'
import type { DocTreeNode } from './DocumentTree'

/** 顶层系列（文件夹）聚合统计 — 卡片总览数据源 */
export interface SeriesSummary {
  folder: DocumentItem
  /** 递归子孙文档数（不含子文件夹本身） */
  docCount: number
  /** 递归子文件夹数 */
  subFolderCount: number
  /** 子孙文档标签去重数 */
  tagCount: number
  /** 子孙最近更新时间（含文件夹自身） */
  latestUpdate: string
  /** 子孙文档状态分布（draft/published/archived → 计数） */
  statusCounts: Record<string, number>
}

/** 顶层文件夹即系列：按递归子孙聚合文档数/标签/状态/最近更新 */
export function buildSeriesStats(items: DocumentItem[]): SeriesSummary[] {
  return buildDocTree(items)
    .filter(node => node.is_folder)
    .map(seriesStatsOf)
}

/**
 * 文件夹 → 递归状态分布（父级列表里的文件夹行状态展示用）.
 *
 * 文件夹本身没有"发布"这个动作，其状态语义应与其内部文档保持一致：
 * 子孙文档已发布时，父级列表看到的文件夹也应是已发布，而不是文件夹自身行上的 draft。
 * 空文件夹没有可聚合的文档，就不显示状态（与顶层系列卡片 `statusCounts` 空对象同口径），
 * 避免把文件夹自身的默认 draft 误报成"里面有草稿"。
 */
export function buildFolderStatusCounts(items: DocumentItem[]): Map<number, Record<string, number>> {
  const result = new Map<number, Record<string, number>>()

  const collect = (node: DocTreeNode): Record<string, number> => {
    const counts: Record<string, number> = {}
    for (const child of node.children) {
      if (child.is_folder) {
        const childCounts = collect(child)
        for (const [status, n] of Object.entries(childCounts)) {
          counts[status] = (counts[status] ?? 0) + n
        }
      } else {
        counts[child.status] = (counts[child.status] ?? 0) + 1
      }
    }
    if (node.is_folder) result.set(node.id, counts)
    return counts
  }

  for (const root of buildDocTree(items)) collect(root)
  return result
}

/** 文件夹行的紧凑摘要（列表副标题用）：递归文档数 / 子文件夹数 / 标签去重数 */
export interface FolderSummary {
  docCount: number
  subFolderCount: number
  tagCount: number
}

/** 全部文件夹 → 紧凑摘要；文件夹列表行与卡片共用同一递归口径 */
export function buildFolderSummaries(items: DocumentItem[]): Map<number, FolderSummary> {
  const result = new Map<number, FolderSummary>()
  const walk = (node: DocTreeNode): FolderSummary & { tags: Set<number> } => {
    let docCount = 0
    let subFolderCount = 0
    const tags = new Set<number>()
    for (const child of node.children) {
      if (child.is_folder) {
        const childSummary = walk(child)
        docCount += childSummary.docCount
        subFolderCount += childSummary.subFolderCount + 1
        for (const tag of childSummary.tags) tags.add(tag)
      } else {
        docCount += 1
        for (const tag of child.tag_ids) tags.add(tag)
      }
    }
    if (node.is_folder) result.set(node.id, { docCount, subFolderCount, tagCount: tags.size })
    return { docCount, subFolderCount, tagCount: tags.size, tags }
  }
  for (const root of buildDocTree(items)) walk(root)
  return result
}

/** 单个文件夹的系列聚合统计（递归子孙；系列详情头部复用） */
export function seriesStatsOf(folder: DocTreeNode): SeriesSummary {
  const descendants: DocumentItem[] = []
  const walk = (nodes: DocTreeNode[]) => {
    for (const n of nodes) {
      descendants.push(n)
      walk(n.children)
    }
  }
  walk(folder.children)
  const docs = descendants.filter(d => !d.is_folder)
  const tags = new Set<number>()
  const statusCounts: Record<string, number> = {}
  for (const d of docs) {
    for (const t of d.tag_ids) tags.add(t)
    statusCounts[d.status] = (statusCounts[d.status] ?? 0) + 1
  }
  const latestUpdate = descendants.reduce(
    (max, d) => (d.updated_at > max ? d.updated_at : max),
    folder.updated_at,
  )
  return {
    folder,
    docCount: docs.length,
    subFolderCount: descendants.filter(d => d.is_folder).length,
    tagCount: tags.size,
    latestUpdate,
    statusCounts,
  }
}
