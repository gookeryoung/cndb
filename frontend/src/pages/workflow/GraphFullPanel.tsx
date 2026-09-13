import { useState, useRef, useCallback, useEffect, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Button, List, Spin, Tag, Typography, Empty, Tooltip, Space } from 'antd'
import { ShareAltOutlined, ZoomInOutlined, ZoomOutOutlined, ReloadOutlined } from '@ant-design/icons'
import { graphApi, type GraphResponse } from '@/api'
import { computeLayeredLayout } from '@/utils/graphLayout'

const { Text } = Typography

const STORAGE_KEY = 'cndb.graph.layout.'

interface GraphFullPanelProps {
  workspaceId: string
  onNavigateToTable: (tableId: string) => void
}

/** Drawer 内的完整交互版关系图.
 *
 * 复用 GraphPage 的渲染逻辑：缩放、拖拽、hover 高亮关联边、
 * 节点详情（被引用 / 引用了谁）、位置 localStorage 持久化.
 */
export default function GraphFullPanel({ workspaceId, onNavigateToTable }: GraphFullPanelProps) {
  const { data, isLoading, refetch } = useQuery<GraphResponse>({
    queryKey: ['graph', workspaceId],
    queryFn: () => graphApi.get(workspaceId),
    enabled: !!workspaceId,
  })

  const [scale, setScale] = useState(1)
  const [hoverNode, setHoverNode] = useState<string | null>(null)
  const [selectedNode, setSelectedNode] = useState<string | null>(null)
  const dragState = useRef<{
    id: string; startX: number; startY: number; origX: number; origY: number
  } | null>(null)

  // 节点位置（可拖拽覆盖初始 layout）
  const [nodePositions, setNodePositions] = useState<Map<string, { x: number; y: number }>>(() => new Map())

  // 自动布局 fallback
  const autoLayout = useMemo(() => {
    if (!data) return new Map<string, { x: number; y: number }>()
    return computeLayeredLayout(data.nodes, data.edges)
  }, [data])

  // 从 localStorage 恢复布局
  useEffect(() => {
    if (!workspaceId || !data) return
    try {
      const raw = localStorage.getItem(`${STORAGE_KEY}${workspaceId}`)
      if (raw) {
        const parsed = JSON.parse(raw) as Record<string, { x: number; y: number }>
        setNodePositions(new Map(Object.entries(parsed)))
      } else {
        setNodePositions(new Map())
      }
    } catch {
      setNodePositions(new Map())
    }
  }, [workspaceId, data])

  // 持久化
  const persistLayout = useCallback((positions: Map<string, { x: number; y: number }>) => {
    if (!workspaceId) return
    try {
      const obj: Record<string, { x: number; y: number }> = {}
      positions.forEach((v, k) => { obj[k] = v })
      localStorage.setItem(`${STORAGE_KEY}${workspaceId}`, JSON.stringify(obj))
    } catch {
      /* quota exceeded 忽略 */
    }
  }, [workspaceId])

  const effectiveLayout = useCallback((id: string) => {
    return nodePositions.get(id) || autoLayout.get(id) || { x: 20, y: 20 }
  }, [nodePositions, autoLayout])

  // 鼠标滚轮缩放（需 ctrl/meta/shift 修饰键，避免 Drawer 内滚动冲突）
  const onWheel = useCallback((e: React.WheelEvent) => {
    if (!e.ctrlKey && !e.metaKey && !e.shiftKey && Math.abs(e.deltaY) < 30) return
    e.preventDefault()
    setScale(prev => Math.min(2, Math.max(0.3, prev - e.deltaY * 0.002)))
  }, [])

  // 重置布局
  const resetLayout = () => {
    setNodePositions(new Map())
    persistLayout(new Map())
    setScale(1)
    setHoverNode(null)
    setSelectedNode(null)
  }

  // ── 拖拽 ──
  const onNodeMouseDown = useCallback((ev: React.MouseEvent, nodeId: string) => {
    ev.stopPropagation()
    ev.preventDefault()
    setSelectedNode(nodeId)
    const pos = effectiveLayout(nodeId)
    dragState.current = {
      id: nodeId, startX: ev.clientX, startY: ev.clientY, origX: pos.x, origY: pos.y,
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

  const W = 640
  const H = Math.max(320, data.nodes.length * 80 + 80)
  const nodeMap = new Map(data.nodes.map(n => [n.id, n]))

  // hover/选中 高亮关联边和节点
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

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      {/* 工具栏 */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <ShareAltOutlined style={{ fontSize: 18, color: '#3b82f6' }} />
        <Text strong>表关系图</Text>
        <Space style={{ marginLeft: 'auto' }}>
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
          <Button size="small" onClick={() => refetch()}>刷新</Button>
        </Space>
      </div>

      {/* SVG + 详情两栏 */}
      <div style={{ display: 'flex', gap: 12 }}>
        {/* 左侧：SVG 画布 */}
        <div style={{ flex: 1, overflow: 'auto', border: '1px solid #e5e7eb', borderRadius: 8, background: '#fafafa' }}>
          <svg
            width={W}
            height={H}
            viewBox={`0 0 ${W} ${H}`}
            style={{
              display: 'block', transform: `scale(${scale})`, transformOrigin: 'top left',
              cursor: 'grab',
            }}
            onWheel={onWheel}
            onClick={() => setSelectedNode(null)}
          >
            <defs>
              <marker id="full-arrow" markerWidth="10" markerHeight="10" refX="9" refY="3" orient="auto">
                <path d="M0,0 L0,6 L9,3 z" fill="#64748b" />
              </marker>
              <marker id="full-arrow-active" markerWidth="10" markerHeight="10" refX="9" refY="3" orient="auto">
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
                  markerEnd={isActive ? 'url(#full-arrow-active)' : 'url(#full-arrow)'}
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
              const stroke = isSelected ? '#ef4444' : isHover ? '#2563eb' : '#3b82f6'
              return (
                <g key={n.id}
                  style={{ cursor: 'move' }}
                  onMouseEnter={() => setHoverNode(n.id)}
                  onMouseLeave={() => setHoverNode(null)}
                  onMouseDown={(ev) => onNodeMouseDown(ev, n.id)}
                  onClick={(ev) => {
                    ev.stopPropagation()
                    if (!dragState.current) onNavigateToTable(n.id)
                  }}
                >
                  <rect
                    x={pos.x} y={pos.y - 22} width={140} height={44} rx={6}
                    fill="#ffffff"
                    stroke={stroke}
                    strokeWidth={isHover || isSelected ? 2 : 1}
                    opacity={dimmed ? 0.3 : 1}
                    style={{
                      transition: isHover || isSelected ? 'all 0.15s' : undefined,
                      filter: isHover ? 'drop-shadow(0 2px 6px rgba(59,130,246,0.25))' : undefined,
                    }}
                  />
                  <text x={pos.x + 70} y={pos.y + 4} textAnchor="middle" fontSize={13} fontWeight={600} fill="#1f2937">
                    {nodeMap.get(n.id)?.label || n.id}
                  </text>
                </g>
              )
            })}
          </svg>
        </div>

        {/* 右侧：详情 / 拓扑 */}
        <div style={{ width: 200, flexShrink: 0 }}>
          {selectedNode ? (
            <NodeDetail node={nodeMap.get(selectedNode)!} nodeMap={nodeMap} edges={data.edges} />
          ) : (
            <div>
              <Text strong style={{ fontSize: 13 }}>拓扑顺序</Text>
              <List
                size="small"
                style={{ marginTop: 4 }}
                dataSource={data.topo_order || data.nodes.map(n => n.id)}
                renderItem={id => {
                  const n = nodeMap.get(id)
                  return (
                    <List.Item style={{ cursor: 'pointer', padding: '2px 8px' }}
                      onClick={() => { setSelectedNode(id); onNavigateToTable(id) }}
                      onMouseEnter={() => setHoverNode(id)}
                      onMouseLeave={() => setHoverNode(null)}
                    >
                      <Tag color="blue" style={{ marginRight: 4 }}>{n?.type || 'table'}</Tag>
                      <Text style={{ fontSize: 12 }}>{n?.label || id}</Text>
                    </List.Item>
                  )
                }}
              />
            </div>
          )}
        </div>
      </div>

      <div style={{ color: '#94a3b8', fontSize: 12, textAlign: 'center' }}>
        提示：可拖拽节点调整位置（自动保存），Ctrl/Shift+滚轮缩放，点击节点可跳转
      </div>
    </div>
  )
}

function NodeDetail({
  node, nodeMap, edges,
}: {
  node: {
    id: string
    label: string
    type?: string
    field_count?: number
    row_count?: number | null
    view_count?: number
    link_count?: number
  }
  nodeMap: Map<string, {
    id: string
    label: string
    type?: string
    field_count?: number
    row_count?: number | null
    view_count?: number
    link_count?: number
  }>
  edges: Array<{ source: string; target: string; label?: string }>
}) {
  const [mode, setMode] = useState<'parents' | 'children'>('parents')
  const parents = edges.filter(e => e.target === node.id).map(e => ({ id: e.source, label: nodeMap.get(e.source)?.label || e.source }))
  const children = edges.filter(e => e.source === node.id).map(e => ({ id: e.target, label: nodeMap.get(e.target)?.label || e.target }))
  const list = mode === 'parents' ? parents : children

  return (
    <div>
      <Text strong style={{ fontSize: 13 }}>{node.label}</Text>
      {/* 统计要素 */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 6 }}>
        {typeof node.field_count === 'number' && (
          <Tag color="blue" style={{ marginRight: 0, fontSize: 11 }}>字段 {node.field_count}</Tag>
        )}
        {node.row_count != null && (
          <Tag color="green" style={{ marginRight: 0, fontSize: 11 }}>{node.row_count} 行</Tag>
        )}
        {typeof node.view_count === 'number' && node.view_count > 0 && (
          <Tag color="purple" style={{ marginRight: 0, fontSize: 11 }}>{node.view_count} 视图</Tag>
        )}
        {typeof node.link_count === 'number' && node.link_count > 0 && (
          <Tag color="orange" style={{ marginRight: 0, fontSize: 11 }}>被引用 {node.link_count}</Tag>
        )}
      </div>
      {/* 关系列表 */}
      <div style={{ marginTop: 8 }}>
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
        <Text type="secondary" style={{ fontSize: 12, marginTop: 8, display: 'block' }}>无</Text>
      ) : (
        <List size="small" style={{ marginTop: 8 }}
          dataSource={list}
          renderItem={x => <List.Item style={{ padding: '2px 8px' }}><Text style={{ fontSize: 12 }}>{x.label}</Text></List.Item>} />
      )}
    </div>
  )
}
