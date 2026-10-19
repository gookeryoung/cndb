/** 流程视图纯逻辑层 — 节点平铺 + 有向流转边（与 UI 解耦，可独立单测）.
 *
 * 职责：
 * - flowNodeKey：单行在流程节点字段上的归属 key（link/multi_select 取首值标签，select 取
 *   options 标签，boolean 取 是/否，其余 String 化；空值返回空串）
 * - resolveFlowNodeOrder：节点平铺顺序（显式 node_order → 字段 options → 数据首次出现），
 *   「未配置节点」恒排末尾
 * - buildFlowGraph：行集合 → 节点列表（含各自的行）+ 相邻节点间的有向流转边
 *
 * 设计约定：
 * - 空值/解析失败统一归「未配置节点」，置于末尾且不参与流转边（无节点无从谈流转）
 * - 流转边仅连接**相邻**节点，边上的 count 为下游节点当前的记录数（单节点字段下唯一
 *   自洽的「流入量」口径），因此节点既有本节点记录数（局部），边又表达节点间的推进量
 */

import type { Field, RowResponse } from '@/api'
import { extractSelectOptions } from '../cells/fieldOps'
import { getLinkFirstLabel, getMultiSelectFirstLabel, getSelectLabel } from '../cells/fieldValueFormat'

// ── 常量与类型 ────────────────────────────────────────

/** 节点字段空值的分组显示名（恒排末尾，不参与流转边） */
export const FLOW_UNGROUPED_LABEL = '未配置节点'

/** 单个流程节点：key（= 显示标签）+ 该节点下的行 */
export interface FlowNode {
  key: string
  label: string
  rows: RowResponse[]
}

/** 相邻节点间的有向流转边：count = 下游节点记录数 */
export interface FlowEdge {
  from: string
  to: string
  count: number
}

/** 流程图数据：节点列表（已排序）+ 流转边列表 */
export interface FlowGraphData {
  nodes: FlowNode[]
  edges: FlowEdge[]
}

// ── 节点归属 ──────────────────────────────────────────

/** 计算单行在流程节点字段上的归属 key；空值/解析失败返回空串（调用方归「未配置节点」）.
 *
 * 类型分派与 matrixBoard.axisKeyForRow / 看板 groupKeyForRow 对齐（不含日期分桶）。
 */
export function flowNodeKey(row: RowResponse, fieldDef: Field | undefined): string {
  const fieldName = fieldDef?.name
  const rawVal = fieldName ? row[fieldName] : undefined
  if (fieldDef) {
    const ft = fieldDef.field_type
    if (ft === 'link') return getLinkFirstLabel(rawVal)
    if (ft === 'multi_select' || ft === 'multiselect') return getMultiSelectFirstLabel(rawVal)
    if (ft === 'select') return getSelectLabel(fieldDef, rawVal)
    if (ft === 'boolean') {
      if (rawVal === null || rawVal === undefined || rawVal === '') return ''
      return rawVal ? '是' : '否'
    }
  }
  if (rawVal === null || rawVal === undefined || rawVal === '') return ''
  return String(rawVal)
}

/** 节点字段的候选顺序 —— 仅 select/multiselect 的 options 提供（取 label，与 flowNodeKey 同 key 空间） */
function fieldOptionOrder(fieldDef: Field | undefined): string[] {
  if (!fieldDef) return []
  const ft = fieldDef.field_type
  if (ft !== 'select' && ft !== 'multi_select' && ft !== 'multiselect') return []
  return extractSelectOptions(fieldDef.config)
    .map((o) => o.label)
    .filter(Boolean)
}

// ── 节点排序 ──────────────────────────────────────────

/** 解析节点平铺顺序.
 *
 * 优先级：显式 node_order → 节点字段 options → 数据首次出现顺序；
 * 未在来源中出现的节点按首次出现顺序补齐；「未配置节点」恒排末尾。
 */
export function resolveFlowNodeOrder(
  presentKeys: string[],
  fieldDef: Field | undefined,
  nodeOrder: string[] | undefined,
): string[] {
  const real = presentKeys.filter((k) => k !== FLOW_UNGROUPED_LABEL)
  const hasUngrouped = presentKeys.length !== real.length

  const preferred = nodeOrder && nodeOrder.length > 0 ? nodeOrder : fieldOptionOrder(fieldDef)

  const ordered: string[] = []
  for (const key of preferred) {
    if (real.includes(key) && !ordered.includes(key)) ordered.push(key)
  }
  for (const key of real) {
    if (!ordered.includes(key)) ordered.push(key)
  }
  if (hasUngrouped) ordered.push(FLOW_UNGROUPED_LABEL)
  return ordered
}

// ── 图构建 ────────────────────────────────────────────

/** 构建流程图：单次遍历分行 → 排序节点 → 生成相邻节点间的流转边.
 *
 * - 节点顺序由 resolveFlowNodeOrder 决定
 * - 流转边仅覆盖相邻的**已配置**节点（from/to 均非「未配置节点」），count 取下游节点记录数
 */
export function buildFlowGraph(
  rows: RowResponse[],
  fields: Field[],
  nodeField: string,
  nodeOrder?: string[],
): FlowGraphData {
  const fieldDef = fields.find((f) => f.name === nodeField)

  const byKey = new Map<string, RowResponse[]>()
  const presentKeys: string[] = []
  for (const row of rows) {
    const key = flowNodeKey(row, fieldDef) || FLOW_UNGROUPED_LABEL
    const bucket = byKey.get(key)
    if (bucket) {
      bucket.push(row)
    } else {
      byKey.set(key, [row])
      presentKeys.push(key)
    }
  }

  const nodes: FlowNode[] = resolveFlowNodeOrder(presentKeys, fieldDef, nodeOrder).map((key) => ({
    key,
    label: key,
    rows: byKey.get(key) ?? [],
  }))

  const edges: FlowEdge[] = []
  for (let i = 0; i + 1 < nodes.length; i++) {
    const from = nodes[i]
    const to = nodes[i + 1]
    if (from.key === FLOW_UNGROUPED_LABEL || to.key === FLOW_UNGROUPED_LABEL) continue
    edges.push({ from: from.key, to: to.key, count: to.rows.length })
  }

  return { nodes, edges }
}
