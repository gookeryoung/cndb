import { useState, useRef, useMemo, useCallback, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { Card, Row, Col, Tag, Typography, List, Empty, Spin, Tooltip, Space, Button } from 'antd'
import { ShareAltOutlined, ZoomInOutlined, ZoomOutOutlined, ReloadOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { graphApi } from '@/api'
import type { GraphResponse } from '@/api'
import { computeLayeredLayout } from '@/utils/graphLayout'

const { Text } = Typography

const STORAGE_KEY = 'cndb.graph.layout.'

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

  // 节点位置（可拖拽覆盖初始 layout）
  const [nodePositions, setNodePositions] = useState<Map<string, { x: number; y: number }>>(() => new Map())
  const dragState = useRef<{
    id: string; startX: number; startY: number; origX: number; origY: number;
  } | null>(null)

  // 默认每次数据变化都应用自动布局（不恢复旧的手动布局）
  useEffect(() => {
    if (!wid || !data) return
    setNodePositions(computeLayeredLayout(data.nodes, data.edges))
  }, [wid, data])

  // 位置变更后持久化
  const persistLayout = useCallback((positions: Map<string, { x: number; y: number }>) => {
    if (!wid) return
    try {
      const obj: Record<string, { x: number; y: number }> = {}
      positions.forEach((v, k) => { obj[k] = v })
      localStorage.setItem(`${STORAGE_KEY}${wid}`, JSON.stringify(obj))
    } catch {
      /* quota exceeded 忽略 */
    }
  }, [wid])

  // 自动布局 fallback（data 不变时稳定引用，避免 useCallback 每次重建）
  const autoLayout = useMemo(
    () => data ? computeLayeredLayout(data.nodes, data.edges) : new Map<string, { x: number; y: number }>(),
    [data],
  )
  const effectiveLayout = useCallback((id: string) => {
    return nodePositions.get(id) || autoLayout.get(id) || { x: 20, y: 20 }
  }, [nodePositions, autoLayout])

  // 鼠标滚轮缩放
  const onWheel = useCallback((e: React.WheelEvent) => {
    if (!e.ctrlKey && !e.metaKey && !e.shiftKey && Math.abs(e.deltaY) < 30) return
    e.preventDefault()
    setScale(prev => Math.min(2, Math.max(0.3, prev - e.deltaY * 0.002)))
  }, [])

  // 重置：恢复自动布局
  const resetLayout = () => {
    if (!data) return
    const fresh = computeLayeredLayout(data.nodes, data.edges)
    setNodePositions(fresh)
    persistLayout(fresh)
    setScale(1)
    setHoverNode(null)
    setSelectedNode(null)
  }

  // ─────────── 拖拽逻辑 ───────────
  const onNodeMouseDown = useCallback((ev: React.MouseEvent, nodeId: string) => {
    ev.stopPropagation()
    ev.preventDefault()
    setSelectedNode(nodeId)
    const pos = effectiveLayout(nodeId)
    dragState.current = {
      id: nodeId,
      startX: ev.clientX,
      startY: ev.clientY,
      origX: pos.x,
      origY: pos.y,
    }
  }, [effectiveLayout])

  useEffect(() => {
    const onMouseMove = (ev: MouseEvent) => {
      if (!dragState.current) return
      const { id, startX, startY, origX, origY } = dragState.current
      const dx = (ev.clientX - startX) / scale
      const dy = (ev.clientY - startY) / scale
      const newX = Math.max(10, origX + dx)
      const newY = Math.max(10, origY + dy)
      setNodePositions(prev => {
        const next = new Map(prev)
        next.set(id, { x: newX, y: newY })
        return next
      })
    }
    const onMouseUp = () => {
      if (dragState.current) {
        dragState.current = null
        // 持久化当前所有位置
        setNodePositions(prev => {
          persistLayout(prev)
          return prev
        })
      }
    }
    window.addEventListener('mousemove', onMouseMove)
    window.addEventListener('mouseup', onMouseUp)
    return () => {
      window.removeEventListener('mousemove', onMouseMove)
      window.removeEventListener('mouseup', onMouseUp)
    }
  }, [scale, persistLayout])

  if (isLoading) return <div style={{ padding: 48, textAlign: 'center' }}><Spin /></div>
  if (!data || data.nodes.length === 0) {
    return <Empty description="暂无表关系" style={{ padding: 48 }} />
  }

  const W = 900, H = Math.max(320, data.nodes.length * 80 + 80)
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
        <span style={{ color: '#94a3b8', fontSize: 12 }}>提示：双击节点跳转，可拖拽调整位置，默认自动布局</span>
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
          <Tooltip title="恢复自动布局">
            <Button size="small" icon={<ReloadOutlined />} onClick={resetLayout} />
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
                const s = effectiveLayout(e.source), t = effectiveLayout(e.target)
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
                const pos = effectiveLayout(n.id)
                const isHover = hoverNode === n.id
                const isSelected = selectedNode === n.id
                const related = activeId != null && relatedNodes.has(n.id)
                const dimmed = activeId != null && !related
                const fill = n.type === 'view' ? '#fef3c7' : n.type === 'workflow' ? '#dcfce7' : '#ffffff'
                const stroke = isSelected ? '#ef4444' : isHover ? '#2563eb' : '#3b82f6'
                return (
                  <g key={n.id}
                    style={{ cursor: 'move' }}
                    onMouseEnter={() => setHoverNode(n.id)}
                    onMouseLeave={() => setHoverNode(null)}
                    onMouseDown={(ev) => onNodeMouseDown(ev, n.id)}
                    onDoubleClick={(ev) => {
                      ev.stopPropagation()
                      goToTable(n.id)
                    }}
                  >
                    <rect
                      x={pos.x} y={pos.y - 22} width={140} height={44} rx={6}
                      fill={fill}
                      stroke={stroke}
                      strokeWidth={isHover || isSelected ? 2 : 1}
                      opacity={dimmed ? 0.3 : 1}
                      style={{ transition: isHover || isSelected ? 'all 0.15s' : undefined, filter: isHover ? 'drop-shadow(0 2px 6px rgba(59,130,246,0.25))' : undefined }}
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
