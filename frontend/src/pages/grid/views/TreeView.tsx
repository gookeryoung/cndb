/** Tree（树）通用层级视图组件 — 按父节点字段把行组织为可折叠树.
 *
 * 与 WBS 工作分解视图的区别：Tree 是通用层级浏览器，不内置编号语义（编号默认关闭，
 * 可开启）、不做进度汇总，聚焦「按父子关系浏览任意自引用数据」（如目录、分类、组织架构）；
 * WBS 则面向项目任务分解，默认显示层级编号并按子节点汇总进度。
 *
 * view_options 配置字段（由 TREE_OPTIONS schema 定义）:
 * - parent_field:    父节点关联字段（link/text/number，必填）
 * - title_field:     节点标题（可选，自动推断）
 * - status_field:    状态字段（select，可选，显示为徽章）
 * - assignee_field:  负责人（可选）
 * - show_numbering:  显示层级编号 1 / 1.1 / 1.1.1（默认 false）
 * - expand_all:      默认全部展开（默认 true，树浏览器语义）
 */

import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { Empty, Tag } from 'antd'
import { DownOutlined, RightOutlined, ApartmentOutlined } from '@ant-design/icons'
import type { RowResponse, Field, View } from '@/api'
import type { Density } from '@/theme/tableSettings'
import { resolveOpts, TREE_OPTIONS, resolveAutoField, findOptionSchema } from '../view-config/viewOptionSchema'
import { formatFieldDisplayValue, getSelectLabel } from '../cells/fieldValueFormat'
import { pickPaletteColor } from '@/utils/paletteColor'
import { WEIGHT } from '@/theme/tokens'

// ── 类型定义 ──────────────────────────────────────────

interface TreeViewProps {
  rows: RowResponse[]
  fields: Field[]
  view?: View | null
  density: Density
  onRowClick?: (r: RowResponse) => void
}

interface TreeNode {
  row: RowResponse
  id: string
  parentId: string | null
  children: TreeNode[]
  depth: number
  numbering: string
  hasChildren: boolean
}

// ── 密度样式 ──────────────────────────────────────────

function densityStyle(density: Density) {
  if (density === 'compact') {
    return { rowHeight: 30, indentUnit: 16, titleFontSize: 12, metaFontSize: 10 }
  }
  if (density === 'spacious') {
    return { rowHeight: 48, indentUnit: 24, titleFontSize: 14, metaFontSize: 12 }
  }
  return { rowHeight: 38, indentUnit: 20, titleFontSize: 13, metaFontSize: 11 }
}

// ── 父 ID 解析 ────────────────────────────────────────

/** 从一行记录里提取 parent_field 的值，归一化为字符串（link/text/number 兼容）.
 *  返回 null 表示无父. */
function extractParentId(row: RowResponse, parentField: string): string | null {
  const raw = (row as Record<string, unknown>)[parentField]
  if (raw === undefined || raw === null || raw === '') return null

  // link 字段：API 返回 [{id, value}] 数组或对象
  if (Array.isArray(raw)) {
    if (raw.length === 0) return null
    const first = raw[0] as Record<string, unknown>
    if (first && typeof first === 'object') {
      return String(first.id ?? first.value ?? '') || null
    }
    return String(first) || null
  }
  if (raw && typeof raw === 'object') {
    const o = raw as Record<string, unknown>
    return String(o.id ?? o.value ?? '') || null
  }

  const str = String(raw)
  if (str === 'null' || str === 'undefined') return null
  return str
}

/** 把一行的主键 ID 归一化为字符串键（用于 Map 查找） */
function rowIdKey(row: RowResponse): string {
  return String(row.id)
}

// ── 树构建 ────────────────────────────────────────────

/** 从 rows 构建 TreeNode 树.
 *  - 按 parent_field 分组后递归（主键直配优先，业务值反查兜底）
 *  - 循环引用检测（visited Set）
 *  - 兄弟顺序按 rows 原始顺序保持 */
function buildTree(
  rows: RowResponse[],
  parentField: string,
): { roots: TreeNode[]; totalNodeCount: number } {
  const rowMap = new Map<string, RowResponse>()
  const childrenMap = new Map<string, RowResponse[]>()

  // 0. 建 业务值 → rowId 反向映射（用于把 parentValue 转成 parent row.id）
  const valueToRowId = new Map<string, string>()
  for (const row of rows) {
    const rid = rowIdKey(row)
    for (const [k, v] of Object.entries(row)) {
      if (k === 'id') continue
      if (k === parentField) continue
      if (typeof v === 'string' && v.length > 0 && v.length < 100) {
        valueToRowId.set(v, rid)
      }
    }
  }

  // 1. 建 rowMap 与全部主键集合（parentValue 命中主键时可直接作为父行）
  for (const row of rows) rowMap.set(rowIdKey(row), row)
  const allIds = new Set<string>(rowMap.keys())

  /** 把 parentValue 归一化为父行主键：主键直配优先，业务值反查兜底 */
  const resolveParentRowId = (row: RowResponse): string | null => {
    const parentValue = extractParentId(row, parentField)
    if (!parentValue) return null
    if (allIds.has(parentValue)) return parentValue
    return valueToRowId.get(parentValue) ?? null
  }

  // 2. 按 parent rowId 分组（不是业务值）
  for (const row of rows) {
    const key = resolveParentRowId(row) ?? '__root__'
    const bucket = childrenMap.get(key) || []
    bucket.push(row)
    childrenMap.set(key, bucket)
  }

  // 3. 识别根节点：parent_field 为空，或 parent 指向不存在的行
  const rootRows: RowResponse[] = []
  for (const row of rows) {
    const parentValue = extractParentId(row, parentField)
    const parentRowId = resolveParentRowId(row)
    if (!parentValue || !parentRowId || !allIds.has(parentRowId)) {
      rootRows.push(row)
    }
  }
  rootRows.sort((a, b) => rows.indexOf(a) - rows.indexOf(b))

  // 4. 递归构建（含循环检测）
  let nodeCounter = 0
  function buildNode(
    row: RowResponse,
    depth: number,
    numbering: string,
    visited: Set<string>,
  ): TreeNode {
    const id = rowIdKey(row)
    nodeCounter++

    const childRows = childrenMap.get(id) || []
    const orderedChildren = [...childRows].sort((a, b) => rows.indexOf(a) - rows.indexOf(b))

    // 循环防御：如果 id 已在 visited 里，标记为 orphan 不递归
    if (visited.has(id)) {
      console.warn(`[Tree] 检测到循环引用，节点 id=${id} 已出现过，跳过子树`)
      return {
        row,
        id,
        parentId: extractParentId(row, parentField),
        children: [],
        depth,
        numbering,
        hasChildren: false,
      }
    }
    visited.add(id)

    const children: TreeNode[] = orderedChildren.map((childRow, idx) =>
      buildNode(childRow, depth + 1, `${numbering}.${idx + 1}`, visited),
    )

    return {
      row,
      id,
      parentId: extractParentId(row, parentField),
      children,
      depth,
      numbering,
      hasChildren: children.length > 0,
    }
  }

  const roots: TreeNode[] = rootRows.map((row, idx) =>
    buildNode(row, 0, String(idx + 1), new Set()),
  )

  return { roots, totalNodeCount: nodeCounter }
}

// ── 颜色工具 ──────────────────────────────────────────

const STATUS_PALETTE = [
  'blue', 'green', 'orange', 'purple', 'cyan', 'magenta', 'gold', 'geekblue',
]

function statusColor(value: string | undefined): string {
  if (!value) return 'default'
  return pickPaletteColor(value, STATUS_PALETTE)
}

// ── 主组件 ────────────────────────────────────────────

export default function TreeView({
  rows,
  fields,
  view,
  density,
  onRowClick,
}: TreeViewProps) {
  const opts = useMemo(
    () => resolveOpts(view?.view_options as Record<string, unknown> | undefined, TREE_OPTIONS),
    [view?.view_options],
  )
  const ds = densityStyle(density)

  // 从配置拿字段名；缺失则自动推断
  const parentField = opts.parent_field as string | undefined
  const titleField = useMemo(() => {
    const configured = opts.title_field as string | undefined
    if (configured) return configured
    const schema = findOptionSchema('tree', 'title_field')
    return resolveAutoField(fields, schema)
  }, [opts.title_field, fields])
  const statusField = opts.status_field as string | undefined
  const assigneeField = opts.assignee_field as string | undefined
  const showNumbering = opts.show_numbering === true   // default false
  const expandAll = opts.expand_all !== false           // default true

  // 构建树
  const { roots, totalNodeCount } = useMemo(
    () => {
      if (!parentField) return { roots: [] as TreeNode[], totalNodeCount: 0 }
      return buildTree(rows, parentField)
    },
    [rows, parentField],
  )

  // 收集所有节点 ID（expandAll 用）
  const allNodeIds = useMemo(() => {
    const ids: string[] = []
    function walk(nodes: TreeNode[]) {
      for (const n of nodes) {
        ids.push(n.id)
        if (n.hasChildren) walk(n.children)
      }
    }
    walk(roots)
    return ids
  }, [roots])

  // 折叠状态：Set 包含"已展开"的节点 ID
  const [expanded, setExpanded] = useState<Set<string>>(() => {
    if (expandAll) return new Set(allNodeIds)
    return new Set(roots.map(r => r.id))
  })

  // 当 rows 或配置变化时，重置展开状态
  useEffect(() => {
    if (expandAll) {
      setExpanded(new Set(allNodeIds))
    } else {
      setExpanded(new Set(roots.map(r => r.id)))
    }
  }, [rows, parentField, expandAll, allNodeIds, roots])

  const toggleExpand = (id: string) => {
    setExpanded(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  // 预查 Field 定义（减少 renderNode 内部重复查找）
  const statusFieldDef = useMemo(
    () => fields.find(f => f.name === statusField),
    [fields, statusField],
  )
  const assigneeFieldDef = useMemo(
    () => fields.find(f => f.name === assigneeField),
    [fields, assigneeField],
  )

  // ── 空态判断 ──
  if (!parentField) {
    return (
      <div style={{ padding: 24 }}>
        <Empty description="树视图需要配置父节点关联字段（视图设置里的「父节点字段」）才能构建层级树" />
      </div>
    )
  }
  if (rows.length === 0) {
    return (
      <div style={{ padding: 24 }}>
        <Empty description="暂无数据" />
      </div>
    )
  }
  if (roots.length === 0 || totalNodeCount === 0) {
    return (
      <div style={{ padding: 24 }}>
        <Empty description="当前数据无法构建层级树：请检查父节点字段的赋值是否正确" />
      </div>
    )
  }

  // ── 渲染行 ──
  const renderNode = (node: TreeNode): ReactNode[] => {
    const out: ReactNode[] = []

    const title = titleField
      ? String((node.row as Record<string, unknown>)[titleField] ?? node.id)
      : String(node.id)
    const statusValue = statusFieldDef
      ? getSelectLabel(statusFieldDef, (node.row as Record<string, unknown>)[statusField!])
      : undefined
    const assigneeValue = assigneeFieldDef
      ? formatFieldDisplayValue(assigneeFieldDef, (node.row as Record<string, unknown>)[assigneeField!])
      : undefined

    const indent = node.depth * ds.indentUnit
    const isExpanded = expanded.has(node.id)

    out.push(
      <div
        key={node.id}
        data-testid="tree-node"
        style={{
          display: 'flex',
          alignItems: 'center',
          height: ds.rowHeight,
          paddingLeft: indent,
          borderBottom: '1px solid var(--cn-border)',
          cursor: 'pointer',
          fontSize: ds.titleFontSize,
          transition: 'background-color 0.15s',
          background: node.depth % 2 === 0 ? 'transparent' : 'rgba(0,0,0,0.015)',
        }}
        onClick={() => onRowClick?.(node.row)}
        onMouseEnter={e => { (e.currentTarget as HTMLDivElement).style.background = 'var(--cn-bg-hover, rgba(0,0,0,0.04))' }}
        onMouseLeave={e => {
          const el = e.currentTarget as HTMLDivElement
          el.style.background = node.depth % 2 === 0 ? 'transparent' : 'rgba(0,0,0,0.015)'
        }}
      >
        {/* 折叠/展开三角 */}
        <span
          data-testid={node.hasChildren ? 'tree-toggle' : undefined}
          onClick={(e) => { e.stopPropagation(); toggleExpand(node.id) }}
          style={{
            width: 16,
            height: ds.rowHeight,
            display: 'inline-flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: node.hasChildren ? 'var(--cn-text-muted)' : 'transparent',
            cursor: node.hasChildren ? 'pointer' : 'default',
            flexShrink: 0,
            fontSize: ds.metaFontSize,
          }}
        >
          {node.hasChildren ? (isExpanded ? <DownOutlined /> : <RightOutlined />) : <RightOutlined />}
        </span>

        {/* 层级编号（可选） */}
        {showNumbering && (
          <span
            style={{
              color: 'var(--cn-text-muted)',
              fontSize: ds.metaFontSize,
              marginRight: 6,
              fontFamily: 'var(--cn-font-mono)',
              flexShrink: 0,
              minWidth: node.depth > 0 ? 28 : 16,
            }}
          >
            {node.numbering}.
          </span>
        )}

        {/* 节点标题 */}
        <span
          style={{
            fontWeight: node.hasChildren ? WEIGHT.semibold : WEIGHT.regular,
            flex: 1,
            color: 'var(--cn-text-primary)',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }}
        >
          {title}
        </span>

        {/* 右侧徽章区 */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 6,
            marginLeft: 8,
            fontSize: ds.metaFontSize,
            flexShrink: 0,
          }}
        >
          {/* 子节点数量 */}
          {node.hasChildren && (
            <span style={{ color: 'var(--cn-text-muted)' }}>{node.children.length} 子项</span>
          )}

          {/* 状态徽章 */}
          {statusValue && (
            <Tag
              color={statusColor(statusValue)}
              style={{ margin: 0, fontSize: ds.metaFontSize, lineHeight: '14px' }}
            >
              {statusValue}
            </Tag>
          )}

          {/* 负责人 */}
          {assigneeValue && (
            <span style={{ color: 'var(--cn-text-muted)' }}>{assigneeValue}</span>
          )}
        </div>
      </div>,
    )

    // 递归子节点（如果展开了）
    if (node.hasChildren && isExpanded) {
      for (const child of node.children) {
        out.push(...renderNode(child))
      }
    }

    return out
  }

  const allRows: ReactNode[] = []
  for (const root of roots) {
    allRows.push(...renderNode(root))
  }

  return (
    <div data-testid="tree-view" style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      {/* 工具栏 */}
      <div
        style={{
          padding: '8px 12px',
          display: 'flex',
          alignItems: 'center',
          gap: 12,
          borderBottom: '1px solid var(--cn-border)',
          background: 'var(--cn-bg-container)',
        }}
      >
        <div style={{ fontWeight: WEIGHT.semibold, fontSize: ds.titleFontSize + 1, display: 'flex', alignItems: 'center', gap: 6 }}>
          <ApartmentOutlined style={{ color: 'var(--cn-brand-color)' }} />
          树视图
        </div>
        <Tag color="blue" style={{ margin: 0 }}>
          {totalNodeCount} 个节点 · {roots.length} 个根
        </Tag>
        <div style={{ flex: 1 }} />
        <span style={{ fontSize: ds.metaFontSize, color: 'var(--cn-text-muted)' }}>
          {expandAll ? '全部展开' : '点击三角展开/折叠'}
        </span>
      </div>

      {/* 树内容 */}
      <div
        style={{
          flex: 1,
          overflow: 'auto',
          background: 'var(--cn-bg-container)',
        }}
      >
        {allRows}
      </div>
    </div>
  )
}
