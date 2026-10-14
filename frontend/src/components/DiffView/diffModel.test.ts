/** diffModel 纯函数单测：unified diff 解析 / 并排配对 / 行内高亮 / 统计. */

import { describe, expect, it } from 'vitest'

import {
  buildSplitRows,
  diffStats,
  inlineSegments,
  pairInline,
  parseUnifiedDiff,
} from './diffModel'

const SAMPLE = [
  '--- base',
  '+++ head',
  '@@ -1,4 +1,4 @@',
  ' # 标题',
  '-分级：A',
  '+分级：B',
  ' 备注：老客户',
  '',
].join('\n')

describe('parseUnifiedDiff', () => {
  it('空文本返回空数组', () => {
    expect(parseUnifiedDiff('')).toEqual([])
  })

  it('解析文件头 / 区间头 / 增删 / 上下文，并给出双端行号', () => {
    const lines = parseUnifiedDiff(SAMPLE)

    expect(lines.map((l) => l.kind)).toEqual(['meta', 'meta', 'hunk', 'ctx', 'del', 'add', 'ctx'])
    expect(lines[0]).toMatchObject({ kind: 'meta', text: '--- base' })
    expect(lines[2]).toMatchObject({ kind: 'hunk', text: '@@ -1,4 +1,4 @@', oldNo: null, newNo: null })

    const ctxHead = lines[3]!
    expect(ctxHead).toMatchObject({ kind: 'ctx', text: '# 标题', oldNo: 1, newNo: 1 })

    const del = lines[4]!
    expect(del).toMatchObject({ kind: 'del', text: '分级：A', oldNo: 2, newNo: null })

    const add = lines[5]!
    expect(add).toMatchObject({ kind: 'add', text: '分级：B', oldNo: null, newNo: 2 })

    expect(lines[6]).toMatchObject({ kind: 'ctx', text: '备注：老客户', oldNo: 3, newNo: 3 })
  })

  it('缺尾换行不产生多余空行', () => {
    const lines = parseUnifiedDiff('@@ -1 +1 @@\n-a\n+b')
    expect(lines.map((l) => l.kind)).toEqual(['hunk', 'del', 'add'])
    expect(lines[2]!.text).toBe('b')
  })

  it('区间内的 \\ No newline at end of file 记为元信息', () => {
    const lines = parseUnifiedDiff('@@ -1 +1 @@\n-a\n\\ No newline at end of file\n+b\n\\ No newline at end of file\n')
    expect(lines.map((l) => l.kind)).toEqual(['hunk', 'del', 'meta', 'add', 'meta'])
    expect(lines[2]!.text).toContain('No newline')
  })

  it('多区间行号按各自起点重置', () => {
    const diff = ['@@ -1,1 +1,1 @@', ' a', '@@ -10,1 +12,1 @@', '-x', '+y'].join('\n')
    const lines = parseUnifiedDiff(diff)
    expect(lines[1]).toMatchObject({ kind: 'ctx', oldNo: 1, newNo: 1 })
    expect(lines[3]).toMatchObject({ kind: 'del', oldNo: 10 })
    expect(lines[4]).toMatchObject({ kind: 'add', newNo: 12 })
  })

  it('区间内以 -/+ 开头的正文仍按增删处理', () => {
    const lines = parseUnifiedDiff('@@ -1 +1 @@\n--- 分隔线\n+++ 分隔线\n')
    expect(lines[1]).toMatchObject({ kind: 'del', text: '-- 分隔线' })
    expect(lines[2]).toMatchObject({ kind: 'add', text: '++ 分隔线' })
  })
})

describe('inlineSegments', () => {
  it('两侧一致时无高亮片段', () => {
    const { left, right } = inlineSegments('同样内容', '同样内容')
    expect(left).toEqual([{ text: '同样内容', changed: false }])
    expect(right).toEqual([{ text: '同样内容', changed: false }])
  })

  it('只标出真正变化的 token', () => {
    const { left, right } = inlineSegments('分级：A', '分级：B')
    expect(left).toEqual([
      { text: '分级：', changed: false },
      { text: 'A', changed: true },
    ])
    expect(right).toEqual([
      { text: '分级：', changed: false },
      { text: 'B', changed: true },
    ])
  })

  it('一侧为空时整行标记为变化', () => {
    expect(inlineSegments('', '新增内容').left).toEqual([{ text: '', changed: true }])
  })

  it('超长文本退化为整行高亮（不进入 LCS）', () => {
    const oldText = 'a'.repeat(400)
    const newText = 'b'.repeat(400)
    expect(inlineSegments(oldText, newText).left).toEqual([{ text: oldText, changed: true }])
  })
})

describe('pairInline', () => {
  it('把相邻删除块与新增块逐行配对并写入行内高亮', () => {
    const lines = pairInline(parseUnifiedDiff(SAMPLE))
    const del = lines.find((l) => l.kind === 'del')!
    const add = lines.find((l) => l.kind === 'add')!

    expect(del.inline?.some((s) => s.changed && s.text === 'A')).toBe(true)
    expect(add.inline?.some((s) => s.changed && s.text === 'B')).toBe(true)
  })

  it('删除行多于新增行时，多出的删除行不配对（无 inline）', () => {
    const lines = pairInline(parseUnifiedDiff('@@ -1,2 +1,1 @@\n-a\n-b\n+c\n'))
    const dels = lines.filter((l) => l.kind === 'del')
    expect(dels[0]!.inline).toBeDefined()
    expect(dels[1]!.inline).toBeUndefined()
  })

  it('不修改入参数组', () => {
    const input = parseUnifiedDiff(SAMPLE)
    const snapshot = JSON.parse(JSON.stringify(input))
    pairInline(input)
    expect(input).toEqual(snapshot)
  })
})

describe('buildSplitRows', () => {
  it('上下文行左右镜像，增删配对为同一行', () => {
    const rows = buildSplitRows(pairInline(parseUnifiedDiff(SAMPLE)))
    expect(rows.map((r) => r.kind)).toEqual(['meta', 'meta', 'hunk', 'ctx', 'change', 'ctx'])

    const change = rows[4]!
    expect(change.left?.kind).toBe('del')
    expect(change.right?.kind).toBe('add')
    expect(rows[3]!.left).toBe(rows[3]!.right)
  })

  it('数量不等时缺失侧补 null 以保持行对齐', () => {
    const rows = buildSplitRows(parseUnifiedDiff('@@ -1,2 +1,1 @@\n-a\n-b\n+c\n'))
    // 区间头单独成行，其余为两行配对结果
    expect(rows.map((r) => r.kind)).toEqual(['hunk', 'change', 'change'])
    expect(rows[1]).toMatchObject({ left: { kind: 'del' }, right: { kind: 'add' } })
    expect(rows[2]!.left?.kind).toBe('del')
    expect(rows[2]!.right).toBeNull()
  })

  it('孤立新增行左侧为 null', () => {
    const rows = buildSplitRows(parseUnifiedDiff('@@ -1,1 +1,2 @@\n a\n+b\n'))
    expect(rows[2]).toMatchObject({ left: null, right: { kind: 'add' } })
  })
})

describe('diffStats', () => {
  it('只统计增删行，不计文件头与区间头', () => {
    expect(diffStats(parseUnifiedDiff(SAMPLE))).toEqual({ added: 1, removed: 1 })
    expect(diffStats([])).toEqual({ added: 0, removed: 0 })
  })
})
