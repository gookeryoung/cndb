import { useState, useRef, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { Card, Row, Col, Tag, Typography, List, Empty, Spin, Tooltip, Space, Button } from 'antd'
import { ShareAltOutlined, ZoomInOutlined, ZoomOutOutlined, ReloadOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { graphApi } from '@/api'
import type { GraphResponse } from '@/api'

const { Text } = Typography

export default function GraphPage() {
  const { wid } = useParams<{ wid: string }>()
  const navigate = useNavigate()

  const { data, isLoading, refetch } = useQuery<GraphResponse>({
    queryKey: ['graph', wid],
    queryFn: () => graphApi.get(wid!),
    enabled: !!wid,
  })

  // 交互状态
  const [scale, setScale] = useState(1)
  const [hoverNode, setHoverNode] = useState<string | null>(null)
  const [selectedNode, setSelectedNode] = useState<string | null>(null)
  const svgRef = useRef<SVGSVGElement>(null)

  // 鼠标滚轮缩放
  const onWheel = useCallback((e: React.WheelEvent) => {
    if (!e.ctrlKey && !e.metaKey && !e.shiftKey && Math.abs(e.deltaY) < 30) return
    e.preventDefault()
    setScale(prev => Math.min(2, Math.max(0.3, prev - e.deltaY * 0.002)))
  }, [])

  // 重置缩放
  const resetView = () => { setScale(1); setHoverNode(null); setSelectedNode(null) }

  if (isLoading) return <div style={{ padding: 48, textAlign: 'center' }}><Spin /></div>
  if (!data || data.nodes.length === 0) {
    return <Empty description="暂无表关系" style={{ padding: 48 }} />
  }

  const W = 900, H = Math.max(320, data.nodes.length * 80 + 80)
  const layout = computeLayeredLayout(data)
  const nodeMap = new Map(data.nodes.map(n => [n.id, n]))

  // 关联边集合（hover/选中节点的直接关联）
  const activeId = hoverNode || selectedNode
  const relatedEdges = new Set<number>()
  const relatedNodes = new Set<string>()
  if (activeId) {
    data.edges.forEach((e, i) => {
      if (e.source === activeId || e.target === activeId) {
        relatedEdges.add(i)
        relatedNodes.add(e.source)
        relatedNodes.add(e.target)
      }
    })
  }

  const goToTable = (nid: string) => {
    const node = nodeMap.get(nid)
    if (node?.type === 'table' || node?.type === undefined) {
      navigate(`/w/${wid}/tables/${nid}`)
    }
  }

  return (
    <div style={{ padding: 24 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 16 }}>
        <ShareAltOutlined style={{ fontSize: 20, color: '#3b82f6' }} />
        <h2 style={{ margin: 0, flex: 1 }}>表关系图</h2>
        <Space>
          <Tooltip title="缩小">
            <Button size="small" icon={<ZoomOutOutlined />} onClick={() => setScale(s => Math.max(0.3, s - 0.15))} />
          </Tooltip>
          <span style={{ color: '#64748b', fontSize: 12, minWidth: 50, textAlign: 'center' }}>
            {Math.round(scale * 100)}%
          </span>
          <Tooltip title="放大">
            <Button size="small" icon={<ZoomInOutlined />} onClick={() => setScale(s => Math.min(2, s + 0.15))} />
          </Tooltip>
          <Tooltip title="重置">
            <Button size="small" icon={<ReloadOutlined />} onClick={resetView} />
          </Tooltip>
        </Space>
      </div>
      <Row gutter={16}>
        <Col xs={24} lg={18}>
          <Card styles={{ body: { padding: 16, overflow: 'auto', maxHeight: '70vh' } }}>
            <svg
              ref={svgRef}
              width={W}
              height={H}
              viewBox={`0 0 ${W} ${H}`}
              style={{
                border: '1px solid #e5e7eb', borderRadius: 8, background: '#fafafa',
                display: 'block', transform: `scale(${scale})`, transformOrigin: 'top left',
                cursor: 'grab',
              }}
              onWheel={onWheel}
              onClick={() => setSelectedNode(null)}
            >
              <defs>
                <marker id="arrow" markerWidth="10" markerHeight="10" refX="9" refY="3" orient="auto">
                  <path d="M0,0 L0,6 L9,3 z" fill="#64748b" />
                </marker>
                <marker id="arrow-active" markerWidth="10" markerHeight="10" refX="9" refY="3" orient="auto">
                  <path d="M0,0 L0,6 L9,3 z" fill="#3b82f6" />
                </marker>
              </defs>

              {/* 边 */}
              {data.edges.map((e, i) => {
                const s = layout.get(e.source), t = layout.get(e.target)
                if (!s || !t) return null
                const isActive = relatedEdges.has(i)
                const dimmed = activeId != null && !isActive
                return (
                  <line key={i} x1={s.x + 70} y1={s.y} x2={t.x} y2={t.y}
                    stroke={isActive ? '#3b82f6' : '#64748b'}
                    strokeWidth={isActive ? 2.5 : 1.5}
                    strokeOpacity={dimmed ? 0.2 : 1}
                    markerEnd={isActive ? 'url(#arrow-active)' : 'url(#arrow)'}
                    style={{ transition: 'stroke 0.15s' }}
                  />
                )
              })}

              {/* 节点 */}
              {data.nodes.map(n => {
                const pos = layout.get(n.id) || { x: 20, y: 20 }
                const isHover = hoverNode === n.id
                const isSelected = selectedNode === n.id
                const related = activeId != null && relatedNodes.has(n.id)
                const dimmed = activeId != null && !related
                const fill = n.type === 'view' ? '#fef3c7' : n.type === 'workflow' ? '#dcfce7' : '#ffffff'
                const stroke = isSelected ? '#ef4444' : isHover ? '#2563eb' : '#3b82f6'
                return (
                  <g key={n.id}
                    style={{ cursor: n.type !== 'workflow' ? 'pointer' : 'default' }}
                    onMouseEnter={() => setHoverNode(n.id)}
                    onMouseLeave={() => setHoverNode(null)}
                    onClick={(ev) => { ev.stopPropagation(); setSelectedNode(n.id); goToTable(n.id) }}
                  >
                    <rect
                      x={pos.x} y={pos.y - 22} width={140} height={44} rx={6}
                      fill={fill}
                      stroke={stroke}
                      strokeWidth={isHover || isSelected ? 2 : 1}
                      opacity={dimmed ? 0.3 : 1}
                      style={{ transition: 'all 0.15s', filter: isHover ? 'drop-shadow(0 2px 6px rgba(59,130,246,0.25))' : undefined }}
                    />
                    <text x={pos.x + 70} y={pos.y + 4} textAnchor="middle" fontSize={13} fontWeight={600} fill="#1f2937">
                      {nodeMap.get(n.id)?.label || n.id}
                    </text>
                  </g>
                )
              })}
            </svg>
          </Card>
        </Col>
        <Col xs={24} lg={6}>
          <Card title={selectedNode ? '节点详情' : '拓扑顺序'} size="small"
            extra={<Button size="small" icon={<ReloadOutlined />} onClick={() => refetch()}>刷新</Button>}>
            {selectedNode ? (
              <NodeDetail node={nodeMap.get(selectedNode)!} nodeMap={nodeMap} edges={data.edges} />
            ) : (
              <List
                size="small"
                dataSource={data.topo_order || data.nodes.map(n => n.id)}
                renderItem={id => {
                  const n = nodeMap.get(id)
                  return (
                    <List.Item style={{ cursor: 'pointer' }}
                      onClick={() => { setSelectedNode(id); goToTable(id) }}
                      onMouseEnter={() => setHoverNode(id)}
                      onMouseLeave={() => setHoverNode(null)}>
                      <Tag color="blue">{n?.type || 'table'}</Tag> <Text>{n?.label || id}</Text>
                    </List.Item>
                  )
                }}
              />
            )}
          </Card>
        </Col>
      </Row>
    </div>
  )
}

function NodeDetail({
  node, nodeMap, edges,
}: {
  node: { id: string; label: string; type?: string }
  nodeMap: Map<string, { id: string; label: string; type?: string }>
  edges: Array<{ source: string; target: string; label?: string }>
}) {
  const [mode, setMode] = useState<'parents' | 'children'>('parents')
  const parents = edges.filter(e => e.target === node.id).map(e => ({ id: e.source, label: nodeMap.get(e.source)?.label || e.source }))
  const children = edges.filter(e => e.source === node.id).map(e => ({ id: e.target, label: nodeMap.get(e.target)?.label || e.target }))
  const list = mode === 'parents' ? parents : children

  return (
    <div>
      <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 4 }}>{node.label}</div>
      <Tag color="blue">{node.type || 'table'}</Tag>
      <div style={{ marginTop: 12 }}>
        <Space size={4}>
          <Button size="small" type={mode === 'parents' ? 'primary' : 'default'} onClick={() => setMode('parents')}>
            被 ({parents.length})
          </Button>
          <Button size="small" type={mode === 'children' ? 'primary' : 'default'} onClick={() => setMode('children')}>
            引用 ({children.length})
          </Button>
        </Space>
      </div>
      {list.length === 0 ? (
        <Text type="secondary" style={{ fontSize: 12 }}>无</Text>
      ) : (
        <List size="small" style={{ marginTop: 8 }}
          dataSource={list}
          renderItem={x => <List.Item>{x.label}</List.Item>} />
      )}
    </div>
  )
}

function computeLayeredLayout(g: GraphResponse): Map<string, { x: number; y: number }> {
  const pos = new Map<string, { x: number; y: number }>()
  const indeg = new Map<string, number>()
  for (const n of g.nodes) indeg.set(n.id, 0)
  for (const e of g.edges) indeg.set(e.target, (indeg.get(e.target) ?? 0) + 1)

  const layers: string[][] = []
  const remaining = new Set(g.nodes.map(n => n.id))
  while (remaining.size > 0) {
    const layer: string[] = []
    for (const id of remaining) {
      if ((indeg.get(id) ?? 0) === 0) layer.push(id)
    }
    if (layer.length === 0) break
    layers.push(layer)
    for (const id of layer) {
      remaining.delete(id)
      for (const e of g.edges) if (e.source === id) indeg.set(e.target, (indeg.get(e.target) ?? 0) - 1)
    }
  }
  if (remaining.size > 0) layers.push([...remaining])

  const colGap = 220, rowGap = 80
  layers.forEach((layer, ci) => {
    layer.forEach((id, ri) => {
      pos.set(id, { x: 40 + ci * colGap, y: 40 + ri * rowGap })
    })
  })
  return pos
}

