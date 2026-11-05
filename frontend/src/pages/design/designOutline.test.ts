/** 设计结构树映射单测（ADR 0083 D3 / D4 / D7）：标签 / 图标语义 / 源行 / 计数 / 空大纲. */

import { describe, expect, it } from 'vitest'
import type { DesignOutlineNode } from '@/api'
import {
  collectNodeIndices, countParts, designEditorPath, groupLabel, outlineKeyPath, outlineToTree,
  primitiveLabel, resolveOutlinePath,
} from './designOutline'

const OUTLINE: DesignOutlineNode[] = [
  {
    kind: 'assembly',
    name: 'plate',
    line: 10,
    col: 1,
    children: [
      {
        kind: 'group',
        op: 'difference',
        line: 11,
        col: 3,
        children: [
          { kind: 'part', primitive: 'box', line: 12, col: 5 },
          { kind: 'part', primitive: 'cyl', line: 14, col: 7 },
        ],
      },
    ],
  },
]

describe('outlineToTree', () => {
  it('按装配层级映射节点并携带 1 基源位置', () => {
    const [assembly] = outlineToTree(OUTLINE, 20)
    expect(assembly).toMatchObject({
      key: 'design-20-0',
      title: 'plate',
      detail: '组件 · 第 10 行 · 2 个零件',
      isLeaf: false,
      meta: { type: 'assembly', designId: 20, line: 10, col: 1, partCount: 2 },
    })
    const [group] = assembly!.children!
    expect(group).toMatchObject({
      key: 'design-20-0-0',
      title: '差集',
      detail: '结构分组 · 第 11 行 · 2 个零件',
      meta: { type: 'group', line: 11, col: 3, partCount: 2 },
    })
    expect(group!.children).toEqual([
      expect.objectContaining({
        key: 'design-20-0-0-0',
        title: '立方体',
        detail: '零件 · 第 12 行',
        isLeaf: true,
        meta: expect.objectContaining({ type: 'part', line: 12, col: 5, partCount: 1 }),
      }),
      expect.objectContaining({ key: 'design-20-0-0-1', title: '圆柱', detail: '零件 · 第 14 行' }),
    ])
  })

  it('同层多实例不撞 key（按索引区分）', () => {
    const nodes: DesignOutlineNode[] = [
      { kind: 'part', primitive: 'box', line: 1, col: 1 },
      { kind: 'part', primitive: 'sphere', line: 2, col: 1 },
    ]
    expect(outlineToTree(nodes, 7).map((entry) => entry.key)).toEqual(['design-7-0', 'design-7-1'])
  })

  it('空大纲映射为空数组', () => {
    expect(outlineToTree([], 7)).toEqual([])
  })

  it('无子节点的组件 / 分组按叶子处理', () => {
    const [assembly] = outlineToTree([{ kind: 'assembly', name: 'm', line: 3, col: 1, children: [] }], 9)
    expect(assembly!.isLeaf).toBe(true)
    expect(assembly!.meta.partCount).toBe(0)
  })

  it('系统级节点（ADR 0084）：标签「系统」+ 声明行 + 递归零件计数', () => {
    const nodes: DesignOutlineNode[] = [{
      kind: 'system',
      name: 'rover',
      line: 27,
      col: 1,
      children: [
        { kind: 'assembly', name: 'chassis', line: 28, col: 3, children: [
          { kind: 'part', primitive: 'box', line: 22, col: 5 },
        ] },
        { kind: 'part', primitive: 'sphere', line: 34, col: 3 },
      ],
    }]
    const [system] = outlineToTree(nodes, 20)
    expect(system).toMatchObject({
      key: 'design-20-0',
      title: 'rover',
      detail: '系统 · 第 27 行 · 2 个零件',
      isLeaf: false,
      meta: { type: 'system', designId: 20, line: 27, col: 1, partCount: 2 },
    })
    expect(system!.children!.map(entry => entry.meta.type)).toEqual(['assembly', 'part'])
    expect(countParts(nodes[0]!)).toBe(2)
  })
})

describe('辅助映射', () => {
  it('布尔分组与图元中文名；未知值原样返回', () => {
    expect(groupLabel('union')).toBe('并集')
    expect(groupLabel('intersection')).toBe('交集')
    expect(groupLabel('custom')).toBe('custom')
    expect(primitiveLabel('torus')).toBe('圆环')
    expect(primitiveLabel('unknown')).toBe('unknown')
  })

  it('countParts 递归统计零件', () => {
    expect(countParts(OUTLINE[0]!)).toBe(2)
    expect(countParts({ kind: 'part', primitive: 'box', line: 1, col: 1 })).toBe(1)
  })

  it('编辑器路径：带源行时追加 ?line=，非法行不追加', () => {
    expect(designEditorPath(10, 20)).toBe('/w/10/design/20')
    expect(designEditorPath('10', 20, 12)).toBe('/w/10/design/20?line=12')
    expect(designEditorPath(10, 20, 0)).toBe('/w/10/design/20')
  })
})

/** 反向定位 / 高亮用大纲（ADR 0103 C1② / C7 / D9）：带 node_index 的 v5 快照 */
const INDEXED: DesignOutlineNode[] = [{
  kind: 'system',
  name: 'rover',
  line: 10,
  col: 1,
  node_index: 0,
  children: [
    {
      kind: 'assembly',
      name: 'chassis',
      line: 12,
      col: 3,
      node_index: 0,
      children: [{
        kind: 'group',
        op: 'difference',
        line: 13,
        col: 5,
        node_index: 0,
        children: [
          { kind: 'part', primitive: 'box', line: 14, col: 7, node_index: 0 },
          { kind: 'part', primitive: 'cyl', line: 15, col: 7, node_index: 0 },
        ],
      }],
    },
    { kind: 'part', primitive: 'sphere', line: 20, col: 3, node_index: 1 },
  ],
}]

describe('resolveOutlinePath（D9 归属规则）', () => {
  it('同父下取最后一个 line ≤ revealLine 的节点并逐层下探', () => {
    const path = resolveOutlinePath(INDEXED, 14, 20)
    expect(path.map(node => node.kind)).toEqual(['system', 'assembly', 'group', 'part'])
    expect(path[path.length - 1]).toMatchObject({ line: 14, primitive: 'box' })
  })

  it('命中父节点行时保持在该父层（子节点行更晚）', () => {
    const path = resolveOutlinePath(INDEXED, 12, 20)
    expect(path.map(node => (node.kind === 'part'
      ? node.primitive
      : node.kind === 'group'
        ? node.op
        : node.name))).toEqual(['rover', 'chassis'])
  })

  it('行号落在两个顶层实例之间时取前一个', () => {
    const path = resolveOutlinePath(INDEXED, 18, 20)
    expect(path.map(node => node.kind)).toEqual(['system', 'assembly', 'group', 'part'])
  })

  it('早于首行不选中（返回空路径）', () => {
    expect(resolveOutlinePath(INDEXED, 1, 20)).toEqual([])
  })

  it('module 行号倒挂：实例调用行晚于零件声明行时仍能命中零件（C1② 实际口径）', () => {
    // plate 在 10 行被调用，其组 / 零件声明在第 3–6 行；revealLine=4（侧栏点击「零件 · 第 4 行」）
    const nodes: DesignOutlineNode[] = [{
      kind: 'assembly',
      name: 'plate',
      line: 10,
      col: 1,
      node_index: 0,
      children: [{
        kind: 'group',
        op: 'difference',
        line: 3,
        col: 3,
        node_index: 0,
        children: [
          { kind: 'part', primitive: 'box', line: 4, col: 5, node_index: 0 },
          { kind: 'part', primitive: 'cyl', line: 6, col: 7, node_index: 0 },
        ],
      }],
    }]
    const path = resolveOutlinePath(nodes, 4, 20)
    expect(path.map(node => node.kind)).toEqual(['assembly', 'group', 'part'])
    expect(path[path.length - 1]).toMatchObject({ line: 4 })
  })

  it('忽略其他文件的节点（use 子树的 line 属于被引用文件）', () => {
    const nodes: DesignOutlineNode[] = [{
      kind: 'assembly',
      name: 'chassis',
      line: 3,
      col: 1,
      file_id: 30,
      node_index: 0,
      children: [{ kind: 'part', primitive: 'box', line: 1, col: 1, node_index: 0 }],
    }]
    expect(resolveOutlinePath(nodes, 5, 20)).toEqual([])
  })
})

describe('collectNodeIndices / outlineKeyPath', () => {
  it('选中节点收集自身子树下标（去重，布尔块共享同一块下标）', () => {
    const [system] = INDEXED
    expect(collectNodeIndices(system!)).toEqual([0, 1])
    // 布尔分组：组与其下两个零件共享块下标 0 → 去重后只有一个
    const assembly = (system as { children: DesignOutlineNode[] }).children[0]!
    const group = (assembly as { children: DesignOutlineNode[] }).children[0]!
    expect(collectNodeIndices(group)).toEqual([0])
  })

  it('v4 旧快照无 node_index：收集结果为空（静默降级）', () => {
    expect(collectNodeIndices(OUTLINE[0]!)).toEqual([])
  })

  it('key 路径与 outlineToTree 口径一致（末项为选中节点）', () => {
    const path = resolveOutlinePath(INDEXED, 14, 20)
    expect(outlineKeyPath(INDEXED, path, 20)).toEqual([
      'design-20-0',
      'design-20-0-0',
      'design-20-0-0-0',
      'design-20-0-0-0-0',
    ])
  })

  it('空路径返回空 key 列表', () => {
    expect(outlineKeyPath(INDEXED, [], 20)).toEqual([])
  })
})
