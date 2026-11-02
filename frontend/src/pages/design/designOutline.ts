/** 设计结构树映射（ADR 0083 D3 / D4 / D7）
 *
 * 把「设计清单 + 单设计装配大纲」映射为 antd Tree 的 DataNode。纯函数、无 IO：
 * 标签 / 图标 / 「第 N 行」/ 类型中文名 / 前端派生实例计数都在这里，便于单测。
 * 后端只提供结构（kind / 名称 / 类型 / 1 基行列），前端不做任何 DSL 解析（ADR 0079 I1）。
 */

import type { DesignOutlineNode } from '../../api/design'

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
        meta: { type: 'part', designId, line: node.line, col: node.col, partCount: 1 },
      }
    }
    // use 实例（IR v4）：带 ref 时点击打开源文件（fileId），否则定位当前设计源行
    const ref = node.kind === 'assembly' ? node.ref : undefined
    const children = outlineToTree(node.children, designId, key)
    // 一次后序计数：父节点计数 = 子节点计数求和，每条边只遍历一次（ADR 0086 C7）
    const partCount = children.reduce((total, child) => total + child.meta.partCount, 0)
    const base = { designId, line: node.line, col: node.col, partCount, ...(ref ? { fileId: ref.file_id } : {}) }
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
