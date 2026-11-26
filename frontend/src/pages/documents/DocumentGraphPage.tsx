/** 文档知识图谱页（需求 0168）.
 *
 * 用 echarts graph + layout=force 呈现工作区文档的 [[双链]] 关系。
 * 本页由 App.tsx 动态 import（H31），echarts 不进首屏 bundle。
 * 节点取自 /links/graph（后端已按 H33 过滤可见性），断链/歧义按语义区分样式。
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Alert, Button, Space, Typography } from 'antd'
import { ApartmentOutlined, MinusOutlined, PlusOutlined } from '@ant-design/icons'
import * as echarts from 'echarts/core'
import { GraphChart } from 'echarts/charts'
import { TooltipComponent } from 'echarts/components'
import { LabelLayout } from 'echarts/features'
import { SVGRenderer } from 'echarts/renderers'
import type { EChartsCoreOption, EChartsType } from 'echarts/core'

import { documentsApi } from '@/api/documents'
import type { GraphEdge, GraphNode } from '@/api/documents'
import { DOC_FORMAT_META } from '@/components/Document/docFormat'
import { useTheme } from '@/theme/ThemeProvider'
import { SPACE } from '@/theme/tokens'

// LabelLayout 让 labelLayout.hideOverlap 生效：节点密集时自动丢弃互相压盖的标签，
// 这是「显示效果差」的主要来源之一（标签糊成一团）。
echarts.use([GraphChart, TooltipComponent, LabelLayout, SVGRenderer])

const { Text } = Typography

/** 缩放档位：与桌面图形类应用一致，单次 ±25%，范围 0.25×–4× */
const ZOOM_STEP_IN = 1.25
const ZOOM_STEP_OUT = 0.8
const ZOOM_MIN = 0.25
const ZOOM_MAX = 4

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

function formatColor(node: GraphNode, colors: ThemeColors): string {
  if (node.broken) return colors.error
  if (node.is_folder) return colors.warning
  const color = DOC_FORMAT_META[node.content_type]?.color ?? DOC_FORMAT_META.markdown.color
  // 格式映射里 folder 等个别项是 var(--cn-*)，SVG 属性无法解析，回退到已读取的主色
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

/** 度数 → 直径：12px 起步，按 log 缓增到 40px，避免单个超级枢纽吃掉整张画布 */
function nodeSize(node: GraphNode, degree: number): number {
  const base = node.broken ? 18 : 14
  const scaled = base + Math.log2(degree + 1) * 8
  return Math.round(Math.min(40, scaled))
}

function buildOption(nodes: GraphNode[], edges: GraphEdge[], colors: ThemeColors): EChartsCoreOption {
  const degree = buildDegrees(nodes, edges)
  return {
    animationDuration: 300,
    // 力导向布局在空中飘：收敛后停住，交互时才继续，避免整页一直抖动
    tooltip: {
      trigger: 'item',
      confine: true,
      formatter: (params: { dataType?: string; data?: GraphNode | GraphEdge & { name?: string } }) => {
        const data = params.data
        if (params.dataType === 'edge') {
          const edge = data as GraphEdge
          const hints = [
            ...(edge.broken ? ['断链'] : []),
            ...(edge.ambiguous ? ['同名多文档，指向首个'] : []),
          ]
          return `${edge.raw || '双链引用'}${hints.length ? `（${hints.join('；')}）` : ''}`
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
        force: { repulsion: [120, 420], edgeLength: [60, 140], gravity: 0.08, friction: 0.2 },
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
        // 有向双链：箭头指向被引用方，方向感是同类图谱应用的标配
        edgeSymbol: ['none', 'arrow'],
        edgeSymbolSize: 7,
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
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<EChartsType | null>(null)
  /** 当前缩放倍率：只用于界面上「100%」这类读数，真值由 echarts 自己维护 */
  const zoomRef = useRef(1)
  const [zoomPct, setZoomPct] = useState(100)

  const graphQuery = useQuery({
    queryKey: ['document-link-graph', workspaceId],
    queryFn: () => documentsApi.linkGraph(workspaceId),
  })
  const graph = graphQuery.data
  const { mode: themeMode } = useTheme()
  const option = useMemo(
    () => buildOption(graph?.nodes ?? [], graph?.edges ?? [], readThemeColors()),
    // themeMode 进依赖：主题切换时 getComputedStyle 结果已更新，需重建 option
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [graph, themeMode],
  )

  const syncZoomPct = useCallback(() => {
    setZoomPct(Math.round(zoomRef.current * 100))
  }, [])

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
    chart.on('click', params => {
      if (params.dataType !== 'node') return
      const data = params.data as { value?: number; is_folder?: boolean } | null
      const docId = data?.value
      if (typeof docId !== 'number' || docId <= 0) return  // 断链虚拟节点（负 id）不跳转
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

  /** 复位：'restore' 会把 option 重置回初始提交态，同时让力导向重新收敛 */
  const reset = useCallback(() => {
    zoomRef.current = 1
    syncZoomPct()
    chartRef.current?.dispatchAction({ type: 'restore' })
  }, [syncZoomPct])

  return (
    <div className="cn-page" data-testid="document-graph-page">
      <header className="cn-page-head">
        <div className="cn-page-head-main">
          <span className="cn-page-head-icon" aria-hidden><ApartmentOutlined /></span>
          <div className="cn-page-head-text">
            <h1 className="cn-page-head-title">知识图谱</h1>
            <div className="cn-page-head-sub">
              工作区内可见文档与 [[双链]] 关系；点击节点进入文档，虚线为断链
            </div>
          </div>
        </div>
        <div className="cn-page-head-actions">
          <Space size={SPACE.sm}>
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
          title={`文档超过 500 个，仅展示最近更新的 500 个（共 ${graph.total} 个）`}
          style={{ marginBottom: SPACE.lg }}
        />
      )}
      {graphQuery.isError && <Alert type="error" showIcon message="图谱加载失败" />}

      <div
        ref={containerRef}
        data-testid="document-graph-canvas"
        style={{
          width: '100%',
          height: 'min(72vh, 720px)',
          minHeight: 420,
          border: '1px solid var(--cn-border)',
          borderRadius: 'var(--cn-radius-base)',
          background: 'var(--cn-bg-canvas)',
        }}
      />
      <Text type="secondary" style={{ fontSize: 'var(--cn-text-xs)' }}>
        节点 {graph?.nodes?.length ?? 0} · 关系 {graph?.edges?.length ?? 0}（拖拽平移，滚轮缩放，悬停高亮关联）
      </Text>
    </div>
  )
}
