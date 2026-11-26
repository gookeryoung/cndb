/** 文档知识图谱页（需求 0168）.
 *
 * 用 echarts graph + layout=force 呈现工作区文档的 [[双链]] 关系。
 * 本页由 App.tsx 动态 import（H31），echarts 不进首屏 bundle。
 * 节点取自 /links/graph（后端已按 H33 过滤可见性），断链/歧义按语义区分样式。
 */

import { useEffect, useMemo, useRef } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Alert, Button, Space, Typography } from 'antd'
import { ApartmentOutlined } from '@ant-design/icons'
import * as echarts from 'echarts/core'
import { GraphChart } from 'echarts/charts'
import { TooltipComponent } from 'echarts/components'
import { SVGRenderer } from 'echarts/renderers'
import type { EChartsCoreOption, EChartsType } from 'echarts/core'

import { documentsApi } from '@/api/documents'
import type { GraphEdge, GraphNode } from '@/api/documents'
import { DOC_FORMAT_META } from '@/components/Document/docFormat'
import { useTheme } from '@/theme/ThemeProvider'
import { SPACE } from '@/theme/tokens'

echarts.use([GraphChart, TooltipComponent, SVGRenderer])

const { Text } = Typography

/** 节点标题过长时省略，避免力导向图标签互相压盖 */
// 标题可能缺失（异常响应 / 空标题文档）：先兜底再取长度，否则 undefined.length 会整页崩溃。
function nodeLabel(title: string | null | undefined): string {
  const text = typeof title === 'string' && title ? title : '未命名文档'
  return text.length > 18 ? `${text.slice(0, 17)}…` : text
}

/** echarts 的 SVG 属性不解析 CSS 变量：与 ChartView 同口径，先读计算值再注入 option. */
interface ThemeColors {
  border: string
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

function buildOption(nodes: GraphNode[], edges: GraphEdge[], colors: ThemeColors): EChartsCoreOption {
  return {
    animationDuration: 300,
    tooltip: {
      trigger: 'item',
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
        return `${nodeLabel(node.title)}${suffix}`
      },
    },
    series: [
      {
        type: 'graph',
        layout: 'force',
        roam: true,
        draggable: true,
        force: { repulsion: 260, edgeLength: 110, gravity: 0.12 },
        // formatter 的 params.data 是写进 series.data 的原始项：必须带 title，
        // 只写 name 时 p.data.title 为 undefined（曾经的整页崩溃点）。
        label: { show: true, formatter: (p: { data: GraphNode }) => nodeLabel(p.data?.title), fontSize: 12 },
        data: nodes.map(node => ({
          id: String(node.id),
          name: node.title,
          title: node.title,
          value: node.id,
          is_folder: node.is_folder,
          itemStyle: { color: formatColor(node, colors), borderColor: colors.border, borderWidth: 1 },
          symbolSize: node.broken ? 22 : 34,
          broken: node.broken,
        })),
        links: edges.map(edge => ({
          source: String(edge.source),
          target: String(edge.target),
          lineStyle: {
            color: colors.border,
            type: edge.broken ? 'dashed' : 'solid',
            width: edge.broken ? 1 : 1.5,
          },
          broken: edge.broken,
          ambiguous: edge.ambiguous,
          raw: edge.raw,
        })),
        emphasis: { focus: 'adjacency' },
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
    const resize = () => chart.resize()
    window.addEventListener('resize', resize)
    return () => {
      window.removeEventListener('resize', resize)
      chart.dispose()
      chartRef.current = null
    }
  }, [graph, navigate, workspaceId])

  useEffect(() => {
    chartRef.current?.setOption(option, true)
  }, [option])

  const reset = () => chartRef.current?.dispatchAction({ type: 'restore' })

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
            <Button size="small" data-testid="graph-zoom-in" onClick={() => chartRef.current?.dispatchAction({ type: 'graphRoam', zoom: 1.2 })}>放大</Button>
            <Button size="small" data-testid="graph-zoom-out" onClick={() => chartRef.current?.dispatchAction({ type: 'graphRoam', zoom: 0.8 })}>缩小</Button>
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
        节点 {graph?.nodes?.length ?? 0} · 关系 {graph?.edges?.length ?? 0}（拖拽平移，滚轮缩放）
      </Text>
    </div>
  )
}
