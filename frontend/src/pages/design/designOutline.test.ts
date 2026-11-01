/** 设计结构树映射单测（ADR 0083 D3 / D4 / D7）：标签 / 图标语义 / 源行 / 计数 / 空大纲. */

import { describe, expect, it } from 'vitest'
import type { DesignOutlineNode } from '@/api'
import {
  countParts, designEditorPath, groupLabel, outlineToTree, primitiveLabel,
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
