/** 流程（Flow）视图组件 — 按流程节点字段把记录平铺为横向流转管线.
 *
 * 视觉：节点卡片按「流程顺序」横向平铺（左→右），相邻节点之间用带箭头 + 流入量的连接线
 * 串联，直观表达「从节点到节点」的流转关系；每个节点卡片内列出归属该节点的记录卡片。
 *
 * view_options 配置字段（由 FLOW_OPTIONS schema 定义）:
 * - node_field:   流程节点字段（必填）
 * - title_field:  节点卡片标题字段（可选，自动推断为第一个文本字段）
 * - node_order:   节点顺序（可选 string[]，缺省按节点字段选项 / 数据首次出现顺序）
 *
 * 配色对齐其他视图：节点头用 8 色板竖条 + 淡染底色区分，结构边框为普通 1px var(--cn-border)。
 */

import { useMemo } from 'react'
import { Empty, Tag, Tooltip } from 'antd'
import { NodeIndexOutlined, ArrowRightOutlined } from '@ant-design/icons'
import type { RowResponse, Field, View } from '@/api'
import type { Density } from '@/theme/tableSettings'
import { resolveOpts, FLOW_OPTIONS, resolveAutoField, findOptionSchema } from '../view-config/viewOptionSchema'
import { formatFieldDisplayValue } from '../cells/fieldValueFormat'
import { buildFlowGraph, FLOW_UNGROUPED_LABEL, type FlowNode } from './flowBoard'

// ── 配色与密度 ────────────────────────────────────────

/** 节点色板 —— antd v5 官方预设主色（daybreak 系），按节点索引循环（语义为流程阶段着色，同 tagColors 策略） */
const NODE_COLORS: readonly string[] = [
  '#1677ff', '#52c41a', '#fa8c16', '#722ed1', '#13c2c2', '#eb2f96', '#faad14', '#2f54eb',
]
const nodeColor = (index: number): string => NODE_COLORS[index % NODE_COLORS.length]
const NODE_BG = (hex: string) => `${hex}14`
const NODE_HEADER_BG = (hex: string) => `color-mix(in srgb, ${hex} 16%, var(--cn-bg-subtle))`

/** 密度 → 节点宽度 / 卡片间距 / 字号 */
function densityStyle(density: Density) {
  if (density === 'compact') {
    return { nodeWidth: 176, cardPadding: '3px 8px', nodeGap: 6, cardGap: 4, fontSize: 12, metaFontSize: 10 }
  }
  if (density === 'spacious') {
    return { nodeWidth: 236, cardPadding: '7px 12px', nodeGap: 10, cardGap: 8, fontSize: 15, metaFontSize: 12 }
  }
  return { nodeWidth: 208, cardPadding: '5px 10px', nodeGap: 8, cardGap: 6, fontSize: 13, metaFontSize: 11 }
}

// ── 组件 ──────────────────────────────────────────────

interface FlowViewProps {
  rows: RowResponse[]
  fields: Field[]
  view?: View | null
  density: Density
  onRowClick?: (r: RowResponse) => void
}

/** 节点内记录卡片：显示 title_field 格式化值，点击打开行详情 */
function FlowCard({
  row,
  titleField,
  fields,
  style,
  onClick,
}: {
  row: RowResponse
  titleField?: string
  fields: Field[]
  style: { cardPadding: string; fontSize: number }
  onClick?: (r: RowResponse) => void
}) {
  const fieldDef = titleField ? fields.find((f) => f.name === titleField) : undefined
  const text = (fieldDef && formatFieldDisplayValue(fieldDef, row[titleField!])) || String(row.id ?? '')
  return (
    <Tooltip title={text} mouseEnterDelay={0.4}>
      <div
        data-testid="flow-card"
        onClick={() => onClick?.(row)}
        style={{
          padding: style.cardPadding,
          fontSize: style.fontSize,
          borderRadius: 6,
          background: 'var(--cn-bg-page)',
          border: '1px solid var(--cn-border)',
          cursor: onClick ? 'pointer' : 'default',
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
        }}
      >
        {text}
      </div>
    </Tooltip>
  )
}

/** 单条流转边连接线：箭头 + 流入量（下游节点记录数） */
function FlowConnector({ count }: { count?: number }) {
  return (
    <div
      data-testid="flow-connector"
      style={{
        flex: '0 0 auto', display: 'flex', flexDirection: 'column',
        alignItems: 'center', justifyContent: 'center', gap: 2,
        color: 'var(--cn-text-muted)', alignSelf: 'stretch', padding: '0 2px',
      }}
    >
      <ArrowRightOutlined />
      {count !== undefined && (
        <span style={{ fontSize: 10, whiteSpace: 'nowrap' }}>{count} 条流入</span>
      )}
    </div>
  )
}

export default function FlowView({ rows, fields, view, density, onRowClick }: FlowViewProps) {
  const opts = useMemo(
    () => resolveOpts(view?.view_options as Record<string, unknown> | undefined, FLOW_OPTIONS),
    [view?.view_options],
  )
  const ds = densityStyle(density)
  const nodeField = (opts.node_field as string) || ''
  const nodeOrder = useMemo(
    () => (Array.isArray(opts.node_order) ? (opts.node_order as unknown[]).map(String) : undefined),
    [opts.node_order],
  )
  const titleField = useMemo(() => {
    const configured = opts.title_field as string | undefined
    if (configured) return configured
    return resolveAutoField(fields, findOptionSchema('flow', 'title_field'))
  }, [opts.title_field, fields])

  const graph = useMemo(
    () => (nodeField ? buildFlowGraph(rows, fields, nodeField, nodeOrder) : { nodes: [], edges: [] }),
    [rows, fields, nodeField, nodeOrder],
  )

  // 边按「from→to」索引，供相邻节点间的连接线取流入量
  const edgeCounts = useMemo(() => {
    const m = new Map<string, number>()
    for (const e of graph.edges) m.set(`${e.from}\u0000${e.to}`, e.count)
    return m
  }, [graph.edges])

  // 未配置节点字段 → 引导空态（后端校验挡新视图，这里兜底历史数据）
  if (!nodeField) {
    return (
      <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <Empty description="流程视图需配置流程节点字段（视图设置里的「流程节点字段」）" />
      </div>
    )
  }

  // 无数据 → 引导空态（与其他视图语义一致）
  if (!rows.length) {
    return (
      <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <Empty description="这张表还没有数据，新增行后即可在流程管线中排布" />
      </div>
    )
  }

  const renderNode = (node: FlowNode, index: number) => {
    const color = nodeColor(index)
    const isUngrouped = node.key === FLOW_UNGROUPED_LABEL
    return (
      <div
        key={node.key}
        data-testid="flow-node"
        style={{
          flex: '0 0 auto', width: ds.nodeWidth, display: 'flex', flexDirection: 'column',
          background: isUngrouped ? 'var(--cn-bg-subtle)' : NODE_BG(color),
          border: '1px solid var(--cn-border)', borderRadius: 8, overflow: 'hidden',
        }}
      >
        <div
          data-testid="flow-node-header"
          style={{
            display: 'flex', alignItems: 'center', gap: 6,
            padding: '8px 10px', borderBottom: '1px solid var(--cn-border)',
            background: isUngrouped ? 'var(--cn-bg-subtle)' : NODE_HEADER_BG(color),
          }}
        >
          <span aria-hidden style={{ flexShrink: 0, width: 4, height: 14, borderRadius: 2, background: isUngrouped ? 'var(--cn-text-muted)' : color }} />
          <strong style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {node.label}
          </strong>
          <Tag style={{ margin: 0, fontSize: ds.metaFontSize, lineHeight: '16px' }}>{node.rows.length}</Tag>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: ds.cardGap, padding: ds.nodeGap }}>
          {node.rows.map((r) => (
            <FlowCard
              key={String(r.id)}
              row={r}
              titleField={titleField}
              fields={fields}
              style={{ cardPadding: ds.cardPadding, fontSize: ds.fontSize }}
              onClick={onRowClick}
            />
          ))}
        </div>
      </div>
    )
  }

  const pipeline: React.ReactNode[] = []
  graph.nodes.forEach((node, i) => {
    pipeline.push(renderNode(node, i))
    if (i + 1 < graph.nodes.length) {
      const next = graph.nodes[i + 1]
      pipeline.push(
        <FlowConnector key={`${node.key}→${next.key}`} count={edgeCounts.get(`${node.key}\u0000${next.key}`)} />,
      )
    }
  })

  return (
    <div data-testid="flow-view" style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column' }}>
      {/* 工具栏 */}
      <div
        style={{
          padding: '8px 12px', display: 'flex', alignItems: 'center', gap: 12,
          borderBottom: '1px solid var(--cn-border)', background: 'var(--cn-bg-container)',
        }}
      >
        <div style={{ fontWeight: 600, fontSize: ds.fontSize + 1, display: 'flex', alignItems: 'center', gap: 6 }}>
          <NodeIndexOutlined style={{ color: 'var(--cn-brand-color)' }} />
          流程视图
        </div>
        <Tag color="blue" style={{ margin: 0 }}>
          {graph.nodes.length} 个节点 · {rows.length} 条记录
        </Tag>
        <div style={{ flex: 1 }} />
        <span style={{ fontSize: ds.metaFontSize, color: 'var(--cn-text-muted)' }}>按流程顺序从左到右流转</span>
      </div>

      {/* 横向流转管线 */}
      <div
        data-testid="flow-pipeline"
        style={{
          flex: 1, minHeight: 0, overflow: 'auto', padding: 12,
          display: 'flex', alignItems: 'flex-start', gap: ds.nodeGap,
          background: 'var(--cn-bg-container)',
        }}
      >
        {pipeline}
      </div>
    </div>
  )
}
