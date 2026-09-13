import { useQuery } from '@tanstack/react-query'
import { Button, List, Spin, Tag, Typography, Empty, Tooltip, Space } from 'antd'
import { ExpandOutlined, ReloadOutlined } from '@ant-design/icons'
import { graphApi, type GraphResponse } from '@/api'
import { computeLayeredLayout } from '@/utils/graphLayout'

const { Text } = Typography

interface GraphMiniPanelProps {
  workspaceId: string
  onExpand: () => void
  onNavigateToTable: (tableId: string) => void
}

/** 工作流编辑器右侧 Tab 内的紧凑关系图面板.
 *
 * 含：紧凑 SVG 缩略图 + 统计信息 + 拓扑顺序列表 + 展开大图按钮.
 * 复用共享的 computeLayeredLayout 保证布局与独立 GraphPage 一致.
 */
export default function GraphMiniPanel({ workspaceId, onExpand, onNavigateToTable }: GraphMiniPanelProps) {
  const { data, isLoading, refetch } = useQuery<GraphResponse>({
    queryKey: ['graph', workspaceId],
    queryFn: () => graphApi.get(workspaceId),
    enabled: !!workspaceId,
  })

  if (isLoading) {
    return <div style={{ textAlign: 'center', padding: 24 }}><Spin size="small" /></div>
  }

  if (!data || data.nodes.length === 0) {
    return (
      <div>
        <div style={{ marginBottom: 12, textAlign: 'center' }}>
          <Empty description="暂无表关系" image={Empty.PRESENTED_IMAGE_SIMPLE} />
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
          <Button size="small" icon={<ReloadOutlined />} onClick={() => refetch()}>刷新</Button>
          <Button size="small" icon={<ExpandOutlined />} onClick={onExpand}>展开大图</Button>
        </div>
      </div>
    )
  }

  const layout = computeLayeredLayout(data.nodes, data.edges, { colGap: 110, rowGap: 50, startX: 16, startY: 16 })

  const svgW = 260
  const maxY = Math.max(...data.nodes.map(n => layout.get(n.id)?.y ?? 0)) + 40
  const svgH = Math.max(120, maxY)

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      {/* 操作栏 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Text type="secondary" style={{ fontSize: 12 }}>表关系图（参考）</Text>
        <Space size={4}>
          <Tooltip title="刷新">
            <Button size="small" icon={<ReloadOutlined />} onClick={() => refetch()} />
          </Tooltip>
          <Tooltip title="展开大图">
            <Button size="small" icon={<ExpandOutlined />} onClick={onExpand} type="primary" ghost />
          </Tooltip>
        </Space>
      </div>

      {/* SVG 缩略图 */}
      <div style={{
        border: '1px solid #e5e7eb', borderRadius: 6,
        background: '#fafafa', overflow: 'hidden',
      }}>
        <svg width={svgW} height={svgH} viewBox={`0 0 ${svgW} ${svgH}`} style={{ display: 'block' }}>
          <defs>
            <marker id="mini-arrow" markerWidth="6" markerHeight="6" refX="5" refY="2" orient="auto">
              <path d="M0,0 L0,4 L5,2 z" fill="#94a3b8" />
            </marker>
          </defs>

          {data.edges.map((e, i) => {
            const s = layout.get(e.source), t = layout.get(e.target)
            if (!s || !t) return null
            return (
              <line key={i}
                x1={s.x + 40} y1={s.y} x2={t.x} y2={t.y}
                stroke="#94a3b8" strokeWidth={1}
                markerEnd="url(#mini-arrow)"
              />
            )
          })}

          {data.nodes.map(n => {
            const pos = layout.get(n.id) || { x: 20, y: 20 }
            const stats = formatNodeStats(n)
            return (
              <g key={n.id}
                style={{ cursor: 'pointer' }}
                onClick={() => onNavigateToTable(n.id)}
              >
                {/* SVG tooltip */}
                <title>{`${n.label}${stats !== '' ? '\n' + stats : ''}`}</title>
                <rect x={pos.x} y={pos.y - 12} width={80} height={stats ? 36 : 24} rx={4}
                  fill="#ffffff" stroke="#3b82f6" strokeWidth={1}
                />
                <text x={pos.x + 40} y={pos.y + 3} textAnchor="middle" fontSize={10} fontWeight={600} fill="#1f2937">
                  {truncate(n.label, 6)}
                </text>
                {stats && (
                  <text x={pos.x + 40} y={pos.y + 15} textAnchor="middle" fontSize={8} fill="#6b7280">
                    {stats}
                  </text>
                )}
              </g>
            )
          })}
        </svg>
      </div>

      {/* 统计 */}
      <div style={{ display: 'flex', gap: 8 }}>
        <Tag color="blue">{data.nodes.length} 张表</Tag>
        <Tag color="green">{data.edges.length} 个 link</Tag>
      </div>

      {/* 拓扑顺序列表 */}
      <div>
        <Text type="secondary" style={{ fontSize: 12 }}>拓扑顺序（被依赖的先）</Text>
        <List
          size="small"
          style={{ marginTop: 4 }}
          dataSource={data.topo_order || data.nodes.map(n => n.id)}
          renderItem={id => {
            const node = data.nodes.find(n => n.id === id)
            return (
              <List.Item
                style={{ cursor: 'pointer', padding: '2px 8px' }}
                onClick={() => onNavigateToTable(id)}
              >
                <Text style={{ fontSize: 12 }}>{node?.label || id}</Text>
              </List.Item>
            )
          }}
        />
      </div>
    </div>
  )
}

function truncate(s: string, n: number): string {
  return s.length > n ? s.slice(0, n) + '…' : s
}

/** 把 GraphNode 统计要素格式化为一行紧凑文本. 无统计信息时返回空串. */
function formatNodeStats(n: { row_count?: number | null; field_count?: number; view_count?: number; link_count?: number }): string {
  const parts: string[] = []
  if (n.row_count != null) parts.push(`${n.row_count}行`)
  if (typeof n.field_count === 'number') parts.push(`${n.field_count}列`)
  if (typeof n.view_count === 'number' && n.view_count > 0) parts.push(`${n.view_count}视图`)
  if (typeof n.link_count === 'number' && n.link_count > 0) parts.push(`引${n.link_count}`)
  return parts.join(' ')
}
