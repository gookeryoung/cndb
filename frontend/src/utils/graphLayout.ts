/** 图自动分层布局 —— 共享工具函数.
 *
 * GraphPage 和 WorkflowEditorPage 都内嵌了几乎相同的 Kahn 分层算法，
 * 抽到这里作为单一来源。
 */

export interface LayoutNode { id: string }
export interface LayoutEdge { source: string; target: string }

/** Kahn 分层布局，返回每个节点的 { x, y } 坐标.
 *
 * 按拓扑序分层：入度为 0 的节点在最左列，被依赖的先排列。
 * 检测到环时，剩余节点会被追加到最后一层。
 */
export function computeLayeredLayout(
  nodes: LayoutNode[],
  edges: LayoutEdge[],
  options: { colGap?: number; rowGap?: number; startX?: number; startY?: number } = {},
): Map<string, { x: number; y: number }> {
  const colGap = options.colGap ?? 220
  const rowGap = options.rowGap ?? 80
  const startX = options.startX ?? 40
  const startY = options.startY ?? 40

  const pos = new Map<string, { x: number; y: number }>()
  const indeg = new Map<string, number>()

  for (const n of nodes) indeg.set(n.id, 0)
  for (const e of edges) {
    if (indeg.has(e.target)) {
      indeg.set(e.target, (indeg.get(e.target) ?? 0) + 1)
    }
  }

  const reverse = new Map<string, string[]>()
  for (const n of nodes) reverse.set(n.id, [])
  for (const e of edges) {
    if (indeg.has(e.source) && indeg.has(e.target)) {
      reverse.get(e.source)!.push(e.target)
    }
  }

  const layers: string[][] = []
  const remaining = new Set(nodes.map(n => n.id))

  while (remaining.size > 0) {
    const layer: string[] = []
    for (const id of remaining) {
      if ((indeg.get(id) ?? 0) === 0) layer.push(id)
    }
    if (layer.length === 0) break // 检测到环，提前退出
    layers.push(layer)
    for (const id of layer) {
      remaining.delete(id)
      const nexts = reverse.get(id) ?? []
      for (const t of nexts) {
        indeg.set(t, (indeg.get(t) ?? 0) - 1)
      }
    }
  }

  // 有环时剩余节点追加到最后一层
  if (remaining.size > 0) layers.push([...remaining])

  layers.forEach((layer, ci) => {
    layer.forEach((id, ri) => {
      pos.set(id, { x: startX + ci * colGap, y: startY + ri * rowGap })
    })
  })

  return pos
}
