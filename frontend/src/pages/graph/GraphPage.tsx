import { useParams } from 'react-router-dom'
import { Card, Row, Col, Tag, Typography, List, Empty, Spin } from 'antd'
import { ShareAltOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { graphApi } from '@/api'
import type { GraphResponse } from '@/api'

const { Text } = Typography

export default function GraphPage() {
  const { wid } = useParams<{ wid: string }>()

  const { data, isLoading } = useQuery<GraphResponse>({
    queryKey: ['graph', wid],
    queryFn: () => graphApi.get(wid!),
    enabled: !!wid,
  })

  if (isLoading) return <div style={{ padding: 48, textAlign: 'center' }}><Spin /></div>
  if (!data || data.nodes.length === 0) {
    return <Empty description="暂无表关系" style={{ padding: 48 }} />
  }

  const W = 900, H = Math.max(320, data.nodes.length * 80 + 80)
  const layout = computeLayeredLayout(data)
  const nodeMap = new Map(data.nodes.map(n => [n.id, n]))

  return (
    <div style={{ padding: 24 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 16 }}>
        <ShareAltOutlined style={{ fontSize: 20, color: '#3b82f6' }} />
        <h2 style={{ margin: 0 }}>表关系图</h2>
      </div>
      <Row gutter={16}>
        <Col xs={24} lg={18}>
          <Card bodyStyle={{ padding: 16 }}>
            <svg width="100%" viewBox={`0 0 ${W} ${H}`} style={{ border: '1px solid #e5e7eb', borderRadius: 8, background: '#fafafa' }}>
              {data.edges.map((e, i) => {
                const s = layout.get(e.source), t = layout.get(e.target)
                if (!s || !t) return null
                return (
                  <line key={i} x1={s.x + 70} y1={s.y} x2={t.x} y2={t.y}
                    stroke="#64748b" strokeWidth={1.5} markerEnd="url(#arrow)" />
                )
              })}
              <defs>
                <marker id="arrow" markerWidth="10" markerHeight="10" refX="9" refY="3" orient="auto">
                  <path d="M0,0 L0,6 L9,3 z" fill="#64748b" />
                </marker>
              </defs>
              {data.nodes.map(n => {
                const pos = layout.get(n.id) || { x: 20, y: 20 }
                return (
                  <g key={n.id}>
                    <rect x={pos.x} y={pos.y - 22} width={140} height={44} rx={6} fill="#fff" stroke="#3b82f6" />
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
          <Card title="拓扑顺序" size="small">
            <List
              size="small"
              dataSource={data.topo_order || data.nodes.map(n => n.id)}
              renderItem={id => {
                const n = nodeMap.get(id)
                return <List.Item><Tag color="blue">{n?.type || 'table'}</Tag> <Text>{n?.label || id}</Text></List.Item>
              }}
            />
          </Card>
        </Col>
      </Row>
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
