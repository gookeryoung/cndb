/** 数据表关联图页（需求 0187 P0）.
 *
 * 用 echarts graph + layout=force 呈现工作区数据表经 link 字段形成的引用关系。
 * 本页由 App.tsx 动态 import（H31），echarts 不进首屏 bundle。
 * 节点 = 当前用户可读的表（后端已按 H64 过滤），边 = link 字段；
 * lookup 是同一关系的投影列不建边；跨工作区 / 已删 / 无权目标聚合为虚拟节点。
 *
 * 交互口径与文档图谱（需求 0168 / 0182 / 0183 / 0184）保持一致：
 * - 单击选中 + 右侧 Inspector，双击才打开表；
 * - 图例按「表分组」着色可点击显隐；
 * - 孤立表 / 枢纽清单；`?focus=<tid>&depth=1|2` 局部图（前端 BFS）；
 * - 标签按缩放倍率淡化；缩放以容器中心为锚点；
 * - `labelLayout.hideOverlap` + SVG renderer。
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Alert,
  App as AntApp,
  Button,
  Checkbox,
  Form,
  Input,
  Modal,
  Popconfirm,
  Select,
  Space,
  Switch,
  Tag,
  Tooltip,
  Typography,
} from 'antd'
import {
  AimOutlined,
  ApartmentOutlined,
  CopyOutlined,
  DeleteOutlined,
  EditOutlined,
  FilterOutlined,
  LinkOutlined,
  MinusOutlined,
  PlusOutlined,
} from '@ant-design/icons'
import * as echarts from 'echarts/core'
import { GraphChart } from 'echarts/charts'
import { TooltipComponent } from 'echarts/components'
import { LabelLayout } from 'echarts/features'
import { SVGRenderer } from 'echarts/renderers'
import type { EChartsCoreOption, EChartsType } from 'echarts/core'

import { fieldApi, tableApi } from '@/api'
import type { LinkGraphEdge, LinkGraphNode } from '@/api'
import { useTheme } from '@/theme/ThemeProvider'
import { SPACE } from '@/theme/tokens'
import { copyText } from '@/utils/clipboard'
// 本页样式随 chunk 加载：.cn-tgraph-* 只被这一页使用，留在 index.css 会让首屏 CSS 白付体积。
import './TableLinkGraphPage.css'

echarts.use([GraphChart, TooltipComponent, LabelLayout, SVGRenderer])

const { Text } = Typography

/** 缩放档位：与文档图谱一致，单次 ±25%，范围 0.25×–4× */
const ZOOM_STEP_IN = 1.25
const ZOOM_STEP_OUT = 0.8
const ZOOM_MIN = 0.25
const ZOOM_MAX = 4

/** 标签淡化阈值：低于该倍率时标签整体隐藏，避免缩小后糊成一片 */
const LABEL_ZOOM_THRESHOLD = 0.6

/** 节点直径上限：度数再高也不再膨胀 */
const MAX_NODE_SIZE = 40
/** 孤立表直径：比连通节点小，让「没连线的」在画布上自然退后 */
const ISOLATED_NODE_SIZE = 10
/** 选中节点放大倍数：轻微强调，实际尺寸仍受 MAX_NODE_SIZE 夹住 */
const SELECTED_NODE_SCALE = 1.15
/** 虚拟节点直径（其他工作区 / 已删除目标的聚合） */
const VIRTUAL_NODE_SIZE = 22

/** 边线宽与透明度：默认线细且淡，让节点成为视觉主体 */
const EDGE_WIDTH = 1
const EDGE_OPACITY = 0.32
/** 虚线边（指向虚拟节点）：形状已足够区分，透明度提回一点保证可读 */
const VIRTUAL_EDGE_OPACITY = 0.6
/** 选中节点的邻接边加粗加亮，其余边退到几乎看不见 */
const EDGE_EMPHASIS_WIDTH = 1.6
const EDGE_EMPHASIS_OPACITY = 0.9
const DIMMED_NODE_OPACITY = 0.12
const DIMMED_EDGE_OPACITY = 0.06
const ISOLATED_NODE_OPACITY = 0.35
/** 边染色的分组色权重：剩下的交给 --cn-border，压掉饱和色 */
const EDGE_COLOR_GROUP_PCT = 45
/** 枢纽清单取度数的前 N 个 */
const HUB_TOP_N = 10
/** 局部图最大深度：1 跳是直接引用，2 跳已接近全图噪声 */
const MAX_FOCUS_DEPTH = 2

/** 分组配色板（fallback）：分组超过 8 个时循环取色；虚拟节点固定中性灰 */
const GROUP_PALETTE = [
  'var(--cn-brand-color)',
  'var(--cn-success)',
  'var(--cn-warning)',
  'var(--cn-purple)',
  'var(--cn-cyan)',
  'var(--cn-magenta)',
  'var(--cn-gold)',
  'var(--cn-geekblue)',
] as const

/** 每个分组一个稳定颜色：按分组 id 在色板中取位，未知分组回落未分组灰 */
function groupColor(node: LinkGraphNode, colors: ThemeColors): string {
  if (node.virtual) return colors.muted
  if (node.group_id == null) return colors.primary
  return GROUP_PALETTE[Math.abs(node.group_id) % GROUP_PALETTE.length]
}

/** SVG 属性不解析 CSS 变量：与文档图谱同口径，先读计算值再注入 option */
interface ThemeColors {
  border: string
  container: string
  text: string
  primary: string
  muted: string
}

function readThemeColors(): ThemeColors {
  const read = (name: string, fallback: string): string => {
    if (typeof document === 'undefined') return fallback
    const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
    return value || fallback
  }
  return {
    border: read('--cn-border', '#e5e7eb'),
    container: read('--cn-bg-container', '#ffffff'),
    text: read('--cn-text-primary', '#1f2937'),
    primary: read('--cn-brand-color', '#2563eb'),
    muted: read('--cn-text-tertiary', '#6b7280'),
  }
}

/** 字号 / 字重走 token（H29）：与文档图谱 readThemeMetrics 同源 */
interface ThemeMetrics {
  labelFontSize: number
  labelFontWeight: number
}

function readThemeMetrics(): ThemeMetrics {
  const read = (name: string, fallback: string): string => {
    if (typeof document === 'undefined') return fallback
    const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
    return value || fallback
  }
  const size = Number.parseFloat(read('--cn-text-2xs', '11'))
  const weight = Number.parseInt(read('--cn-weight-medium', '500'), 10)
  return {
    labelFontSize: Number.isFinite(size) && size > 0 ? size : 11,
    labelFontWeight: Number.isFinite(weight) && weight > 0 ? weight : 500,
  }
}

/** 表名过长时省略，避免力导向图标签互相压盖 */
function nodeLabel(name: string | null | undefined): string {
  const text = typeof name === 'string' && name ? name : '未命名表'
  return text.length > 18 ? `${text.slice(0, 17)}…` : text
}

/** 度数 = 唯一关联表数（自关联不计边，已并入 self_loop 徽标） */
function buildDegrees(nodes: LinkGraphNode[], edges: LinkGraphEdge[]): Map<number, number> {
  const degree = new Map<number, number>()
  for (const node of nodes) degree.set(node.id, 0)
  for (const edge of edges) {
    if (degree.has(edge.source)) degree.set(edge.source, (degree.get(edge.source) ?? 0) + 1)
    if (degree.has(edge.target)) degree.set(edge.target, (degree.get(edge.target) ?? 0) + 1)
  }
  return degree
}

/** 度数 → 直径：14px 起步，按 log 缓增，虚拟节点固定尺寸 */
function nodeSize(node: LinkGraphNode, degree: number): number {
  if (node.virtual) return VIRTUAL_NODE_SIZE
  const scaled = 14 + Math.log2(degree + 1) * 8
  return Math.round(Math.min(MAX_NODE_SIZE, scaled))
}

/** 局部图扩邻：从中心节点按无向邻接做 BFS，深度 1–2（与文档图谱同口径） */
export function collectNeighborhood(edges: LinkGraphEdge[], focusId: number, depth: number): Set<number> {
  const adjacency = new Map<number, number[]>()
  const link = (a: number, b: number) => {
    const list = adjacency.get(a)
    if (list) list.push(b)
    else adjacency.set(a, [b])
  }
  for (const edge of edges) {
    link(edge.source, edge.target)
    link(edge.target, edge.source)
  }
  const seen = new Set<number>([focusId])
  let frontier = [focusId]
  for (let level = 0; level < depth && frontier.length > 0; level += 1) {
    const next: number[] = []
    for (const id of frontier) {
      for (const peer of adjacency.get(id) ?? []) {
        if (seen.has(peer)) continue
        seen.add(peer)
        next.push(peer)
      }
    }
    frontier = next
  }
  return seen
}

export interface GraphFilters {
  keyword: string
  onlyIsolated: boolean
  onlyExternal: boolean
  onlySelfLoop: boolean
}

const EMPTY_FILTERS: GraphFilters = { keyword: '', onlyIsolated: false, onlyExternal: false, onlySelfLoop: false }

interface FilterDeps {
  /** 中心表集合（局部图）；null 表示全图 */
  scope: Set<number> | null
  /** 被图例关掉的分组 id（虚拟节点按其负 id 过滤） */
  hiddenGroups: Set<number>
  degrees: Map<number, number>
}

/** 一次遍历同时算可见节点与「两端都可见」的边：边不能只按源筛选，否则会挂到画布外 */
export function filterGraph(
  nodes: LinkGraphNode[],
  edges: LinkGraphEdge[],
  filters: GraphFilters,
  deps: FilterDeps,
): { nodes: LinkGraphNode[]; edges: LinkGraphEdge[] } {
  const keyword = filters.keyword.trim().toLowerCase()
  const kept = nodes.filter(node => {
    if (deps.scope && !deps.scope.has(node.id)) return false
    if (deps.hiddenGroups.has(node.group_id ?? -0)) return false
    if (keyword && !node.name.toLowerCase().includes(keyword)) return false
    if (filters.onlyIsolated && (deps.degrees.get(node.id) ?? 0) > 0) return false
    // 只看外部关联：后端约定虚拟 id -1 = 其他工作区聚合（-2 = 已删除 / 不可访问）
    if (filters.onlyExternal && !(node.virtual && node.id === -1)) return false
    if (filters.onlySelfLoop && !node.self_loop) return false
    return true
  })
  const ids = new Set(kept.map(node => node.id))
  return { nodes: kept, edges: edges.filter(edge => ids.has(edge.source) && ids.has(edge.target)) }
}

/** 孤立表：度数为 0 的真实表（虚拟节点天然无边，不混进来） */
export function findIsolated(nodes: LinkGraphNode[], degrees: Map<number, number>): LinkGraphNode[] {
  return nodes.filter(node => !node.virtual && (degrees.get(node.id) ?? 0) === 0)
}

/** 枢纽：按度数倒序取前 N，度数为 0 的不能算枢纽 */
export function findHubs(nodes: LinkGraphNode[], degrees: Map<number, number>, limit = HUB_TOP_N): LinkGraphNode[] {
  return nodes
    .filter(node => !node.virtual && (degrees.get(node.id) ?? 0) > 0)
    .sort((a, b) => (degrees.get(b.id) ?? 0) - (degrees.get(a.id) ?? 0) || a.id - b.id)
    .slice(0, limit)
}

/** 边的线色：取源节点的分组色，与 --cn-border 按权重混一次压掉饱和色 */
function edgeColor(source: ColorizedNode | undefined, colors: ThemeColors): string {
  if (!source) return colors.border
  if (source.virtual) return colors.muted
  // SVG 属性读不到 var()：分组色在 option 里已解析成实际颜色值
  return source.itemColorCache ?? mixWithBorder(source.groupColorCache ?? colors.primary, colors)
}

/** 旧内核没有 color-mix：按 themeMix 兼容层语义手混（文档图谱 edgeColor 同款） */
function mixWithBorder(color: string, colors: ThemeColors): string {
  if (color.startsWith('var(') || !color) return colors.border
  return mixHex(color, colors.border, EDGE_COLOR_GROUP_PCT)
}

/** 简易十六进制混合：a 占 pct%，其余给 b；非法输入回落 b */
function mixHex(a: string, b: string, pct: number): string {
  const pa = parseHex(a)
  const pb = parseHex(b)
  if (!pa || !pb) return b
  const mix = (x: number, y: number) => Math.round((x * pct + y * (100 - pct)) / 100)
  return `rgb(${mix(pa[0], pb[0])}, ${mix(pa[1], pb[1])}, ${mix(pa[2], pb[2])})`
}

function parseHex(value: string): [number, number, number] | null {
  const m = /^#([0-9a-f]{6})$/i.exec(value.trim())
  if (!m) return null
  const n = Number.parseInt(m[1], 16)
  return [(n >> 16) & 0xff, (n >> 8) & 0xff, n & 0xff]
}

/** 把节点/边写进 series 前预解析颜色：SVG 属性读不到 CSS 变量 */
interface ColorizedNode extends LinkGraphNode {
  groupColorCache?: string
  itemColorCache?: string
}

function colorizeNodes(nodes: LinkGraphNode[], colors: ThemeColors): ColorizedNode[] {
  return nodes.map(node => {
    const raw = groupColor(node, colors)
    // 色板项是 var(--cn-*)：解析成实际值后再上画布
    const resolved = raw.startsWith('var(') ? resolveVar(raw, colors) : raw
    return { ...node, groupColorCache: resolved, itemColorCache: mixWithBorder(resolved, colors) }
  })
}

/** var(--cn-xxx) → getComputedStyle 取值；读不到回落主色 */
function resolveVar(raw: string, colors: ThemeColors): string {
  const name = /var\((--cn-[\w-]+)\)/.exec(raw)?.[1]
  if (!name || typeof document === 'undefined') return colors.primary
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || colors.primary
}

function buildOption(
  nodes: LinkGraphNode[],
  edges: LinkGraphEdge[],
  colors: ThemeColors,
  metrics: ThemeMetrics,
  selectedId: number | null = null,
): EChartsCoreOption {
  const degree = buildDegrees(nodes, edges)
  // 颜色缓存在 colorized 上：节点与边的取色必须走同一份，否则边读不到缓存
  const colorized = colorizeNodes(nodes, colors)
  const nodeById = new Map(colorized.map(node => [node.id, node]))

  /** 选中态常驻邻接聚焦：单击后整张图只留「这个节点 + 它的直接邻居」，其余压暗 */
  const hasSelection = selectedId != null && nodes.some(node => node.id === selectedId)
  const adjacent = new Set<number>()
  if (hasSelection) {
    adjacent.add(selectedId as number)
    for (const edge of edges) {
      if (edge.source === selectedId) adjacent.add(edge.target)
      if (edge.target === selectedId) adjacent.add(edge.source)
    }
  }
  const isDimmed = (id: number) => hasSelection && !adjacent.has(id)
  const adjacentEdge = (edge: LinkGraphEdge) =>
    hasSelection && (edge.source === selectedId || edge.target === selectedId)

  return {
    animationDuration: 300,
    tooltip: {
      trigger: 'item',
      confine: true,
      formatter: (params: { dataType?: string; data?: (LinkGraphNode & LinkGraphEdge) }) => {
        const data = params.data
        if (params.dataType === 'edge') {
          const edge = data as LinkGraphEdge
          const source = nodeById.get(edge.source)
          const target = nodeById.get(edge.target)
          const hints = [
            edge.multiple ? '多选关联' : '单选关联',
            edge.reference_field_count > 0 ? `引用字段 ${edge.reference_field_count} 个` : '',
            edge.target_state !== 'ok' ? TARGET_STATE_LABELS[edge.target_state] : '',
          ].filter(Boolean)
          return `${source?.name ?? `#${edge.source}`} → ${target?.name ?? ''}${hints.length ? `（${hints.join('；')}）` : ''}`
        }
        const node = data as LinkGraphNode
        const suffix = node.virtual ? '（虚拟聚合）' : node.self_loop ? '（自关联）' : ''
        return `${nodeLabel(node.name)}${suffix}<br/>关联 ${degree.get(node.id) ?? 0} 条 · 字段 ${node.field_count}`
      },
    },
    series: [
      {
        type: 'graph',
        layout: 'force',
        roam: true,
        draggable: true,
        scaleLimit: { min: ZOOM_MIN, max: ZOOM_MAX },
        nodeScaleRatio: 0.4,
        force: {
          initLayout: 'circular',
          repulsion: 260,
          edgeLength: [70, 150],
          gravity: 0.08,
          friction: 0.2,
        },
        layoutAnimation: true,
        label: {
          show: true,
          position: 'right',
          distance: 5,
          formatter: (p: { data: LinkGraphNode }) => nodeLabel(p.data?.name),
          fontSize: metrics.labelFontSize,
          fontWeight: metrics.labelFontWeight,
          color: colors.text,
        },
        labelLayout: { hideOverlap: true },
        edgeSymbol: ['none', 'arrow'],
        edgeSymbolSize: 7,
        lineStyle: { curveness: 0.06, width: EDGE_WIDTH },
        data: colorized.map(node => {
          const nodeDegree = degree.get(node.id) ?? 0
          const isSelected = node.id === selectedId
          const isIsolated = !node.virtual && nodeDegree === 0 && !isSelected
          const size = isIsolated
            ? ISOLATED_NODE_SIZE
            : isSelected && !node.virtual
              ? Math.min(MAX_NODE_SIZE, Math.round(nodeSize(node, nodeDegree) * SELECTED_NODE_SCALE))
              : nodeSize(node, nodeDegree)
          const opacity = isDimmed(node.id)
            ? DIMMED_NODE_OPACITY
            : isIsolated
              ? ISOLATED_NODE_OPACITY
              : 0.95
          return {
            id: String(node.id),
            name: node.name,
            value: node.id,
            itemStyle: {
              color: node.groupColorCache ?? colors.primary,
              borderColor: isSelected ? colors.primary : colors.container,
              borderWidth: 2,
              shadowBlur: isSelected ? 10 : 0,
              shadowColor: isSelected ? colors.primary : 'transparent',
              opacity,
            },
            // 虚拟聚合节点用圆角方形：与真实表（圆）形状双编码
            symbol: node.virtual ? 'roundRect' : 'circle',
            symbolSize: size,
            self_loop: node.self_loop,
            virtual: node.virtual,
            selected: isSelected,
            label: {
              ...(isIsolated ? { show: false } : {}),
            },
          }
        }),
        links: edges.map(edge => {
          const emphasized = adjacentEdge(edge)
          const dimmed = hasSelection && !emphasized
          const virtualTarget = edge.target < 0
          return {
            source: String(edge.source),
            target: String(edge.target),
            lineStyle: {
              color: edgeColor(nodeById.get(edge.source), colors),
              type: virtualTarget ? 'dashed' : 'solid',
              width: emphasized ? EDGE_EMPHASIS_WIDTH : EDGE_WIDTH,
              opacity: dimmed
                ? DIMMED_EDGE_OPACITY
                : emphasized
                  ? EDGE_EMPHASIS_OPACITY
                  : virtualTarget
                    ? VIRTUAL_EDGE_OPACITY
                    : EDGE_OPACITY,
              curveness: 0.06,
            },
            target_state: edge.target_state,
            field_name: edge.field_name,
          }
        }),
        emphasis: {
          focus: 'adjacency',
          scale: 1.1,
          label: { show: true, fontWeight: 'bold' },
          lineStyle: { width: 2, opacity: 0.95 },
        },
        blur: { itemStyle: { opacity: 0.15 }, label: { opacity: 0.15 } },
      },
    ],
  } as EChartsCoreOption
}

/** 虚拟边目标态 → 中文短标签（tooltip / Inspector 共用） */
const TARGET_STATE_LABELS: Record<string, string> = {
  other_workspace: '目标在其他工作区',
  trashed: '目标已删除',
  restricted: '目标不可访问',
}

export default function TableLinkGraphPage() {
  const { wid } = useParams<{ wid: string }>()
  const workspaceId = wid ?? ''
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const { message } = AntApp.useApp()
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<EChartsType | null>(null)
  /** 当前缩放倍率：只用于界面上「100%」这类读数，真值由 echarts 自己维护 */
  const zoomRef = useRef(1)
  const [zoomPct, setZoomPct] = useState(100)
  const [filters, setFilters] = useState<GraphFilters>(EMPTY_FILTERS)
  const [hiddenGroups, setHiddenGroups] = useState<Set<number>>(() => new Set())
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [showLabels, setShowLabels] = useState(true)

  const graphQuery = useQuery({
    queryKey: ['table-link-graph', workspaceId],
    queryFn: () => tableApi.linkGraph(workspaceId),
  })
  const graph = graphQuery.data
  const nodes = useMemo(() => graph?.nodes ?? [], [graph])
  const edges = useMemo(() => graph?.edges ?? [], [graph])

  /** 中心表（局部图）：URL 即状态，刷新与分享都能复现同一张局部图 */
  const focusId = useMemo(() => {
    const raw = searchParams.get('focus')
    const parsed = Number(raw)
    return raw && Number.isFinite(parsed) && parsed > 0 ? parsed : null
  }, [searchParams])
  const focusDepth = useMemo(() => {
    const parsed = Number(searchParams.get('depth'))
    if (!Number.isFinite(parsed)) return 1
    return Math.min(MAX_FOCUS_DEPTH, Math.max(1, Math.round(parsed)))
  }, [searchParams])

  const degrees = useMemo(() => buildDegrees(nodes, edges), [nodes, edges])
  const scope = useMemo(
    () => (focusId != null ? collectNeighborhood(edges, focusId, focusDepth) : null),
    [edges, focusId, focusDepth],
  )
  /** 中心表不在图里（已删除 / 超出 500 上限）：不能静默画全图，否则用户以为在看局部图 */
  const focusMissing = focusId != null && nodes.length > 0 && !nodes.some(n => n.id === focusId)

  const visible = useMemo(
    () => filterGraph(nodes, edges, filters, { scope, hiddenGroups, degrees }),
    [nodes, edges, filters, scope, hiddenGroups, degrees],
  )

  const { mode: themeMode } = useTheme()
  const colors = useMemo(
    () => readThemeColors(),
    // themeMode 进依赖：切换主题后 getComputedStyle 才拿到新的 --cn-* 值
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [themeMode],
  )
  const metrics = useMemo(
    () => readThemeMetrics(),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [themeMode],
  )
  const option = useMemo(
    () => buildOption(visible.nodes, visible.edges, colors, metrics, selectedId),
    [visible.nodes, visible.edges, colors, metrics, selectedId],
  )

  /** 图例按「当前图里出现的分组」生成，避免列一堆没有节点的分组 */
  const legend = useMemo(() => {
    const groups = new Map<number | null, string>()
    for (const node of visible.nodes) {
      const key = node.group_id ?? null
      if (!groups.has(key)) groups.set(key, node.virtual ? '虚拟目标' : node.group_name || '未分组')
    }
    return [...groups.entries()].sort((a, b) => (a[0] ?? 0) - (b[0] ?? 0))
  }, [visible.nodes])

  const isolated = useMemo(() => findIsolated(nodes, degrees), [nodes, degrees])
  const hubs = useMemo(() => findHubs(nodes, degrees), [nodes, degrees])

  const selected = useMemo(
    () => visible.nodes.find(node => node.id === selectedId) ?? null,
    [visible.nodes, selectedId],
  )

  /** 选中表的出边 / 入边从当前图推导：图外的边本来也看不见 */
  const selectionLinks = useMemo(() => {
    if (!selected) return { out: [] as LinkGraphEdge[], in: [] as LinkGraphEdge[] }
    return {
      out: visible.edges.filter(edge => edge.source === selected.id),
      in: visible.edges.filter(edge => edge.target === selected.id),
    }
  }, [visible.edges, selected])

  /** 选中项被筛掉时清空，否则 Inspector 会显示一个画布上根本不存在的表 */
  useEffect(() => {
    if (selectedId != null && !visible.nodes.some(node => node.id === selectedId)) setSelectedId(null)
  }, [visible.nodes, selectedId])

  const syncZoomPct = useCallback(() => {
    setZoomPct(Math.round(zoomRef.current * 100))
  }, [])

  const nodeNameById = useCallback(
    (id: number) => nodes.find(node => node.id === id)?.name ?? '',
    [nodes],
  )

  /** 以画布中心为锚点缩放：echarts graphRoam 缺省锚点是 (0,0)，不带 origin 会往左上角飞 */
  const zoomBy = useCallback(
    (factor: number) => {
      const chart = chartRef.current
      if (!chart) return
      const box = containerRef.current
      const originX = (box?.clientWidth ?? 0) / 2
      const originY = (box?.clientHeight ?? 0) / 2
      const next = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, zoomRef.current * factor))
      if (next === zoomRef.current) return
      zoomRef.current = next
      chart.dispatchAction({ type: 'graphRoam', zoom: factor, originX, originY })
      syncZoomPct()
    },
    [syncZoomPct],
  )

  // click 处理器只挂一次（见上），用 ref 读最新交互态
  const nodeByIdRef = useRef<Map<number, LinkGraphNode>>(new Map())
  const connectFromRef = useRef<LinkGraphNode | null>(null)
  const cancelConnectRef = useRef<() => void>(() => {})
  const pickConnectTargetRef = useRef<(node: LinkGraphNode) => void>(() => {})

  useEffect(() => {
    if (!containerRef.current || !graph) return
    const chart = echarts.init(containerRef.current, undefined, { renderer: 'svg' })
    chartRef.current = chart
    // 单击只选中：图谱里点错一下就跳走是文档图谱首版最被诟病的交互。
    // P1 E4：连线态下单击的语义变成「选目标表」，故先看连线态（经 ref 读最新值，
    // 避免把 click 处理器因依赖变化重挂而丢失 echarts 内部状态）。
    chart.on('click', params => {
      if (params.dataType !== 'node') {
        setSelectedId(null)
        cancelConnectRef.current()
        return
      }
      const data = params.data as { value?: number } | null
      const tid = data?.value
      if (typeof tid !== 'number') return
      const node = nodeByIdRef.current.get(tid)
      if (connectFromRef.current) {
        if (node) pickConnectTargetRef.current(node)
        return
      }
      setSelectedId(tid)
    })
    chart.on('dblclick', params => {
      if (params.dataType !== 'node') return
      const data = params.data as { value?: number; virtual?: boolean } | null
      const tid = data?.value
      if (typeof tid !== 'number' || tid <= 0 || data?.virtual) return
      navigate(`/w/${workspaceId}/tables/${tid}`)
    })
    // 滚轮 / 拖拽缩放由 RoamController 直接改视图，这里同步倍率读数
    chart.on('graphroam', () => {
      const series = (chart.getOption() as { series?: { zoom?: number }[] }).series
      const zoom = series?.[0]?.zoom
      if (typeof zoom === 'number') {
        zoomRef.current = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, zoom))
        syncZoomPct()
      }
    })
    const resize = () => chart.resize()
    window.addEventListener('resize', resize)
    return () => {
      window.removeEventListener('resize', resize)
      chart.dispose()
      chartRef.current = null
    }
  }, [graph, navigate, workspaceId, syncZoomPct])

  useEffect(() => {
    // merge 而非 notMerge：全量重建会让力导向重新收敛，选中 / 筛选一次就整张图重排跳动
    chartRef.current?.setOption(option, false)
  }, [option])

  /** 标签显隐单独下发：塞进主 option 会让每次缩放都重建并触发重排跳动 */
  const labelsVisible = showLabels && zoomPct >= LABEL_ZOOM_THRESHOLD * 100
  useEffect(() => {
    chartRef.current?.setOption({ series: [{ label: { show: labelsVisible } }] })
  }, [labelsVisible, option])

  /** 复位：'restore' 会把 option 重置回初始提交态，同时让力导向重新收敛 */
  const reset = useCallback(() => {
    zoomRef.current = 1
    syncZoomPct()
    chartRef.current?.dispatchAction({ type: 'restore' })
  }, [syncZoomPct])

  /** 定位到某个节点：用它自带的邻接聚焦代替「移到中心」 */
  const focusNode = useCallback((nodeId: number) => {
    setSelectedId(nodeId)
    const dataIndex = (chartRef.current?.getOption() as { series?: { data?: unknown[] }[] } | undefined)
      ?.series?.[0]?.data
    const index = Array.isArray(dataIndex)
      ? dataIndex.findIndex((item) => (item as { value?: number })?.value === nodeId)
      : -1
    if (index >= 0) {
      chartRef.current?.dispatchAction({ type: 'focusNodeAdjacency', seriesIndex: 0, dataIndex: index })
    }
  }, [])

  const setFocus = useCallback(
    (tid: number | null, depth = 1) => {
      const next = new URLSearchParams(searchParams)
      if (tid == null) next.delete('focus')
      else next.set('focus', String(tid))
      if (tid != null) next.set('depth', String(depth))
      else next.delete('depth')
      setSearchParams(next, { replace: true })
    },
    [searchParams, setSearchParams],
  )

  const copyShareLink = useCallback(async () => {
    if (!selected) return
    if (typeof window === 'undefined') return
    const link = `${window.location.origin}/w/${workspaceId}/tables/graph?focus=${selected.id}&depth=1`
    if (await copyText(link)) message.success('已复制图谱链接')
  }, [selected, workspaceId, message])

  const toggleGroup = useCallback((key: number) => {
    setHiddenGroups(prev => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }, [])

  const openTable = useCallback(
    (node: LinkGraphNode) => {
      if (node.virtual || node.id <= 0) return
      navigate(`/w/${workspaceId}/tables/${node.id}`)
    },
    [navigate, workspaceId],
  )

  // ── P1 图上编辑（ADR 0187 E1–E4）──────────────────────────────
  // 不新增写路径：建 / 改 / 删边一律走既有字段端点（D6），本页只做表单预填 + 提交。

  /** 连线中态：E4 两步点击（点源表 → 点目标表），不做拖拽连线（D5） */
  const [connectFrom, setConnectFrom] = useState<LinkGraphNode | null>(null)
  /** 连线第二步选定的目标表（弹命名表单前） */
  const [pendingTarget, setPendingTarget] = useState<LinkGraphNode | null>(null)
  /** 正在编辑的边（null = 未打开编辑弹窗） */
  const [editingEdge, setEditingEdge] = useState<LinkGraphEdge | null>(null)
  const [form] = Form.useForm()

  const queryClient = useQueryClient()
  const invalidateGraph = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: ['table-link-graph', workspaceId] })
  }, [queryClient, workspaceId])

  /** 可连线的目标表：真实节点（虚拟节点没有可建的 link 目标） */
  const connectTargets = useMemo(
    () => nodes.filter(node => !node.virtual && node.id > 0),
    [nodes],
  )

  const createEdge = useMutation({
    mutationFn: (payload: { sourceId: number; targetId: number; name: string; multiple: boolean }) =>
      fieldApi.create(workspaceId, payload.sourceId, {
        name: payload.name,
        field_type: 'link',
        config: { target_table_id: payload.targetId, multiple: payload.multiple },
      }),
    onSuccess: () => {
      message.success('已建立关联')
      setConnectFrom(null)
      invalidateGraph()
    },
    onError: (err: unknown) => message.error((err instanceof Error ? err.message : '建立关联失败')),
  })

  const updateEdge = useMutation({
    mutationFn: (payload: { edge: LinkGraphEdge; name: string; multiple: boolean; targetId: number }) =>
      fieldApi.update(workspaceId, payload.edge.source, payload.edge.id, {
        name: payload.name,
        config: { target_table_id: payload.targetId, multiple: payload.multiple },
      }),
    onSuccess: () => {
      message.success('已更新关联')
      setEditingEdge(null)
      invalidateGraph()
    },
    onError: (err: unknown) => message.error((err instanceof Error ? err.message : '更新关联失败')),
  })

  /** 改目标表会失效既有取值（D7）：后端 400 时提示用户确认后带 force 重试 */
  const updateEdgeForce = useMutation({
    mutationFn: (payload: { edge: LinkGraphEdge; name: string; multiple: boolean; targetId: number }) =>
      fieldApi.update(
        workspaceId,
        payload.edge.source,
        payload.edge.id,
        { name: payload.name, config: { target_table_id: payload.targetId, multiple: payload.multiple } },
        true,
      ),
    onSuccess: () => {
      message.success('已更新关联（失效关联已清除）')
      setEditingEdge(null)
      invalidateGraph()
    },
    onError: (err: unknown) => message.error((err instanceof Error ? err.message : '更新关联失败')),
  })

  const deleteEdge = useMutation({
    mutationFn: (edge: LinkGraphEdge) => fieldApi.remove(workspaceId, edge.source, edge.id),
    onSuccess: () => {
      message.success('已删除关联')
      setEditingEdge(null)
      invalidateGraph()
    },
    onError: (err: unknown) => message.error((err instanceof Error ? err.message : '删除关联失败')),
  })

  /** E4：进入连线态。仅当源表可编辑（can_edit）才允许 */
  const startConnect = useCallback((node: LinkGraphNode) => {
    if (node.virtual || !node.can_edit) return
    setConnectFrom(node)
    setSelectedId(node.id)
  }, [])

  /** E4：连线态下点第二个节点 = 选目标，弹命名表单 */
  const pickConnectTarget = useCallback(
    (target: LinkGraphNode) => {
      if (!connectFrom || target.virtual || target.id === connectFrom.id) return
      const suggested = `关联${target.name}`.slice(0, 64)
      form.setFieldsValue({ name: suggested, multiple: true })
      setPendingTarget(target)
    },
    [connectFrom, form],
  )

  const cancelConnect = useCallback(() => {
    setConnectFrom(null)
    setPendingTarget(null)
  }, [])

  /** 打开编辑弹窗：从 Inspector 的边列表进入 */
  const openEdgeEditor = useCallback(
    (edge: LinkGraphEdge) => {
      const targetNode = nodes.find(node => node.id === edge.target)
      form.setFieldsValue({
        name: edge.field_name,
        multiple: edge.multiple,
        targetId: edge.target > 0 ? edge.target : undefined,
      })
      setEditingEdge(edge)
      // targetNode 仅用于校验提示，弹窗里由 Select 自己渲染
      void targetNode
    },
    [form, nodes],
  )

  // refs 与最新态同步：echarts 的 click 处理器只挂一次，必须能读到当前连线态
  useEffect(() => {
    nodeByIdRef.current = new Map(nodes.map(node => [node.id, node]))
  }, [nodes])
  useEffect(() => {
    connectFromRef.current = connectFrom
  }, [connectFrom])
  useEffect(() => {
    cancelConnectRef.current = cancelConnect
    pickConnectTargetRef.current = pickConnectTarget
  }, [cancelConnect, pickConnectTarget])

  /** E4：ESC 取消连线（拖拽中按 ESC 是通用预期） */
  useEffect(() => {
    if (!connectFrom) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') cancelConnect()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [connectFrom, cancelConnect])

  const hiddenCount = Math.max(0, (graph?.nodes?.length ?? 0) - visible.nodes.length)

  return (
    <div className="cn-page" data-testid="table-graph-page">
      <header className="cn-page-head">
        <div className="cn-page-head-main">
          <span className="cn-page-head-icon" aria-hidden><ApartmentOutlined /></span>
          <div className="cn-page-head-text">
            <h1 className="cn-page-head-title">关联图</h1>
            <div className="cn-page-head-sub">
              数据表之间通过「关联」字段的引用关系；单击选中、双击打开表，虚线为目标不可见
            </div>
          </div>
        </div>
        <div className="cn-page-head-actions">
          <Space size={SPACE.sm}>
            <Button
              size="small"
              data-testid="table-graph-labels-toggle"
              aria-pressed={showLabels}
              onClick={() => setShowLabels(v => !v)}
            >
              {showLabels ? '隐藏标签' : '显示标签'}
            </Button>
            <Text type="secondary" data-testid="table-graph-zoom-pct" style={{ fontSize: 'var(--cn-text-xs)' }}>
              {zoomPct}%
            </Text>
            <Button
              size="small"
              icon={<MinusOutlined />}
              aria-label="缩小"
              disabled={zoomPct <= ZOOM_MIN * 100}
              data-testid="table-graph-zoom-out"
              onClick={() => zoomBy(ZOOM_STEP_OUT)}
            />
            <Button
              size="small"
              icon={<PlusOutlined />}
              aria-label="放大"
              disabled={zoomPct >= ZOOM_MAX * 100}
              data-testid="table-graph-zoom-in"
              onClick={() => zoomBy(ZOOM_STEP_IN)}
            />
            <Button size="small" data-testid="table-graph-reset" onClick={reset}>复位</Button>
          </Space>
        </div>
      </header>

      {graph?.truncated && (
        <Alert
          type="warning"
          showIcon
          title={`数据表超过 500 张，仅展示排序靠前的 500 张（共 ${graph.total} 张）${
            graph.edges_out_of_view ? `；另有 ${graph.edges_out_of_view} 条关联指向未展示的表` : ''
          }`}
          style={{ marginBottom: SPACE.lg }}
          data-testid="table-graph-truncated-alert"
        />
      )}
      {focusMissing && (
        <Alert
          type="warning"
          showIcon
          title="作为中心的表不在当前图谱范围内（可能已删除或超出节点上限），已显示全图"
          action={
            <Button size="small" data-testid="table-graph-clear-focus" onClick={() => setFocus(null)}>
              回到全图
            </Button>
          }
          style={{ marginBottom: SPACE.lg }}
        />
      )}
      {graphQuery.isError && <Alert type="error" showIcon message="关联图加载失败" />}

      <div className="cn-tgraph-toolbar" data-testid="table-graph-filter-bar">
        <Input
          allowClear
          size="small"
          placeholder="按表名筛选"
          prefix={<FilterOutlined />}
          value={filters.keyword}
          data-testid="table-graph-filter-keyword"
          onChange={e => setFilters(prev => ({ ...prev, keyword: e.target.value }))}
          style={{ width: 200 }}
        />
        <Checkbox
          checked={filters.onlyIsolated}
          data-testid="table-graph-filter-isolated"
          onChange={e => setFilters(prev => ({ ...prev, onlyIsolated: e.target.checked }))}
        >
          只看孤立表
        </Checkbox>
        <Checkbox
          checked={filters.onlyExternal}
          data-testid="table-graph-filter-external"
          onChange={e => setFilters(prev => ({ ...prev, onlyExternal: e.target.checked }))}
        >
          只看外部关联
        </Checkbox>
        <Checkbox
          checked={filters.onlySelfLoop}
          data-testid="table-graph-filter-selfloop"
          onChange={e => setFilters(prev => ({ ...prev, onlySelfLoop: e.target.checked }))}
        >
          只看自关联
        </Checkbox>
        {focusId != null && (
          <Tag closable data-testid="table-graph-focus-tag" onClose={() => setFocus(null)}>
            中心：{nodeNameById(focusId) || `#${focusId}`} · {focusDepth} 跳
          </Tag>
        )}
      </div>

      <div className="cn-tgraph-body">
        <div className="cn-tgraph-canvas-wrap">
          <div
            ref={containerRef}
            data-testid="table-graph-canvas"
            className="cn-tgraph-canvas"
            style={{
              width: '100%',
              height: 'min(72vh, 720px)',
              minHeight: 420,
            }}
          />
          <div className="cn-tgraph-legend" data-testid="table-graph-legend">
            {legend.map(([key, label]) => {
              const off = hiddenGroups.has(key ?? -0)
              return (
                <button
                  key={String(key)}
                  type="button"
                  className={`cn-tgraph-legend-item${off ? ' cn-tgraph-legend-item-off' : ''}`}
                  data-testid={`table-graph-legend-${key ?? 'none'}`}
                  aria-pressed={!off}
                  onClick={() => toggleGroup(key ?? -0)}
                >
                  <span
                    className="cn-tgraph-legend-dot"
                    style={{ background: groupColor({ id: key ?? 0, virtual: key == null || key < 0 } as LinkGraphNode, colors) }}
                  />
                  {label}
                </button>
              )
            })}
            <span className="cn-tgraph-legend-note" data-testid="table-graph-legend-note">
              → 引用方向 · 虚线 = 目标不可见
            </span>
          </div>
        </div>

        <aside className="cn-tgraph-inspector" data-testid="table-graph-inspector">
          {selected ? (
            <div className="cn-tgraph-inspector-detail" data-testid="table-graph-inspector-detail">
              <div className="cn-tgraph-inspector-head">
                <strong data-testid="table-graph-inspector-title">{selected.name}</strong>
                {selected.virtual && <Tag>虚拟聚合</Tag>}
                {selected.self_loop && <Tag>自关联</Tag>}
              </div>
              {selected.description && (
                <Text type="secondary" style={{ fontSize: 'var(--cn-text-xs)' }}>{selected.description}</Text>
              )}
              <div className="cn-tgraph-inspector-meta">
                <Tag>{selected.group_name || '未分组'}</Tag>
                <Text type="secondary" style={{ fontSize: 'var(--cn-text-xs)' }}>
                  字段 {selected.field_count} · 关联 {degrees.get(selected.id) ?? 0} 条
                </Text>
              </div>
              <div className="cn-tgraph-inspector-section">
                <Text type="secondary" style={{ fontSize: 'var(--cn-text-xs)' }}>
                  引用了 {selectionLinks.out.length} 张表
                </Text>
                {selectionLinks.out.length === 0 ? (
                  <Text type="secondary" style={{ fontSize: 'var(--cn-text-xs)' }}>（无）</Text>
                ) : (
                  <ul className="cn-tgraph-inspector-list">
                    {selectionLinks.out.map(edge => (
                      <li key={`out-${edge.id}`} data-testid={`table-graph-edge-${edge.id}`}>
                        <a
                          onClick={() => focusNode(edge.target)}
                          role="button"
                          tabIndex={0}
                          onKeyDown={e => { if (e.key === 'Enter') focusNode(edge.target) }}
                        >
                          {nodeNameById(edge.target) || `#${edge.target}`}
                        </a>
                        <Text type="secondary" style={{ fontSize: 'var(--cn-text-xs)' }}>
                          {` via「${edge.field_name}」`}
                        </Text>
                        {edge.target_state !== 'ok' && <Tag color="warning">{TARGET_STATE_LABELS[edge.target_state]}</Tag>}
                        {edge.can_edit && (
                          <Space size={2}>
                            <Button
                              type="text"
                              size="small"
                              icon={<EditOutlined />}
                              aria-label="编辑关联"
                              data-testid={`table-graph-edge-edit-${edge.id}`}
                              onClick={() => openEdgeEditor(edge)}
                            />
                            <Popconfirm
                              title="删除这条关联？"
                              description="会一并删除该字段承载的全部关联数据，且不可撤销。"
                              okText="删除"
                              cancelText="取消"
                              okButtonProps={{ danger: true }}
                              onConfirm={() => deleteEdge.mutate(edge)}
                            >
                              <Button
                                type="text"
                                size="small"
                                danger
                                icon={<DeleteOutlined />}
                                aria-label="删除关联"
                                data-testid={`table-graph-edge-delete-${edge.id}`}
                              />
                            </Popconfirm>
                          </Space>
                        )}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
              <div className="cn-tgraph-inspector-section">
                <Text type="secondary" style={{ fontSize: 'var(--cn-text-xs)' }}>
                  被引用（{selectionLinks.in.length} 张表）
                </Text>
                {selectionLinks.in.length === 0 ? (
                  <Text type="secondary" style={{ fontSize: 'var(--cn-text-xs)' }}>（无）</Text>
                ) : (
                  <ul className="cn-tgraph-inspector-list">
                    {selectionLinks.in.map(edge => (
                      <li key={`in-${edge.id}`}>
                        <a
                          onClick={() => focusNode(edge.source)}
                          role="button"
                          tabIndex={0}
                          onKeyDown={e => { if (e.key === 'Enter') focusNode(edge.source) }}
                        >
                          {nodeNameById(edge.source) || `#${edge.source}`}
                        </a>
                        <Text type="secondary" style={{ fontSize: 'var(--cn-text-xs)' }}>
                          {` via「${edge.field_name}」`}
                        </Text>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
              <Space wrap size={SPACE.xs}>
                <Button
                  size="small"
                  type="primary"
                  data-testid="table-graph-inspector-open"
                  disabled={selected.virtual || selected.id <= 0}
                  onClick={() => openTable(selected)}
                >
                  打开表
                </Button>
                <Button
                  size="small"
                  icon={<LinkOutlined />}
                  data-testid="table-graph-inspector-connect"
                  disabled={selected.virtual || selected.id <= 0 || !selected.can_edit}
                  onClick={() => startConnect(selected)}
                >
                  从此表连线
                </Button>
                <Button
                  size="small"
                  icon={<AimOutlined />}
                  data-testid="table-graph-inspector-focus"
                  disabled={selected.virtual || selected.id <= 0}
                  onClick={() => setFocus(selected.id, focusDepth)}
                >
                  设为中心
                </Button>
                <Button
                  size="small"
                  icon={<CopyOutlined />}
                  data-testid="table-graph-inspector-copy"
                  onClick={() => void copyShareLink()}
                >
                  复制链接
                </Button>
              </Space>
            </div>
          ) : (
            <div className="cn-tgraph-overview" data-testid="table-graph-overview">
              <div className="cn-tgraph-inspector-section">
                <Text type="secondary" style={{ fontSize: 'var(--cn-text-xs)' }}>
                  孤立表 {isolated.length}（没有任何关联）
                </Text>
                {isolated.length === 0 ? (
                  <Text type="secondary" style={{ fontSize: 'var(--cn-text-xs)' }}>（全都有连接）</Text>
                ) : (
                  <ul className="cn-tgraph-inspector-list" data-testid="table-graph-isolated-list">
                    {isolated.slice(0, HUB_TOP_N * 2).map(node => (
                      <li key={`iso-${node.id}`}>
                        <Tooltip title="点击定位">
                          <a
                            onClick={() => focusNode(node.id)}
                            role="button"
                            tabIndex={0}
                            onKeyDown={e => { if (e.key === 'Enter') focusNode(node.id) }}
                          >
                            {nodeLabel(node.name)}
                          </a>
                        </Tooltip>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
              <div className="cn-tgraph-inspector-section">
                <Text type="secondary" style={{ fontSize: 'var(--cn-text-xs)' }}>
                  枢纽表 top {Math.min(HUB_TOP_N, hubs.length)}
                </Text>
                {hubs.length === 0 ? (
                  <Text type="secondary" style={{ fontSize: 'var(--cn-text-xs)' }}>（暂无关联）</Text>
                ) : (
                  <ul className="cn-tgraph-inspector-list" data-testid="table-graph-hub-list">
                    {hubs.map(node => (
                      <li key={`hub-${node.id}`}>
                        <a
                          onClick={() => focusNode(node.id)}
                          role="button"
                          tabIndex={0}
                          onKeyDown={e => { if (e.key === 'Enter') focusNode(node.id) }}
                        >
                          {nodeLabel(node.name)}
                        </a>
                        <Text type="secondary" style={{ fontSize: 'var(--cn-text-xs)' }}>
                          {' '}{degrees.get(node.id) ?? 0}
                        </Text>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </div>
          )}
        </aside>
      </div>

      {/* E4：连线中态提示条——明确当前在「选目标」，并提供退出 */}
      {connectFrom && !pendingTarget && (
        <Alert
          type="info"
          showIcon
          data-testid="table-graph-connect-hint"
          message={`正在从「${connectFrom.name}」连线：点另一个表作为目标，按 ESC 取消`}
          action={
            <Button size="small" data-testid="table-graph-connect-cancel" onClick={cancelConnect}>
              取消
            </Button>
          }
          style={{ marginBottom: SPACE.lg }}
        />
      )}

      {/* E1：命名并确认建边 */}
      <Modal
        open={pendingTarget != null}
        title="建立关联"
        okText="建立"
        cancelText="取消"
        confirmLoading={createEdge.isPending}
        onCancel={() => setPendingTarget(null)}
        onOk={() => {
          if (!connectFrom || !pendingTarget) return
          form
            .validateFields()
            .then(values =>
              createEdge.mutate({
                sourceId: connectFrom.id,
                targetId: pendingTarget.id,
                name: String(values.name ?? '').trim(),
                multiple: Boolean(values.multiple),
              }),
            )
            .catch(() => undefined)
        }}
        destroyOnHidden
      >
        <Form form={form} layout="vertical" preserve={false}>
          <Form.Item label="源表">
            <Input value={connectFrom?.name ?? ''} disabled data-testid="table-graph-connect-source" />
          </Form.Item>
          <Form.Item label="目标表">
            <Input value={pendingTarget?.name ?? ''} disabled data-testid="table-graph-connect-target" />
          </Form.Item>
          <Form.Item
            name="name"
            label="关联字段名"
            rules={[{ required: true, message: '请填写关联字段名' }]}
            extra="这是源表上的字段名，需在源表内唯一"
          >
            <Input placeholder="例如：所属项目" data-testid="table-graph-connect-name" />
          </Form.Item>
          <Form.Item name="multiple" label="允许多选" valuePropName="checked" extra="勾选后一个单元格可关联多行目标数据">
            <Switch data-testid="table-graph-connect-multiple" />
          </Form.Item>
        </Form>
      </Modal>

      {/* E2 / E2′：编辑已有边（名字 / 多选 / 目标表） */}
      <Modal
        open={editingEdge != null}
        title="编辑关联"
        okText="保存"
        cancelText="取消"
        confirmLoading={updateEdge.isPending || updateEdgeForce.isPending}
        onCancel={() => setEditingEdge(null)}
        onOk={() => {
          if (!editingEdge) return
          form
            .validateFields()
            .then(values => {
              const targetId = Number(values.targetId)
              const payload = {
                edge: editingEdge,
                name: String(values.name ?? '').trim(),
                multiple: Boolean(values.multiple),
                targetId,
              }
              // D7：改目标表可能失效既有取值，后端首次会 400，确认后带 force 重试
              if (targetId !== editingEdge.target) {
                updateEdgeForce.mutate(payload)
              } else {
                updateEdge.mutate(payload)
              }
            })
            .catch(() => undefined)
        }}
        destroyOnHidden
      >
        <Form form={form} layout="vertical" preserve={false}>
          <Form.Item
            name="name"
            label="关联字段名"
            rules={[{ required: true, message: '请填写关联字段名' }]}
          >
            <Input data-testid="table-graph-edge-name" />
          </Form.Item>
          <Form.Item
            name="targetId"
            label="关联目标表"
            extra="改成另一张表会让指向旧目标行的关联失效，保存时会先给出影响面"
          >
            <Select
              showSearch
              optionFilterProp="label"
              data-testid="table-graph-edge-target"
              options={connectTargets.map(node => ({ label: node.name, value: node.id }))}
            />
          </Form.Item>
          <Form.Item name="multiple" label="允许多选" valuePropName="checked">
            <Switch data-testid="table-graph-edge-multiple" />
          </Form.Item>
        </Form>
      </Modal>

      <Text type="secondary" style={{ fontSize: 'var(--cn-text-xs)' }} data-testid="table-graph-footer-stats">
        显示 {visible.nodes.length} / 共 {graph?.nodes?.length ?? 0} 个节点 · 关联 {visible.edges.length}
        {hiddenCount > 0 ? `（隐藏 ${hiddenCount}）` : ''}（拖拽平移，滚轮缩放，悬停高亮关联）
      </Text>
    </div>
  )
}
