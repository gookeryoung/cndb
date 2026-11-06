/** 设计结构树映射（ADR 0083 D3 / D4 / D7）
 *
 * 把「设计清单 + 单设计装配大纲」映射为 antd Tree 的 DataNode。纯函数、无 IO：
 * 标签 / 图标 / 「第 N 行」/ 类型中文名 / 前端派生实例计数都在这里，便于单测。
 * 后端只提供结构（kind / 名称 / 类型 / 1 基行列），前端不做任何 DSL 解析（ADR 0079 I1）。
 */

import type { DesignListItem, DesignOutlineNode } from '../../api/design'

/** 最近更新的设计 id（默认打开口径，ADR 0109 D3；列表按 updated_at 字符串比较） */
export function latestDesignId(items: DesignListItem[]): number | null {
  let best: DesignListItem | undefined
  for (const item of items) {
    if (!best || String(item.updated_at) > String(best.updated_at)) best = item
  }
  return best?.id ?? null
}

/** 树节点负载：供点击跳转 / 图标 / 文案渲染使用 */
export interface DesignTreeMeta {
  /** 节点类别：设计根 / 系统（复杂系统级，ADR 0084）/ 组件 / 分组 / 零件 */
  type: 'design' | 'system' | 'assembly' | 'group' | 'part'
  /** 设计节点：设计 id（用于打开编辑器） */
  designId?: number
  /** 大纲节点：1 基源行（用于编辑器定位） */
  line?: number
  /** 大纲节点：1 基源列 */
  col?: number
  /** use 实例的源文件 id（IR v4，ADR 0086 §7）：点击打开源文件而非当前设计 */
  fileId?: number
  /** 子树内的零件计数（一次后序遍历派生，ADR 0086 C7） */
  partCount: number
  /** 渲染实体下标（IR v5，ADR 0103 D7）：选中该节点时高亮的顶层 nodes 集合来源 */
  nodeIndex?: number | null
}

export interface DesignTreeEntry {
  key: string
  title: string
  /** 节点描述：类型 / 行号 / 数量 */
  detail: string
  /** 叶子（无子节点，不显示展开箭头） */
  isLeaf: boolean
  meta: DesignTreeMeta
  /** 子条目（组件 / 分组可嵌套；零件无） */
  children?: DesignTreeEntry[]
}

const GROUP_LABELS: Record<string, string> = {
  union: '并集',
  difference: '差集',
  intersection: '交集',
}

const PRIMITIVE_LABELS: Record<string, string> = {
  box: '立方体',
  cyl: '圆柱',
  sphere: '球体',
  cone: '圆锥',
  torus: '圆环',
  tube: '圆管',
}

/** 布尔分组的中文名（未知 op 原样返回，避免吞掉后端新增值） */
export function groupLabel(op: string): string {
  return GROUP_LABELS[op] ?? op
}

/** 图元的中文名（未知类型原样返回） */
export function primitiveLabel(primitive: string): string {
  return PRIMITIVE_LABELS[primitive] ?? primitive
}

/** 子树零件计数（part 记 1，system / assembly / group 递归求和） */
export function countParts(node: DesignOutlineNode): number {
  if (node.kind === 'part') return 1
  return node.children.reduce((total, child) => total + countParts(child), 0)
}

/** 大纲节点 → 树条目（递归；key 由路径拼接，保证同层多实例不撞 key） */
export function outlineToTree(
  nodes: DesignOutlineNode[],
  designId: number,
  parentKey = `design-${designId}`,
): DesignTreeEntry[] {
  return nodes.map((node, index) => {
    const key = `${parentKey}-${index}`
    if (node.kind === 'part') {
      return {
        key,
        title: primitiveLabel(node.primitive),
        detail: `零件 · 第 ${node.line} 行`,
        isLeaf: true,
        meta: {
          type: 'part', designId, line: node.line, col: node.col, partCount: 1, nodeIndex: node.node_index ?? null,
        },
      }
    }
    // use 实例（IR v4）：带 ref 时点击打开源文件（fileId），否则定位当前设计源行
    const ref = node.kind === 'assembly' ? node.ref : undefined
    const children = outlineToTree(node.children, designId, key)
    // 一次后序计数：父节点计数 = 子节点计数求和，每条边只遍历一次（ADR 0086 C7）
    const partCount = children.reduce((total, child) => total + child.meta.partCount, 0)
    const base = {
      designId,
      line: node.line,
      col: node.col,
      partCount,
      nodeIndex: node.node_index ?? null,
      ...(ref ? { fileId: ref.file_id } : {}),
    }
    if (node.kind === 'system') {
      return {
        key,
        title: node.name,
        detail: `系统 · 第 ${node.line} 行 · ${partCount} 个零件`,
        isLeaf: children.length === 0,
        meta: { type: 'system', ...base },
        children,
      }
    }
    if (node.kind === 'assembly') {
      return {
        key,
        title: node.name,
        detail: ref ? `组件（${ref.file_key}） · ${partCount} 个零件` : `组件 · 第 ${node.line} 行 · ${partCount} 个零件`,
        isLeaf: children.length === 0,
        meta: { type: 'assembly', ...base },
        children,
      }
    }
    return {
      key,
      title: groupLabel(node.op),
      detail: `结构分组 · 第 ${node.line} 行 · ${partCount} 个零件`,
      isLeaf: children.length === 0,
      meta: { type: 'group', ...base },
      children,
    }
  })
}

/** 打开设计的编辑器路径；大纲节点带 ?line= 定位源行（D7） */
export function designEditorPath(workspaceId: number | string, designId: number, line?: number): string {
  const path = `/w/${workspaceId}/design/${designId}`
  return line && line > 0 ? `${path}?line=${line}` : path
}

/** 反向定位（ADR 0103 D9 / C1②）：源行 → 大纲节点路径（根 → 最深命中）.
 *
 * 归属规则：在**当前文件**的节点里取 `line ≤ revealLine` 中行号最大者（同号取更深者），
 * 再从根拼出它的祖先链。这样同时满足「同父下取最后一个 `line ≤ revealLine`」的直觉，
 * 又能处理 module 的行号倒挂——组件实例节点带的是**调用行**（晚于其内部零件的声明行），
 * 只按同父规则逐层下探会在实例行晚于 revealLine 时完全落空。
 * `use` 实例子树的行号属于被引用文件（跨文件不可比），按 `file_id` 过滤掉。
 * 早于全部行 → 返回空数组（不选中）。
 */
export function resolveOutlinePath(
  nodes: DesignOutlineNode[],
  revealLine: number,
  designId: number,
): DesignOutlineNode[] {
  let bestPath: DesignOutlineNode[] = []
  let bestLine = -Infinity
  const walk = (level: DesignOutlineNode[], path: DesignOutlineNode[]) => {
    for (const node of level) {
      if (node.file_id != null && node.file_id !== designId) continue
      const nextPath = [...path, node]
      if (node.line <= revealLine
        && (node.line > bestLine || (node.line === bestLine && nextPath.length > bestPath.length))) {
        bestPath = nextPath
        bestLine = node.line
      }
      if (node.kind !== 'part') walk(node.children, nextPath)
    }
  }
  walk(nodes, [])
  return bestPath
}

/** 选中节点 → 需高亮的顶层 nodes 下标集合（自身子树递归，去重；v4 快照为空 = 不高亮） */
export function collectNodeIndices(node: DesignOutlineNode): number[] {
  const indices = new Set<number>()
  const walk = (current: DesignOutlineNode) => {
    if (current.node_index != null) indices.add(current.node_index)
    if (current.kind !== 'part') current.children.forEach(walk)
  }
  walk(node)
  return [...indices]
}

/** 大纲节点同一定位判定：接口来源不同（/outline 与 /ir 快照）时对象身份不同，按位置签名比较 */
function sameOutlineNode(a: DesignOutlineNode, b: DesignOutlineNode): boolean {
  if (a.kind !== b.kind || a.line !== b.line || a.col !== b.col) return false
  if (a.kind === 'assembly' && b.kind === 'assembly') return a.name === b.name
  if (a.kind === 'system' && b.kind === 'system') return a.name === b.name
  return true
}

/** 反向定位 → 树节点 key 路径（与 outlineToTree 的 `parentKey-index` 口径一致） */
export function outlineKeyPath(
  nodes: DesignOutlineNode[],
  path: DesignOutlineNode[],
  designId: number,
): string[] {
  if (path.length === 0) return []
  const keys: string[] = []
  const locate = (level: DesignOutlineNode[], key: string, depth: number): boolean => {
    for (let index = 0; index < level.length; index += 1) {
      const node = level[index]
      if (!sameOutlineNode(node, path[depth])) continue
      const nodeKey = `${key}-${index}`
      keys.push(nodeKey)
      if (depth + 1 < path.length && node.kind !== 'part') {
        return locate(node.children, nodeKey, depth + 1)
      }
      return true
    }
    return false
  }
  locate(nodes, `design-${designId}`, 0)
  return keys
}
