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
