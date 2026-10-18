/** 文档树排序（docTreeSort）单测 — 覆盖文件夹优先、置顶优先、三种字段升降序、递归与本地持久化 */
import { beforeEach, describe, expect, it } from 'vitest'
import {
  DEFAULT_DOC_SORT,
  DOC_SORT_STORAGE_KEY,
  describeSort,
  readDocSort,
  sortDocTree,
  sortToValue,
  valueToSort,
  writeDocSort,
} from './docTreeSort'
import type { DocSort, SortableDocNode } from './docTreeSort'

let nextId = 1

function node(partial: Partial<SortableDocNode> & { title: string }): SortableDocNode {
  return {
    id: nextId++,
    is_folder: false,
    pinned: false,
    created_at: '2026-01-01T00:00:00',
    updated_at: '2026-01-01T00:00:00',
    children: [],
    ...partial,
  }
}

const titles = (nodes: SortableDocNode[]) => nodes.map(n => n.title)

const ASC_NAME: DocSort = { key: 'name', order: 'asc' }
const DESC_NAME: DocSort = { key: 'name', order: 'desc' }

describe('sortDocTree', () => {
  beforeEach(() => {
    nextId = 1
  })

  it('manual 档原样返回（不重排、不递归拷贝）', () => {
    const nodes = [node({ title: 'b' }), node({ title: 'a' })]
    expect(sortDocTree(nodes, { key: 'manual', order: 'asc' })).toBe(nodes)
  })

  it('名称升序：中文按拼音、数字感知（项目2 在 项目10 之前）', () => {
    const nodes = [node({ title: '项目10' }), node({ title: '项目2' }), node({ title: '文档' })]
    // 拼音：文档(wen…) 在 项目(xiang…) 之前
    expect(titles(sortDocTree(nodes, ASC_NAME))).toEqual(['文档', '项目2', '项目10'])
  })

  it('名称降序', () => {
    const nodes = [node({ title: 'a' }), node({ title: 'b' }), node({ title: 'c' })]
    expect(titles(sortDocTree(nodes, DESC_NAME))).toEqual(['c', 'b', 'a'])
  })

  it('文件夹恒在文件之前（升降序都不反转）', () => {
    const nodes = [
      node({ title: 'z-doc' }),
      node({ title: 'a-folder', is_folder: true }),
      node({ title: 'b-doc' }),
    ]
    expect(titles(sortDocTree(nodes, ASC_NAME))).toEqual(['a-folder', 'b-doc', 'z-doc'])
    expect(titles(sortDocTree(nodes, DESC_NAME))).toEqual(['a-folder', 'z-doc', 'b-doc'])
  })

  it('置顶优先级高于文件夹优先', () => {
    const nodes = [
      node({ title: 'a-folder', is_folder: true }),
      node({ title: 'z-pinned', pinned: true }),
    ]
    expect(titles(sortDocTree(nodes, ASC_NAME))).toEqual(['z-pinned', 'a-folder'])
  })

  it('创建时间升序 / 降序', () => {
    const nodes = [
      node({ title: 'mid', created_at: '2026-03-01T00:00:00' }),
      node({ title: 'old', created_at: '2025-01-01T00:00:00' }),
      node({ title: 'new', created_at: '2026-09-01T00:00:00' }),
    ]
    expect(titles(sortDocTree(nodes, { key: 'created_at', order: 'asc' }))).toEqual(['old', 'mid', 'new'])
    expect(titles(sortDocTree(nodes, { key: 'created_at', order: 'desc' }))).toEqual(['new', 'mid', 'old'])
  })

  it('修改时间升序 / 降序', () => {
    const nodes = [
      node({ title: 'a', updated_at: '2026-05-01T00:00:00' }),
      node({ title: 'b', updated_at: '2026-09-01T00:00:00' }),
    ]
    expect(titles(sortDocTree(nodes, { key: 'updated_at', order: 'asc' }))).toEqual(['a', 'b'])
    expect(titles(sortDocTree(nodes, { key: 'updated_at', order: 'desc' }))).toEqual(['b', 'a'])
  })

  it('时间相同按 id 升序兜底（结果稳定）', () => {
    const a = node({ title: 'first' })
    const b = node({ title: 'second' })
    expect(titles(sortDocTree([b, a], { key: 'updated_at', order: 'desc' }))).toEqual(['first', 'second'])
  })

  it('非法时间按 0 处理，不抛错', () => {
    const nodes = [
      node({ title: 'bad', created_at: 'not-a-date' }),
      node({ title: 'ok', created_at: '2026-01-01T00:00:00' }),
    ]
    expect(titles(sortDocTree(nodes, { key: 'created_at', order: 'asc' }))).toEqual(['bad', 'ok'])
  })

  it('递归：每个文件夹内部同样排序', () => {
    const tree = [
      node({
        title: 'folder',
        is_folder: true,
        children: [node({ title: 'b' }), node({ title: 'a' })],
      }),
    ]
    const [folder] = sortDocTree(tree, ASC_NAME)
    expect(titles(folder.children)).toEqual(['a', 'b'])
  })

  it('不修改入参（返回新数组）', () => {
    const nodes = [node({ title: 'b' }), node({ title: 'a' })]
    const sorted = sortDocTree(nodes, ASC_NAME)
    expect(sorted).not.toBe(nodes)
    expect(titles(nodes)).toEqual(['b', 'a'])
  })
})

describe('排序偏好的序列化与本地持久化', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('排序配置与菜单 key 互转', () => {
    expect(sortToValue({ key: 'manual', order: 'asc' })).toBe('manual')
    expect(sortToValue({ key: 'created_at', order: 'desc' })).toBe('created-desc')
    expect(valueToSort('updated-asc')).toEqual({ key: 'updated_at', order: 'asc' })
    expect(describeSort({ key: 'name', order: 'desc' })).toBe('名称 Z → A')
  })

  it('非法 key 回落默认', () => {
    expect(valueToSort('nope')).toBe(DEFAULT_DOC_SORT)
    expect(valueToSort('nope')).toEqual({ key: 'manual', order: 'asc' })
  })

  it('写入后可读回；缺省时读默认', () => {
    expect(readDocSort()).toEqual(DEFAULT_DOC_SORT)
    writeDocSort({ key: 'updated_at', order: 'desc' })
    expect(localStorage.getItem(DOC_SORT_STORAGE_KEY)).toBe('updated-desc')
    expect(readDocSort()).toEqual({ key: 'updated_at', order: 'desc' })
  })

  it('存了非法值时读回默认', () => {
    localStorage.setItem(DOC_SORT_STORAGE_KEY, 'garbage')
    expect(readDocSort()).toEqual(DEFAULT_DOC_SORT)
  })
})
