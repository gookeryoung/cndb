/** WBS（Work Breakdown Structure）工作分解结构视图组件 — 树状层级任务分解.
 *
 * view_options 配置字段（由 WBS_OPTIONS schema 定义）:
 * - parent_field:      父任务关联字段（link/text/number，必填）
 * - title_field:       任务名称（可选，自动推断）
 * - progress_field:    进度百分比 0-100（可选，父节点自动汇总）
 * - status_field:      状态字段（select，可选）
 * - assignee_field:    负责人（可选）
 * - start_date_field:  开始日期（可选，显示时间跨度）
 * - end_date_field:    结束日期（可选，配合开始日期）
 * - show_numbering:    显示层级编号 1 / 1.1 / 1.1.1（默认 true）
 * - expand_all:        默认全部展开（默认 false，只展开第一层）
 */

import { useEffect, useMemo, useState } from 'react'
import { Empty, Tag } from 'antd'
import { DownOutlined, RightOutlined, PartitionOutlined } from '@ant-design/icons'
import type { RowResponse, Field, View } from '@/api'
import type { Density } from '@/theme/tableSettings'
import { resolveOpts, WBS_OPTIONS, resolveAutoField, findOptionSchema } from './viewOptionSchema'
import { formatFieldDisplayValue, getSelectLabel } from './fieldValueFormat'

// ── 类型定义 ──────────────────────────────────────────

interface WbsViewProps {
  rows: RowResponse[]
  fields: Field[]
  view?: View | null
  density: Density
  onRowClick?: (r: RowResponse) => void
}

interface WbsNode {
  row: RowResponse
  id: string
  parentId: string | null
  children: WbsNode[]
  depth: number
  numbering: string
  computedProgress: number | null  // 实际进度（有值用自己，无值用子节点平均）
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

/** 从 rows 构建 WbsNode 树.
 *  - 按 parent_field 分组后递归
 *  - 循环引用检测（visited Set）
 *  - 父节点无 progress 时自动用子节点平均汇总
 *  - 兄弟顺序按 rows 原始顺序保持 */
function buildTree(
  rows: RowResponse[],
  parentField: string,
  progressField?: string,
): { roots: WbsNode[]; totalNodeCount: number } {
  const rowMap = new Map<string, RowResponse>()
  const childrenMap = new Map<string, RowResponse[]>()

  // 0. 建 业务值 → rowId 反向映射（用于把 parentValue 转成 parent row.id）
  //    遍历每行所有 string 值（排除 id 和 parentField 本身），任一值都可能是别人引用的业务 ID
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

  // 1. 建 rowMap + 按 parent rowId 分组（不是业务值）
  for (const row of rows) {
    const rid = rowIdKey(row)
    rowMap.set(rid, row)
    const parentValue = extractParentId(row, parentField)
    // 把 parentValue（业务值）转成 parent rowId（数据库主键）
    let parentRowId: string | null = null
    if (parentValue && valueToRowId.has(parentValue)) {
      parentRowId = valueToRowId.get(parentValue)!
    }
    const key = parentRowId ?? '__root__'
    const bucket = childrenMap.get(key) || []
    bucket.push(row)
    childrenMap.set(key, bucket)
  }

  // 2. 识别根节点：parent_field 为空，或 parent 指向不存在的行
  const allIds = new Set<string>(rowMap.keys())
  const rootRows: RowResponse[] = []
  for (const row of rows) {
    const parentValue = extractParentId(row, parentField)
    let parentRowId: string | null = null
    if (parentValue && valueToRowId.has(parentValue)) {
      parentRowId = valueToRowId.get(parentValue)!
    }
    if (!parentValue || !parentRowId || !allIds.has(parentRowId)) {
      rootRows.push(row)
    }
  }
  // 保持原始顺序
  rootRows.sort((a, b) => rows.indexOf(a) - rows.indexOf(b))

  // 3. 递归构建（含循环检测）
  let nodeCounter = 0
  function buildNode(
    row: RowResponse,
    depth: number,
    numbering: string,
    visited: Set<string>,
  ): WbsNode {
    const id = rowIdKey(row)
    nodeCounter++

    // 拿子行（从 childrenMap，保持 rows 里的原始顺序）
    const childRows = childrenMap.get(id) || []
    const orderedChildren = [...childRows].sort((a, b) => rows.indexOf(a) - rows.indexOf(b))

    // 循环防御：如果 id 已在 visited 里，标记为 orphan 不递归
    if (visited.has(id)) {
      console.warn(`[WBS] 检测到循环引用，节点 id=${id} 已出现过，跳过子树`)
      return {
        row,
        id,
        parentId: extractParentId(row, parentField),
        children: [],
        depth,
        numbering,
        computedProgress: extractProgress(row, progressField),
        hasChildren: false,
      }
    }
    visited.add(id)

    const children: WbsNode[] = orderedChildren.map((childRow, idx) =>
      buildNode(childRow, depth + 1, `${numbering}.${idx + 1}`, visited),
    )

    // 汇总进度
    const ownProgress = extractProgress(row, progressField)
    let computedProgress: number | null = ownProgress
    if (computedProgress === null && children.length > 0) {
      // 子节点有真实进度才参与平均
      const valid = children
        .map(c => c.computedProgress)
        .filter((p): p is number => p !== null)
      if (valid.length > 0) {
        computedProgress = Math.round(valid.reduce((a, b) => a + b, 0) / valid.length)
      }
    }

    return {
      row,
      id,
      parentId: extractParentId(row, parentField),
      children,
      depth,
      numbering,
      computedProgress,
      hasChildren: children.length > 0,
    }
  }

  const roots: WbsNode[] = rootRows.map((row, idx) =>
    buildNode(row, 0, String(idx + 1), new Set()),
  )

  return { roots, totalNodeCount: nodeCounter }
}

/** 从 row 中提取进度值（0-100）. 无法解析时返回 null. */
function extractProgress(row: RowResponse, progressField?: string): number | null {
  if (!progressField) return null
  const v = (row as Record<string, unknown>)[progressField]
  if (v === undefined || v === null || v === '') return null
  const n = Number(v)
  if (Number.isNaN(n)) return null
  // 如果是 0-1 浮点数，乘 100
  if (n <= 1 && n > 0) return Math.round(n * 100)
  // 如果是百分比字符串 "50%"
  if (typeof v === 'string' && v.includes('%')) {
    const num = Number(v.replace('%', ''))
    return Number.isNaN(num) ? null : Math.round(num)
  }
  return Math.round(n)
}

// ── 颜色工具 ──────────────────────────────────────────

const STATUS_PALETTE = [
  'blue', 'green', 'orange', 'purple', 'cyan', 'magenta', 'gold', 'geekblue',
]

function statusColor(value: string | undefined): string {
  if (!value) return 'default'
  let h = 0
  for (let i = 0; i < value.length; i++) h = (h * 31 + value.charCodeAt(i)) & 0x7fffffff
  return STATUS_PALETTE[h % STATUS_PALETTE.length]
}

// ── 主组件 ────────────────────────────────────────────

export default function WbsView({
  rows,
  fields,
  view,
  density,
  onRowClick,
}: WbsViewProps) {
  const opts = useMemo(
    () => resolveOpts(view?.view_options as Record<string, unknown> | undefined, WBS_OPTIONS),
    [view?.view_options],
  )
  const ds = densityStyle(density)

  // 从配置拿字段名；缺失则自动推断
  const parentField = opts.parent_field as string | undefined
  const titleField = useMemo(() => {
    const configured = opts.title_field as string | undefined
    if (configured) return configured
    const schema = findOptionSchema('wbs', 'title_field')
    return resolveAutoField(fields, schema)
  }, [opts.title_field, fields])
  const progressField = opts.progress_field as string | undefined
  const statusField = opts.status_field as string | undefined
  const assigneeField = opts.assignee_field as string | undefined
  const startField = opts.start_date_field as string | undefined
  const endField = opts.end_date_field as string | undefined
  const showNumbering = opts.show_numbering !== false  // default true
  const expandAll = opts.expand_all === true            // default false

  // 构建树
  const { roots, totalNodeCount } = useMemo(
    () => {
      if (!parentField) return { roots: [] as WbsNode[], totalNodeCount: 0 }
      return buildTree(rows, parentField, progressField)
    },
    [rows, parentField, progressField],
  )

  // 收集所有节点 ID（expandAll 用）
  const allNodeIds = useMemo(() => {
    const ids: string[] = []
    function walk(nodes: WbsNode[]) {
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

  // 预查 Field 定义（减少 renderNode 内部重复查找）—— 必须在所有 early return 之前
  const assigneeFieldDef = useMemo(
    () => fields.find(f => f.name === assigneeField),
    [fields, assigneeField],
  )
  const startFieldDef = useMemo(
    () => fields.find(f => f.name === startField),
    [fields, startField],
  )
  const endFieldDef = useMemo(
    () => fields.find(f => f.name === endField),
    [fields, endField],
  )

  // ── 空态判断 ──
  if (!parentField) {
    return (
      <div style={{ padding: 24 }}>
        <Empty description="WBS 视图需要配置 parent_field（父任务字段）才能构建层级树" />
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
  if (roots.length === 0 && totalNodeCount === 0) {
    return (
      <div style={{ padding: 24 }}>
        <Empty description="请在视图设置中检查 parent_field 是否正确指向存储父任务关联的字段" />
      </div>
    )
  }
  // 有 rows 但无法构成树（可能所有 parent 指向不存在的行）
  if (roots.length === 0) {
    return (
      <div style={{ padding: 24 }}>
        <Empty description="当前数据无法构建 WBS 树：请检查父任务字段的赋值是否正确" />
      </div>
    )
  }

  // ── 渲染行 ──
  const renderNode = (node: WbsNode): React.ReactNode[] => {
    const rows: React.ReactNode[] = []

    const title = titleField
      ? String((node.row as Record<string, unknown>)[titleField] ?? node.id)
      : String(node.id)
    const statusFieldDef = statusField
      ? fields.find(f => f.name === statusField)
      : undefined
    const statusValue = statusField && statusFieldDef
      ? getSelectLabel(statusFieldDef, (node.row as Record<string, unknown>)[statusField])
      : undefined
    const assigneeValue = assigneeFieldDef
      ? formatFieldDisplayValue(assigneeFieldDef, (node.row as Record<string, unknown>)[assigneeField!])
      : undefined
    const startValue = startFieldDef
      ? formatFieldDisplayValue(startFieldDef, (node.row as Record<string, unknown>)[startField!])
      : undefined
    const endValue = endFieldDef
      ? formatFieldDisplayValue(endFieldDef, (node.row as Record<string, unknown>)[endField!])
      : undefined
    const progress = node.computedProgress

    const indent = node.depth * ds.indentUnit
    const isExpanded = expanded.has(node.id)

    rows.push(
      <div
        key={node.id}
        data-testid="wbs-node"
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
        {/* 折叠/展开三角占位 */}
        <span
          data-testid={node.hasChildren ? 'wbs-toggle' : undefined}
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

        {/* 层级编号 */}
        {showNumbering && (
          <span
            style={{
              color: 'var(--cn-text-muted)',
              fontSize: ds.metaFontSize,
              marginRight: 6,
              fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace',
              flexShrink: 0,
              minWidth: node.depth > 0 ? 28 : 16,
            }}
          >
            {node.numbering}.
          </span>
        )}

        {/* 任务标题 */}
        <span
          style={{
            fontWeight: node.hasChildren ? 600 : 400,
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

          {/* 日期区间 */}
          {(startValue || endValue) && (
            <span style={{ color: 'var(--cn-text-muted)' }}>
              {startValue || '...'} — {endValue || '...'}
            </span>
          )}

          {/* 进度条 */}
          {progress !== null && (
            <div style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 4,
              marginLeft: 4,
            }}>
              <div style={{
                width: 60,
                height: 6,
                background: 'var(--cn-border)',
                borderRadius: 3,
                overflow: 'hidden',
              }}>
                <div style={{
                  width: `${Math.max(0, Math.min(100, progress))}%`,
                  height: '100%',
                  background: node.hasChildren ? 'var(--cn-brand-color-light, #91caff)' : 'var(--cn-brand-color, #1677ff)',
                  borderRadius: 3,
                  transition: 'width 0.2s',
                }} />
              </div>
              <span style={{
                color: node.hasChildren ? 'var(--cn-text-secondary)' : 'var(--cn-text-primary)',
                minWidth: 28,
                textAlign: 'right',
              }}>
                {progress}%
              </span>
            </div>
          )}
        </div>
      </div>,
    )

    // 递归子节点（如果展开了）
    if (node.hasChildren && isExpanded) {
      for (const child of node.children) {
        rows.push(...renderNode(child))
      }
    }

    return rows
  }

  const allRows: React.ReactNode[] = []
  for (const root of roots) {
    allRows.push(...renderNode(root))
  }

  return (
    <div data-testid="wbs-view" style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
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
        <div style={{ fontWeight: 600, fontSize: ds.titleFontSize + 1, display: 'flex', alignItems: 'center', gap: 6 }}>
          <PartitionOutlined style={{ color: 'var(--cn-brand-color)' }} />
          WBS 工作分解结构
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
