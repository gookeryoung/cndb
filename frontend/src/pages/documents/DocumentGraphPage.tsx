/** 文档知识图谱页（需求 0168 首版 / 需求 0182 图谱探索器）.
 *
 * 用 echarts graph + layout=force 呈现工作区文档的 [[双链]] 关系。
 * 本页由 App.tsx 动态 import（H31），echarts 不进首屏 bundle。
 * 节点取自 /links/graph（后端已按 H33 过滤可见性），断链/歧义按语义区分样式。
 *
 * 需求 0182 在前述基础上补：
 * - C3 局部图 `?focus=<docId>&depth=1|2`（前端 BFS，不新增接口）
 * - C5 筛选栏（关键词 / 格式 / 状态 / 只看断链 / 只看孤立点）+ 页脚「显示 X / 共 Y」
 * - C6 单击选中 + 右侧 Inspector，**双击**才进入文档（原单击即跳转下线）
 * - C7 图例按格式着色可点击显隐，标签按缩放倍率淡化
 * - C8 孤岛 / 枢纽清单，点击选中并高亮其邻接
 * - C9 力参数面板（repulsion / edgeLength / gravity）+ 恢复默认
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Alert, App as AntApp, Button, Checkbox, Input, Select, Slider, Space, Tag, Tooltip, Typography } from 'antd'
import {
  AimOutlined,
  ApartmentOutlined,
  CopyOutlined,
  FilterOutlined,
  MinusOutlined,
  PlusOutlined,
} from '@ant-design/icons'
import * as echarts from 'echarts/core'
import { GraphChart } from 'echarts/charts'
import { TooltipComponent } from 'echarts/components'
import { LabelLayout } from 'echarts/features'
import { SVGRenderer } from 'echarts/renderers'
import type { EChartsCoreOption, EChartsType } from 'echarts/core'

import { documentsApi } from '@/api/documents'
import type { GraphEdge, GraphNode } from '@/api/documents'
import { DOC_FORMAT_META, formatMeta } from '@/components/Document/docFormat'
import { STATUS_LABELS } from './documentDisplay'
import { useTheme } from '@/theme/ThemeProvider'
import { SPACE } from '@/theme/tokens'
import { copyText } from '@/utils/clipboard'

// LabelLayout 让 labelLayout.hideOverlap 生效：节点密集时自动丢弃互相压盖的标签，
// 这是「显示效果差」的主要来源之一（标签糊成一团）。
echarts.use([GraphChart, TooltipComponent, LabelLayout, SVGRenderer])

const { Text } = Typography

/** 缩放档位：与桌面图形类应用一致，单次 ±25%，范围 0.25×–4× */
const ZOOM_STEP_IN = 1.25
const ZOOM_STEP_OUT = 0.8
const ZOOM_MIN = 0.25
const ZOOM_MAX = 4

/** 标签淡化阈值（C7）：低于该倍率时标签整体隐藏，避免缩小后糊成一片 */
const LABEL_ZOOM_THRESHOLD = 0.6

/** 箭头淡化阈值（C7）：比标签更早收起，缩小后先丢的是细节噪声 */
const ARROW_ZOOM_THRESHOLD = 0.4

/** 边箭头尺寸：series 级与逐边覆盖共用同一常量 */
const EDGE_SYMBOL_SIZE = 7
/** 枢纽清单取度数的前 N 个（C8） */
const HUB_TOP_N = 10

/** 局部图最大深度（C3）：1 跳是直接引用关系，2 跳已经接近全图噪声 */
const MAX_FOCUS_DEPTH = 2

export interface ForceParams {
  repulsion: number
  edgeLength: number
  gravity: number
}

const DEFAULT_FORCE: ForceParams = { repulsion: 180, edgeLength: 100, gravity: 0.08 }

/** 节点标题过长时省略，避免力导向图标签互相压盖 */
// 标题可能缺失（异常响应 / 空标题文档）：先兜底再取长度，否则 undefined.length 会整页崩溃。
function nodeLabel(title: string | null | undefined): string {
  const text = typeof title === 'string' && title ? title : '未命名文档'
  return text.length > 18 ? `${text.slice(0, 17)}…` : text
}

/** echarts 的 SVG 属性不解析 CSS 变量：与 ChartView 同口径，先读计算值再注入 option. */
interface ThemeColors {
  border: string
  text: string
  error: string
  warning: string
  primary: string
}

function readThemeColors(): ThemeColors {
  const read = (name: string, fallback: string): string => {
    if (typeof document === 'undefined') return fallback
    const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
    return value || fallback
  }
  return {
    border: read('--cn-border', '#e5e7eb'),
    text: read('--cn-text-primary', '#1f2937'),
    error: read('--cn-error', '#cf1322'),
    warning: read('--cn-warning', '#faad14'),
    primary: read('--cn-primary', '#2563eb'),
  }
}

/** 节点所属格式键：文件夹与断链优先，其余按 content_type */
function formatKey(node: GraphNode): string {
  if (node.broken) return 'broken'
  if (node.is_folder) return 'folder'
  const key = (node.content_type ?? '').toLowerCase()
  return DOC_FORMAT_META[key] ? key : 'markdown'
}

function formatColor(node: GraphNode, colors: ThemeColors): string {
  if (node.broken) return colors.error
  if (node.is_folder) return colors.warning
  const color = DOC_FORMAT_META[node.content_type]?.color ?? DOC_FORMAT_META.markdown.color
  // 格式映射里 folder 等个别项是 var(--cn-*)，SVG 属性无法解析，回退到已读取的主色
  return color.startsWith('var(') ? colors.primary : color
}

/** 图例项：格式键 → 展示名，颜色同一取 formatColor，避免图例与节点两套色 */
function legendLabel(key: string): string {
  if (key === 'broken') return '断链'
  return DOC_FORMAT_META[key]?.label ?? formatMeta(key).label
}

function legendColor(key: string, colors: ThemeColors): string {
  if (key === 'broken') return colors.error
  if (key === 'folder') return colors.warning
  const color = DOC_FORMAT_META[key]?.color ?? DOC_FORMAT_META.markdown.color
  return color.startsWith('var(') ? colors.primary : color
}

/** 节点度数：同类应用按连接数放大节点，孤立文档保持小尺寸，一眼能看出枢纽与孤岛 */
function buildDegrees(nodes: GraphNode[], edges: GraphEdge[]): Map<number, number> {
  const degree = new Map<number, number>()
  for (const node of nodes) degree.set(node.id, 0)
  for (const edge of edges) {
    if (degree.has(edge.source)) degree.set(edge.source, (degree.get(edge.source) ?? 0) + 1)
    if (degree.has(edge.target)) degree.set(edge.target, (degree.get(edge.target) ?? 0) + 1)
  }
  return degree
}

/** 折叠互引后的画布边：`mutual` 决定画两端箭头，`reverseRaw` 是反向那条边的原始写法（C1） */
export interface DisplayEdge extends GraphEdge {
  mutual: boolean
  reverseRaw?: string
}

/** 无序节点对：互引的两条有向边落到同一个键上 */
function pairKey(edge: GraphEdge): string {
  return `${Math.min(edge.source, edge.target)}-${Math.max(edge.source, edge.target)}`
}

/**
 * 互引折叠（C1）：A→B 与 B→A 合成一条画布边，`mutual` 标记双向。
 * 只折叠方向相反的成对边；同向重复边（后端已去重，防御性保留）仍各自成线。
 * 折叠只作用于画布与聚合计数，`visible.edges` 的有向明细仍供 Inspector 使用（D6）。
 */
export function foldReciprocal(edges: GraphEdge[]): DisplayEdge[] {
  const folded: DisplayEdge[] = []
  const indexByKey = new Map<string, number>()
  for (const edge of edges) {
    const key = pairKey(edge)
    const at = indexByKey.get(key)
    if (at == null) {
      indexByKey.set(key, folded.length)
      folded.push({ ...edge, mutual: false })
      continue
    }
    const previous = folded[at]
    const reverse = previous.source === edge.target && previous.target === edge.source && edge.source !== edge.target
    const next: DisplayEdge = {
      ...previous,
      // 断链 / 同名多文档：任一方向成立即整体成立，折叠后只有一条线可着色
      broken: previous.broken || edge.broken,
      ambiguous: previous.ambiguous || edge.ambiguous,
      mutual: previous.mutual || reverse,
    }
    if (reverse) next.reverseRaw = edge.raw
    folded[at] = next
  }
  return folded
}

/** 度数 → 直径：12px 起步，按 log 缓增到 40px，避免单个超级枢纽吃掉整张画布 */
function nodeSize(node: GraphNode, degree: number): number {
  const base = node.broken ? 18 : 14
  const scaled = base + Math.log2(degree + 1) * 8
  return Math.round(Math.min(40, scaled))
}

/**
 * 局部图扩邻（C3）：从中心节点按无向邻接做 BFS，深度 1–2。
 * 无向而非有向：出链与反链在「谁和谁相关」上是等价的，只取出链会漏掉被引用的一方。
 */
export function collectNeighborhood(
  edges: GraphEdge[],
  focusId: number,
  depth: number,
): Set<number> {
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
  statuses: string[]
  onlyBroken: boolean
  onlyIsolated: boolean
}

const EMPTY_FILTERS: GraphFilters = {
  keyword: '',
  statuses: [],
  onlyBroken: false,
  onlyIsolated: false,
}

interface FilterDeps {
  /** 中心节点集（C3 局部图）；null 表示全图 */
  scope: Set<number> | null
  /** 被图例关掉的格式键（C7） */
  hiddenFormats: Set<string>
  degrees: Map<number, number>
}

/** 一次遍历同时算可见节点与「两端都可见」的边：边不能只按源筛选，否则会挂到画布外 */
export function filterGraph(
  nodes: GraphNode[],
  edges: GraphEdge[],
  filters: GraphFilters,
  deps: FilterDeps,
): { nodes: GraphNode[]; edges: GraphEdge[] } {
  const keyword = filters.keyword.trim().toLowerCase()
  const kept = nodes.filter(node => {
    if (deps.scope && !deps.scope.has(node.id)) return false
    if (deps.hiddenFormats.has(formatKey(node))) return false
    if (keyword && !node.title.toLowerCase().includes(keyword)) return false
    if (filters.statuses.length > 0 && !node.broken && !filters.statuses.includes(node.status)) return false
    if (filters.onlyBroken && !node.broken) return false
    if (filters.onlyIsolated && (deps.degrees.get(node.id) ?? 0) > 0) return false
    return true
  })
  const ids = new Set(kept.map(node => node.id))
  if (filters.onlyBroken) {
    // 断链节点本身没有「出自己的边」，若只留断链节点，画出来是一堆孤点。
    // 保留「指向它的那条边」的源节点，用户才能看出是谁引用错了。
    const sourceIds = new Set<number>()
    for (const edge of edges) {
      if (ids.has(edge.target) && !ids.has(edge.source)) sourceIds.add(edge.source)
    }
    const sourceNodes = nodes.filter(node => sourceIds.has(node.id))
    const all = new Set<number>([...ids, ...sourceIds])
    return {
      nodes: [...kept, ...sourceNodes],
      edges: edges.filter(edge => all.has(edge.source) && all.has(edge.target)),
    }
  }
  return { nodes: kept, edges: edges.filter(edge => ids.has(edge.source) && ids.has(edge.target)) }
}

/** 孤岛：度数为 0 且不是断链（断链天然没有边，混进来会淹没真正的孤岛） */
export function findIsolated(nodes: GraphNode[], degrees: Map<number, number>): GraphNode[] {
  return nodes.filter(node => !node.broken && (degrees.get(node.id) ?? 0) === 0)
}

/** 枢纽：按度数倒序取前 N，度数为 0 的不能算枢纽 */
export function findHubs(
  nodes: GraphNode[],
  degrees: Map<number, number>,
  limit = HUB_TOP_N,
): GraphNode[] {
  return nodes
    .filter(node => !node.broken && (degrees.get(node.id) ?? 0) > 0)
    .sort((a, b) => (degrees.get(b.id) ?? 0) - (degrees.get(a.id) ?? 0) || a.id - b.id)
    .slice(0, limit)
}

function buildOption(
  nodes: GraphNode[],
  edges: DisplayEdge[],
  colors: ThemeColors,
  force: ForceParams,
): EChartsCoreOption {
  const degree = buildDegrees(nodes, edges)
  return {
    animationDuration: 300,
    // 力导向布局在空中飘：收敛后停住，交互时才继续，避免整页一直抖动
    tooltip: {
      trigger: 'item',
      confine: true,
      formatter: (params: { dataType?: string; data?: GraphNode | (GraphEdge & { name?: string }) }) => {
        const data = params.data
        if (params.dataType === 'edge') {
          const edge = data as DisplayEdge
          const raw = edge.reverseRaw ? `${edge.raw} ⇄ ${edge.reverseRaw}` : edge.raw
          const hints = [
            ...(edge.broken ? ['断链'] : []),
            ...(edge.ambiguous ? ['同名多文档，指向首个'] : []),
            ...(edge.mutual ? ['互相引用'] : []),
          ]
          return `${raw || '双链引用'}${hints.length ? `（${hints.join('；')}）` : ''}`
        }
        const node = data as GraphNode
        const suffix = node.broken ? '（断链目标）' : node.is_folder ? '（文件夹）' : ''
        const links = degree.get(node.id) ?? 0
        return `${nodeLabel(node.title)}${suffix}<br/>关联 ${links} 条`
      },
    },
    series: [
      {
        type: 'graph',
        layout: 'force',
        roam: true,
        draggable: true,
        // 缩放上下限：无限制时滚轮会把图缩成一个点或放大到只剩一个节点
        scaleLimit: { min: ZOOM_MIN, max: ZOOM_MAX },
        // 缩放时节点尺寸变化幅度（1 = 完全随缩放，0 = 尺寸恒定）
        nodeScaleRatio: 0.4,
        force: {
          repulsion: force.repulsion,
          edgeLength: force.edgeLength,
          gravity: force.gravity,
          friction: 0.2,
        },
        // formatter 的 params.data 是写进 series.data 的原始项：必须带 title，
        // 只写 name 时 p.data.title 为 undefined（曾经的整页崩溃点）。
        label: {
          show: true,
          position: 'right',
          distance: 5,
          formatter: (p: { data: GraphNode }) => nodeLabel(p.data?.title),
          fontSize: 11,
          color: colors.text,
        },
        labelLayout: { hideOverlap: true },
        // 单向：一个箭头指向被引用方；互引折叠成一条线时由逐边 symbol 补成两端箭头（C2）
        edgeSymbol: ['none', 'arrow'],
        edgeSymbolSize: EDGE_SYMBOL_SIZE,
        lineStyle: { curveness: 0.06, opacity: 0.55, width: 1.2 },
        data: nodes.map(node => ({
          id: String(node.id),
          name: node.title,
          title: node.title,
          value: node.id,
          is_folder: node.is_folder,
          itemStyle: {
            color: formatColor(node, colors),
            borderColor: colors.border,
            borderWidth: 1,
            opacity: 0.95,
          },
          symbolSize: nodeSize(node, degree.get(node.id) ?? 0),
          broken: node.broken,
        })),
        links: edges.map(edge => ({
          source: String(edge.source),
          target: String(edge.target),
          // link 级 symbol 逐条覆盖 series 默认：两端箭头即互引（C2），无需拆第二个 series（D2）
          ...(edge.mutual ? { symbol: ['arrow', 'arrow'] } : {}),
          lineStyle: {
            color: edge.broken ? colors.error : colors.border,
            type: edge.broken ? 'dashed' : 'solid',
            width: edge.broken ? 1 : 1.2,
            opacity: edge.broken ? 0.75 : 0.55,
            curveness: 0.06,
          },
          broken: edge.broken,
          ambiguous: edge.ambiguous,
          raw: edge.raw,
          reverseRaw: edge.reverseRaw,
          mutual: edge.mutual,
        })),
        // 悬停一个节点时压暗无关部分，只看它的邻接关系
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

export default function DocumentGraphPage() {
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
  const [hiddenFormats, setHiddenFormats] = useState<Set<string>>(() => new Set())
  const [force, setForce] = useState<ForceParams>(DEFAULT_FORCE)
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [showLabels, setShowLabels] = useState(true)
  const [showArrows, setShowArrows] = useState(true)

  const graphQuery = useQuery({
    queryKey: ['document-link-graph', workspaceId],
    queryFn: () => documentsApi.linkGraph(workspaceId),
  })
  const graph = graphQuery.data
  const nodes = useMemo(() => graph?.nodes ?? [], [graph])
  const edges = useMemo(() => graph?.edges ?? [], [graph])

  /** 中心文档（C3）：URL 即状态，刷新与分享都能复现同一张局部图 */
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

  /** 度数按折叠后的唯一关联数算（C3）：互引只算一条线，读数与画布才不打架（D3） */
  const folded = useMemo(() => foldReciprocal(edges), [edges])
  const degrees = useMemo(() => buildDegrees(nodes, folded), [nodes, folded])
  const scope = useMemo(
    () => (focusId != null ? collectNeighborhood(edges, focusId, focusDepth) : null),
    [edges, focusId, focusDepth],
  )
  /** 中心文档不在图里（已删除 / 超出 500 上限）：不能静默画全图，否则用户以为在看局部图 */
  const focusMissing = focusId != null && nodes.length > 0 && !nodes.some(n => n.id === focusId)

  const visible = useMemo(
    () => filterGraph(nodes, edges, filters, { scope, hiddenFormats, degrees }),
    [nodes, edges, filters, scope, hiddenFormats, degrees],
  )

  /** 画布与关系计数都走折叠后的边（C1/C4）；Inspector 仍读 `visible.edges` 的有向明细 */
  const displayEdges = useMemo(() => foldReciprocal(visible.edges), [visible.edges])
  const mutualCount = useMemo(() => displayEdges.filter(edge => edge.mutual).length, [displayEdges])
  /** 折叠后每条线只保留首次出现的朝向：判断某条有向明细是否属互引要两头都比 */
  const mutualPairs = useMemo(
    () => new Set(displayEdges.filter(edge => edge.mutual).map(edge => `${edge.source}-${edge.target}`)),
    [displayEdges],
  )
  const isMutual = useCallback(
    (edge: GraphEdge) => mutualPairs.has(`${edge.source}-${edge.target}`) || mutualPairs.has(`${edge.target}-${edge.source}`),
    [mutualPairs],
  )

  const { mode: themeMode } = useTheme()
  const colors = useMemo(
    () => readThemeColors(),
    // themeMode 进依赖：切换主题后 getComputedStyle 才拿到新的 --cn-* 值
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [themeMode],
  )
  const option = useMemo(
    () => buildOption(visible.nodes, displayEdges, colors, force),
    [visible.nodes, displayEdges, colors, force],
  )

  /** 图例条目按「当前可见图里有出现的格式」生成，避免列出 8 个全没节点的格式 */
  const legend = useMemo(() => {
    const keys = new Set<string>()
    for (const node of nodes) {
      if (scope && !scope.has(node.id)) continue
      keys.add(formatKey(node))
    }
    return ['markdown', 'folder', 'pdf', 'image', 'xlsx', 'pptx', 'mhtml', 'word', 'broken']
      .filter(key => keys.has(key))
  }, [nodes, scope])

  const isolated = useMemo(() => findIsolated(nodes, degrees), [nodes, degrees])
  const hubs = useMemo(() => findHubs(nodes, degrees), [nodes, degrees])

  const selected = useMemo(
    () => visible.nodes.find(node => node.id === selectedId) ?? null,
    [visible.nodes, selectedId],
  )

  /** 选中节点的出链 / 入链都从当前图推导：图外的边本来也看不见，不额外打接口 */
  const selectionLinks = useMemo(() => {
    if (!selected) return { out: [] as GraphEdge[], in: [] as GraphEdge[] }
    return {
      out: visible.edges.filter(edge => edge.source === selected.id),
      in: visible.edges.filter(edge => edge.target === selected.id),
    }
  }, [visible.edges, selected])

  /** 选中项被筛掉时清空，否则 Inspector 会显示一个画布上根本不存在的文档 */
  useEffect(() => {
    if (selectedId != null && !visible.nodes.some(node => node.id === selectedId)) setSelectedId(null)
  }, [visible.nodes, selectedId])

  const syncZoomPct = useCallback(() => {
    setZoomPct(Math.round(zoomRef.current * 100))
  }, [])

  const nodeTitleById = useCallback(
    (id: number) => nodes.find(node => node.id === id)?.title ?? '',
    [nodes],
  )

  /**
   * 以画布中心为锚点缩放。
   * echarts 的 graphRoam 是「相对增量」语义：zoom 与当前倍率相乘，且 originX/originY
   * 缺失时会以 (0,0) 为锚点（左上角），表现为缩放时整张图往一个角飞出去。
   * 必须显式带上视口中心坐标。
   */
  const zoomBy = useCallback(
    (factor: number) => {
      const chart = chartRef.current
      if (!chart) return
      const box = containerRef.current
      const originX = (box?.clientWidth ?? 0) / 2
      const originY = (box?.clientHeight ?? 0) / 2
      const next = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, zoomRef.current * factor))
      // 已到上下限时不再派发，避免倍率读数与实际视图脱节
      if (next === zoomRef.current) return
      zoomRef.current = next
      chart.dispatchAction({ type: 'graphRoam', zoom: factor, originX, originY })
      syncZoomPct()
    },
    [syncZoomPct],
  )

  useEffect(() => {
    if (!containerRef.current || !graph) return
    const chart = echarts.init(containerRef.current, undefined, { renderer: 'svg' })
    chartRef.current = chart
    // 单击只选中：图谱里点错一下就跳走是首版最被诟病的交互（需求 0182 C6）
    chart.on('click', params => {
      if (params.dataType !== 'node') return
      const data = params.data as { value?: number } | null
      const docId = data?.value
      if (typeof docId !== 'number') return
      setSelectedId(docId)
    })
    chart.on('dblclick', params => {
      if (params.dataType !== 'node') return
      const data = params.data as { value?: number; is_folder?: boolean } | null
      const docId = data?.value
      if (typeof docId !== 'number' || docId <= 0) return  // 断链虚拟节点（负 id）不进文档
      if (data?.is_folder) navigate(`/w/${workspaceId}/documents?parent=${docId}`)
      else navigate(`/w/${workspaceId}/documents/${docId}`)
    })
    // 滚轮 / 拖拽缩放由 RoamController 直接改视图，这里同步倍率读数。
    // getOption() 的返回类型是松散的 {}，取 series[0].zoom 需显式收窄。
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
    chartRef.current?.setOption(option, true)
  }, [option])

  /**
   * 标签与箭头的显隐单独下发：把它们塞进主 option 会让每次缩放都 notMerge 重建，
   * 力导向布局随之重排，画布会「跳」一下。两者合成一次下发，互不覆盖。
   */
  const labelsVisible = showLabels && zoomPct >= LABEL_ZOOM_THRESHOLD * 100
  // 箭头比标签更早收起（C7）：缩小后先丢的是细节噪声
  const arrowsVisible = showArrows && zoomPct >= ARROW_ZOOM_THRESHOLD * 100
  useEffect(() => {
    chartRef.current?.setOption({
      series: [{
        label: { show: labelsVisible },
        edgeSymbol: arrowsVisible ? ['none', 'arrow'] : 'none',
        edgeSymbolSize: arrowsVisible ? EDGE_SYMBOL_SIZE : 0,
      }],
    })
  }, [labelsVisible, arrowsVisible, option])

  /** 复位：'restore' 会把 option 重置回初始提交态，同时让力导向重新收敛 */
  const reset = useCallback(() => {
    zoomRef.current = 1
    syncZoomPct()
    chartRef.current?.dispatchAction({ type: 'restore' })
  }, [syncZoomPct])

  /** 定位到某个节点：echarts 没有「把节点移到中心」的公开能力，用它自带的邻接聚焦代替 */
  const focusNode = useCallback((nodeId: number) => {
    setSelectedId(nodeId)
    const dataIndex = (chartRef.current?.getOption() as { series?: { data?: unknown[] }[] } | undefined)
      ?.series?.[0]?.data
    const index = Array.isArray(dataIndex) ? dataIndex.findIndex((item) => (item as { value?: number })?.value === nodeId) : -1
    if (index >= 0) {
      chartRef.current?.dispatchAction({ type: 'focusNodeAdjacency', seriesIndex: 0, dataIndex: index })
    }
  }, [])

  const setFocus = useCallback(
    (docId: number | null, depth = 1) => {
      const next = new URLSearchParams(searchParams)
      if (docId == null) next.delete('focus')
      else next.set('focus', String(docId))
      if (docId != null) next.set('depth', String(depth))
      else next.delete('depth')
      setSearchParams(next, { replace: true })
    },
    [searchParams, setSearchParams],
  )

  const copyShareLink = useCallback(async () => {
    if (!selected) return
    if (typeof window === 'undefined') return
    const link = `${window.location.origin}/w/${workspaceId}/documents/graph?focus=${selected.id}&depth=1`
    if (await copyText(link)) message.success('已复制图谱链接')
  }, [selected, workspaceId, message])

  const toggleFormat = useCallback((key: string) => {
    setHiddenFormats(prev => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }, [])

  const openDocument = useCallback(
    (node: GraphNode) => {
      if (node.broken || node.id <= 0) return
      if (node.is_folder) navigate(`/w/${workspaceId}/documents?parent=${node.id}`)
      else navigate(`/w/${workspaceId}/documents/${node.id}`)
    },
    [navigate, workspaceId],
  )

  const hiddenCount = Math.max(0, (graph?.nodes?.length ?? 0) - visible.nodes.length)

  return (
    <div className="cn-page" data-testid="document-graph-page">
      <header className="cn-page-head">
        <div className="cn-page-head-main">
          <span className="cn-page-head-icon" aria-hidden><ApartmentOutlined /></span>
          <div className="cn-page-head-text">
            <h1 className="cn-page-head-title">知识图谱</h1>
            <div className="cn-page-head-sub">
              工作区内可见文档与 [[双链]] 关系；单击选中、双击进入文档，虚线为断链
            </div>
          </div>
        </div>
        <div className="cn-page-head-actions">
          <Space size={SPACE.sm}>
            <Button
              size="small"
              data-testid="graph-labels-toggle"
              aria-pressed={showLabels}
              onClick={() => setShowLabels(v => !v)}
            >
              {showLabels ? '隐藏标签' : '显示标签'}
            </Button>
            <Button
              size="small"
              data-testid="graph-arrows-toggle"
              aria-pressed={showArrows}
              onClick={() => setShowArrows(v => !v)}
            >
              {showArrows ? '隐藏箭头' : '显示箭头'}
            </Button>
            <Text type="secondary" data-testid="graph-zoom-pct" style={{ fontSize: 'var(--cn-text-xs)' }}>
              {zoomPct}%
            </Text>
            <Button
              size="small"
              icon={<MinusOutlined />}
              aria-label="缩小"
              disabled={zoomPct <= ZOOM_MIN * 100}
              data-testid="graph-zoom-out"
              onClick={() => zoomBy(ZOOM_STEP_OUT)}
            />
            <Button
              size="small"
              icon={<PlusOutlined />}
              aria-label="放大"
              disabled={zoomPct >= ZOOM_MAX * 100}
              data-testid="graph-zoom-in"
              onClick={() => zoomBy(ZOOM_STEP_IN)}
            />
            <Button size="small" data-testid="graph-reset" onClick={reset}>复位</Button>
          </Space>
        </div>
      </header>

      {graph?.truncated && (
        <Alert
          type="warning"
          showIcon
          title={`文档超过 500 个，仅展示最近更新的 500 个（共 ${graph.total} 个）${
            graph.edges_out_of_view
              ? `；另有 ${graph.edges_out_of_view} 条关系指向未展示的文档`
              : ''
          }`}
          style={{ marginBottom: SPACE.lg }}
          data-testid="graph-truncated-alert"
        />
      )}
      {focusMissing && (
        <Alert
          type="warning"
          showIcon
          title="作为中心的文档不在当前图谱范围内（可能已删除或超出节点上限），已显示全图"
          action={
            <Button size="small" data-testid="graph-clear-focus" onClick={() => setFocus(null)}>
              回到全图
            </Button>
          }
          style={{ marginBottom: SPACE.lg }}
        />
      )}
      {graphQuery.isError && <Alert type="error" showIcon message="图谱加载失败" />}

      <div className="cn-graph-toolbar" data-testid="graph-filter-bar">
        <Input
          allowClear
          size="small"
          placeholder="按标题筛选"
          prefix={<FilterOutlined />}
          value={filters.keyword}
          data-testid="graph-filter-keyword"
          onChange={e => setFilters(prev => ({ ...prev, keyword: e.target.value }))}
          style={{ width: 200 }}
        />
        <Select
          allowClear
          size="small"
          mode="multiple"
          placeholder="状态"
          value={filters.statuses}
          data-testid="graph-filter-status"
          onChange={(value: string[]) => setFilters(prev => ({ ...prev, statuses: value }))}
          options={Object.entries(STATUS_LABELS).map(([value, label]) => ({ value, label }))}
          style={{ minWidth: 140 }}
          maxTagCount="responsive"
        />
        <Checkbox
          checked={filters.onlyBroken}
          data-testid="graph-filter-broken"
          onChange={e => setFilters(prev => ({ ...prev, onlyBroken: e.target.checked }))}
        >
          只看断链
        </Checkbox>
        <Checkbox
          checked={filters.onlyIsolated}
          data-testid="graph-filter-isolated"
          onChange={e => setFilters(prev => ({ ...prev, onlyIsolated: e.target.checked }))}
        >
          只看孤立点
        </Checkbox>
        {focusId != null && (
          <Tag closable data-testid="graph-focus-tag" onClose={() => setFocus(null)}>
            中心：{nodeTitleById(focusId) || `#${focusId}`} · {focusDepth} 跳
          </Tag>
        )}
      </div>

      <div className="cn-graph-body">
        <div className="cn-graph-canvas-wrap">
          <div
            ref={containerRef}
            data-testid="document-graph-canvas"
            className="cn-graph-canvas"
            style={{
              width: '100%',
              height: 'min(72vh, 720px)',
              minHeight: 420,
              border: '1px solid var(--cn-border)',
              borderRadius: 'var(--cn-radius-base)',
              background: 'var(--cn-bg-canvas)',
            }}
          />
          <div className="cn-graph-legend" data-testid="graph-legend">
            {legend.map(key => {
              const off = hiddenFormats.has(key)
              return (
                <button
                  key={key}
                  type="button"
                  className={`cn-graph-legend-item${off ? ' cn-graph-legend-item-off' : ''}`}
                  data-testid={`graph-legend-${key}`}
                  aria-pressed={!off}
                  onClick={() => toggleFormat(key)}
                >
                  <span className="cn-graph-legend-dot" style={{ background: legendColor(key, colors) }} />
                  {legendLabel(key)}
                </button>
              )
            })}
            <span className="cn-graph-legend-note" data-testid="graph-legend-edge-direction">
              → 引用 · ⇄ 互引
            </span>
          </div>
          <div className="cn-graph-force" data-testid="graph-force-panel">
            <div className="cn-graph-force-row">
              <Text type="secondary" style={{ fontSize: 'var(--cn-text-xs)' }}>斥力</Text>
              <span style={{ flex: 1 }} data-testid="graph-force-repulsion-wrap">
                <Slider
                  min={40}
                  max={600}
                  step={20}
                  value={force.repulsion}
                  onChange={(value: number) => setForce(prev => ({ ...prev, repulsion: value }))}
                />
              </span>
            </div>
            <div className="cn-graph-force-row">
              <Text type="secondary" style={{ fontSize: 'var(--cn-text-xs)' }}>边长</Text>
              <span style={{ flex: 1 }} data-testid="graph-force-edge-length-wrap">
                <Slider
                  min={40}
                  max={300}
                  step={10}
                  value={force.edgeLength}
                  onChange={(value: number) => setForce(prev => ({ ...prev, edgeLength: value }))}
                />
              </span>
            </div>
            <div className="cn-graph-force-row">
              <Text type="secondary" style={{ fontSize: 'var(--cn-text-xs)' }}>向心</Text>
              <span style={{ flex: 1 }} data-testid="graph-force-gravity-wrap">
                <Slider
                  min={0}
                  max={0.5}
                  step={0.01}
                  value={force.gravity}
                  onChange={(value: number) => setForce(prev => ({ ...prev, gravity: value }))}
                />
              </span>
            </div>
            <Button size="small" data-testid="graph-force-reset" onClick={() => setForce(DEFAULT_FORCE)}>
              恢复默认
            </Button>
          </div>
        </div>

        <aside className="cn-graph-inspector" data-testid="graph-inspector">
          {selected ? (
            <div className="cn-graph-inspector-detail" data-testid="graph-inspector-detail">
              <div className="cn-graph-inspector-head">
                <strong data-testid="graph-inspector-title">{selected.title || '未命名文档'}</strong>
                {selected.broken && <Tag color="error">断链目标</Tag>}
              </div>
              <div className="cn-graph-inspector-meta">
                <Tag>{formatMeta(selected.content_type, selected.is_folder).label}</Tag>
                {!selected.broken && <Tag>{STATUS_LABELS[selected.status] ?? selected.status}</Tag>}
                <Text type="secondary" style={{ fontSize: 'var(--cn-text-xs)' }}>
                  关联 {degrees.get(selected.id) ?? 0} 条
                </Text>
              </div>
              <div className="cn-graph-inspector-section">
                <Text type="secondary" style={{ fontSize: 'var(--cn-text-xs)' }}>出链 {selectionLinks.out.length}</Text>
                {selectionLinks.out.length === 0 ? (
                  <Text type="secondary" style={{ fontSize: 'var(--cn-text-xs)' }}>（无）</Text>
                ) : (
                  <ul className="cn-graph-inspector-list">
                    {selectionLinks.out.map(edge => (
                      <li key={`out-${edge.source}-${edge.target}`}>
                        <a
                          onClick={() => focusNode(edge.target)}
                          role="button"
                          tabIndex={0}
                          onKeyDown={e => { if (e.key === 'Enter') focusNode(edge.target) }}
                        >
                          {nodeTitleById(edge.target) || edge.raw || `#${edge.target}`}
                        </a>
                        {edge.broken && <Tag color="error">断链</Tag>}
                        {isMutual(edge) && <Tag>⇄ 互引</Tag>}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
              <div className="cn-graph-inspector-section">
                <Text type="secondary" style={{ fontSize: 'var(--cn-text-xs)' }}>反链 {selectionLinks.in.length}</Text>
                {selectionLinks.in.length === 0 ? (
                  <Text type="secondary" style={{ fontSize: 'var(--cn-text-xs)' }}>（无）</Text>
                ) : (
                  <ul className="cn-graph-inspector-list">
                    {selectionLinks.in.map(edge => (
                      <li key={`in-${edge.source}-${edge.target}`}>
                        <a
                          onClick={() => focusNode(edge.source)}
                          role="button"
                          tabIndex={0}
                          onKeyDown={e => { if (e.key === 'Enter') focusNode(edge.source) }}
                        >
                          {nodeTitleById(edge.source) || `#${edge.source}`}
                        </a>
                        {isMutual(edge) && <Tag>⇄ 互引</Tag>}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
              <Space wrap size={SPACE.xs}>
                <Button
                  size="small"
                  type="primary"
                  data-testid="graph-inspector-open"
                  disabled={selected.broken || selected.id <= 0}
                  onClick={() => openDocument(selected)}
                >
                  打开文档
                </Button>
                <Button
                  size="small"
                  icon={<AimOutlined />}
                  data-testid="graph-inspector-focus"
                  disabled={selected.broken || selected.id <= 0}
                  onClick={() => setFocus(selected.id, focusDepth)}
                >
                  设为中心
                </Button>
                <Button
                  size="small"
                  icon={<CopyOutlined />}
                  data-testid="graph-inspector-copy"
                  onClick={() => void copyShareLink()}
                >
                  复制链接
                </Button>
              </Space>
            </div>
          ) : (
            <div className="cn-graph-overview" data-testid="graph-overview">
              <div className="cn-graph-inspector-section">
                <Text type="secondary" style={{ fontSize: 'var(--cn-text-xs)' }}>
                  孤立文档 {isolated.length}（无任何双链）
                </Text>
                {isolated.length === 0 ? (
                  <Text type="secondary" style={{ fontSize: 'var(--cn-text-xs)' }}>（全都有连接）</Text>
                ) : (
                  <ul className="cn-graph-inspector-list" data-testid="graph-isolated-list">
                    {isolated.slice(0, HUB_TOP_N * 2).map(node => (
                      <li key={`iso-${node.id}`}>
                        <Tooltip title="点击定位">
                          <a
                            onClick={() => focusNode(node.id)}
                            role="button"
                            tabIndex={0}
                            onKeyDown={e => { if (e.key === 'Enter') focusNode(node.id) }}
                          >
                            {nodeLabel(node.title)}
                          </a>
                        </Tooltip>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
              <div className="cn-graph-inspector-section">
                <Text type="secondary" style={{ fontSize: 'var(--cn-text-xs)' }}>
                  枢纽文档 top {Math.min(HUB_TOP_N, hubs.length)}
                </Text>
                {hubs.length === 0 ? (
                  <Text type="secondary" style={{ fontSize: 'var(--cn-text-xs)' }}>（暂无连接）</Text>
                ) : (
                  <ul className="cn-graph-inspector-list" data-testid="graph-hub-list">
                    {hubs.map(node => (
                      <li key={`hub-${node.id}`}>
                        <a
                          onClick={() => focusNode(node.id)}
                          role="button"
                          tabIndex={0}
                          onKeyDown={e => { if (e.key === 'Enter') focusNode(node.id) }}
                        >
                          {nodeLabel(node.title)}
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

      <Text type="secondary" style={{ fontSize: 'var(--cn-text-xs)' }} data-testid="graph-footer-stats">
        显示 {visible.nodes.length} / 共 {graph?.nodes?.length ?? 0} 个节点 · 关系 {displayEdges.length}
        {mutualCount > 0 ? `（互引 ${mutualCount}）` : ''}
        {hiddenCount > 0 ? `（隐藏 ${hiddenCount}）` : ''}（拖拽平移，滚轮缩放，悬停高亮关联）
      </Text>
    </div>
  )
}
