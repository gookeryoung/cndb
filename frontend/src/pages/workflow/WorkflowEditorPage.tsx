import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  ReactFlow, useReactFlow,
  Background, Controls, Handle, MiniMap, Position, ReactFlowProvider,
  applyNodeChanges, applyEdgeChanges, BackgroundVariant,
  BaseEdge, getBezierPath,
  type Connection, type Edge, type EdgeChange, type EdgeProps, type Node, type NodeChange,
  type NodeProps,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import {
  Button, Card, Descriptions, Drawer, Empty, Input, Modal,
  Select, Space, Spin, Tabs, Tag, Tooltip, Typography, message,
} from 'antd'
import {
  AimOutlined, ApartmentOutlined, ClusterOutlined, DeleteOutlined,
  PlusOutlined, ReloadOutlined, SaveOutlined, TableOutlined,
} from '@ant-design/icons'
import { useMutation, useQuery } from '@tanstack/react-query'
import { workflowApi, tableApi } from '@/api'
import type { WorkflowNode, ID } from '@/api'
import GraphMiniPanel from './GraphMiniPanel'
import GraphFullPanel from './GraphFullPanel'
import { computeLayeredLayout } from '@/utils/graphLayout'

const { Text } = Typography

// ── 自定义节点卡片 ────────────────────────────────────

function TableNode({ data, selected }: NodeProps) {
  const node = data as unknown as WorkflowNode
  const hasTable = !!node.table_id

  return (
    <div
      style={{
        minWidth: 180,
        border: `2px solid ${selected ? '#1677ff' : hasTable ? '#10b981' : '#d1d5db'}`,
        borderRadius: 10,
        background: '#fff',
        padding: '12px 14px',
        boxShadow: selected ? '0 4px 16px rgba(22,119,255,.25)' : '0 2px 8px rgba(0,0,0,.06)',
        cursor: 'grab',
      }}
    >
      {/* 源 handle */}
      <Handle type="target" position={Position.Left} style={{ background: '#94a3b8', width: 10, height: 10 }} />

      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6 }}>
        <ApartmentOutlined style={{ color: '#3b82f6' }} />
        <Text strong style={{ fontSize: 14 }}>{node.name}</Text>
      </div>

      {hasTable ? (
        <div style={{ fontSize: 12, color: '#6b7280', display: 'flex', flexDirection: 'column', gap: 2 }}>
          <span>
            <TableOutlined /> 绑定表：<Tag color="blue" style={{ marginLeft: 4 }}>{node.table?.name || '(加载中)'}</Tag>
          </span>
          <span style={{ display: 'flex', gap: 8 }}>
            {node.table?.row_count != null && <Tag color="green" style={{ fontSize: 11 }}>{node.table.row_count} 行</Tag>}
            {node.table?.view_count != null && <Tag color="purple" style={{ fontSize: 11 }}>{node.table.view_count} 视图</Tag>}
          </span>
        </div>
      ) : (
        <Text type="secondary" style={{ fontSize: 12 }}>未绑定表</Text>
      )}

      {/* 目标 handle */}
      <Handle type="source" position={Position.Right} style={{ background: '#94a3b8', width: 10, height: 10 }} />
    </div>
  )
}

// ── 自定义边（无背景 label，位于连线上方） ────────────

function CustomEdge({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  style,
  markerEnd,
  label,
  selected,
}: EdgeProps) {
  const [edgePath, labelX, labelY] = getBezierPath({
    sourceX,
    sourceY,
    targetX,
    targetY,
    sourcePosition,
    targetPosition,
  })

  // label 向上偏移 8px，紧贴连线上方
  const labelOffsetY = labelY - 12

  return (
    <>
      {/* 透明宽路径作为点击热区，方便选中边 */}
      <path
        d={edgePath}
        fill="none"
        stroke="transparent"
        strokeWidth={16}
        style={{ cursor: 'pointer' }}
      />
      <BaseEdge
        id={id}
        path={edgePath}
        markerEnd={markerEnd}
        style={{
          ...style,
          stroke: selected ? '#1677ff' : (style?.stroke || '#64748b'),
          strokeWidth: selected ? 3 : (style?.strokeWidth || 2),
          transition: 'stroke 0.15s, stroke-width 0.15s',
        }}
      />
      {label && (
        <foreignObject
          width={240}
          height={40}
          x={labelX - 120}
          y={labelOffsetY - 8}
          style={{ overflow: 'visible', pointerEvents: 'none' }}
        >
          <div style={{
            fontSize: 12,
            color: selected ? '#1677ff' : '#64748b',
            textAlign: 'center',
            lineHeight: '16px',
            fontFamily: 'inherit',
            userSelect: 'none',
          }}>
            {label}
          </div>
        </foreignObject>
      )}
    </>
  )
}

const nodeTypes = { table: TableNode }
const edgeTypes = { custom: CustomEdge }

// ── 主编辑器 ─────────────────────────────────────────

function WorkflowEditorInner() {
  const { wid, fwid } = useParams<{ wid: string; fwid: string }>()
  const navigate = useNavigate()
  const rf = useReactFlow()

  const { data, isLoading, refetch } = useQuery({
    queryKey: ['workflows', wid, fwid],
    queryFn: () => workflowApi.get(wid!, fwid!),
    enabled: !!wid && !!fwid,
  })

  const { data: tables = [] } = useQuery({
    queryKey: ['workspaces', wid, 'tables'],
    queryFn: () => tableApi.list(wid!),
    enabled: !!wid,
  })

  // React Flow 节点状态
  const [rfNodes, setRfNodes] = useState<Node[]>([])
  const [rfEdges, setRfEdges] = useState<Edge[]>([])
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null)
  const [addNodeOpen, setAddNodeOpen] = useState(false)
  const [addNodeName, setAddNodeName] = useState('')
  const [addNodeTableId, setAddNodeTableId] = useState<ID | null>(null)
  const [graphDrawerOpen, setGraphDrawerOpen] = useState(false)

  // 将后端数据转换为 React Flow 格式
  useEffect(() => {
    if (!data) return
    const nodes: Node[] = data.nodes.map(n => ({
      id: String(n.id),
      type: 'table',
      position: { x: n.pos_x, y: n.pos_y },
      data: n as unknown as Record<string, unknown>,
    }))
    const edges: Edge[] = data.edges.map(e => ({
      id: String(e.id),
      type: 'custom',
      source: String(e.source_node_id),
      target: String(e.target_node_id),
      label: e.label || undefined,
      animated: true,
      selectable: true,
      deletable: true,
      style: { stroke: '#64748b', strokeWidth: 2 },
    }))
    setRfNodes(nodes)
    setRfEdges(edges)
    setSelectedNodeId(null)
  }, [data])

  const selectedNode = useMemo(
    () => rfNodes.find(n => n.id === selectedNodeId) as Node | undefined,
    [rfNodes, selectedNodeId],
  )

  // ── 节点变更处理 ───────────────────────────────────

  const onNodesChange = useCallback((changes: NodeChange[]) => {
    setRfNodes(ns => applyNodeChanges(changes, ns))
    // 位置变更 debounce PATCH 由 onNodeDragStop 处理
  }, [])

  const onEdgesChange = useCallback((changes: EdgeChange[]) => {
    // 删除边：直接调后端
    changes.forEach(c => {
      if (c.type === 'remove') {
        const edgeId = Number(c.id)
        workflowApi.removeEdge(wid!, fwid!, edgeId).catch(() => { })
      }
    })
    setRfEdges(es => applyEdgeChanges(changes, es))
  }, [wid, fwid])

  const onConnect = useCallback((conn: Connection) => {
    if (!conn.source || !conn.target) return
    // 禁自环
    if (conn.source === conn.target) { message.warning('不允许自环'); return }
    const sourceNum = Number(conn.source)
    const targetNum = Number(conn.target)
    // 检查重复
    if (rfEdges.some(e => e.source === conn.source && e.target === conn.target)) {
      message.warning('该边已存在'); return
    }
    workflowApi.addEdge(wid!, fwid!, {
      source_node_id: sourceNum,
      target_node_id: targetNum,
      label: '',
    }).then(resp => {
      setRfEdges(es => [...es, {
        id: String(resp.id),
        type: 'custom',
        source: String(sourceNum),
        target: String(targetNum),
        animated: true,
        selectable: true,
        deletable: true,
        style: { stroke: '#64748b', strokeWidth: 2 },
      }])
      message.success('连线已创建')
    }).catch(e => {
      message.error(e?.response?.data?.detail || '创建边失败')
    })
  }, [wid, fwid, rfEdges])

  const onNodeDragStop = useCallback((_ev: unknown, node: Node) => {
    // debounce 批量发送位置
    const nid = Number(node.id)
    const orig = rfNodes.find(n => n.id === node.id)?.data as unknown as WorkflowNode | undefined
    if (!orig) return
    const dx = node.position.x - orig.pos_x
    const dy = node.position.y - orig.pos_y
    if (dx === 0 && dy === 0) return
    workflowApi.updateNode(wid!, fwid!, nid, {
      pos_x: Math.round(node.position.x),
      pos_y: Math.round(node.position.y),
    }).catch(() => { })
  }, [wid, fwid, rfNodes])

  const onNodeDoubleClick = useCallback((_ev: unknown, node: Node) => {
    const n = node.data as unknown as WorkflowNode
    if (n.table_id) {
      const vid = (n.config as any)?.default_view_id
      const url = vid
        ? `/w/${wid}/tables/${n.table_id}?view=${vid}`
        : `/w/${wid}/tables/${n.table_id}`
      navigate(url)
    } else {
      message.info('该节点未绑定表')
    }
  }, [wid, navigate])

  // ── 添加节点 ──────────────────────────────────────

  const addNodeMut = useMutation({
    mutationFn: () => workflowApi.addNode(wid!, fwid!, {
      name: addNodeName.trim(),
      table_id: addNodeTableId,
      pos_x: 100 + rfNodes.length * 60,
      pos_y: 100 + rfNodes.length * 40,
      config: { default_view_id: null },
    }),
    onSuccess: (resp) => {
      setRfNodes(ns => [...ns, {
        id: String(resp.id),
        type: 'table',
        position: { x: resp.pos_x, y: resp.pos_y },
        data: { ...resp } as unknown as Record<string, unknown>,
      }])
      setAddNodeOpen(false); setAddNodeName(''); setAddNodeTableId(null)
      message.success('节点已添加')
    },
  })

  // ── 更新节点属性 ──────────────────────────────────

  const updateNodeMut = useMutation({
    mutationFn: (nid: number, payload: Record<string, unknown>) =>
      workflowApi.updateNode(wid!, fwid!, nid, payload),
  })

  const removeNodeMut = useMutation({
    mutationFn: (nid: number) => workflowApi.removeNode(wid!, fwid!, nid),
    onSuccess: () => {
      message.success('节点已删除')
      setSelectedNodeId(null)
    },
  })

  // ── 自动布局 ─────────────────────────────────────

  const handleAutoLayout = () => {
    if (!data) return
    const layout = computeLayeredLayout(
      data.nodes.map(n => ({ id: String(n.id) })),
      data.edges.map(e => ({ source: String(e.source_node_id), target: String(e.target_node_id) })),
      { colGap: 340, rowGap: 140, startX: 40, startY: 60 },
    )
    const newNodes = rfNodes.map(n => {
      const pos = layout.get(n.id) || { x: n.position.x, y: n.position.y }
      return { ...n, position: pos }
    })
    setRfNodes(newNodes)
    // 批量更新位置
    for (const n of newNodes) {
      const orig = rfNodes.find(x => x.id === n.id)?.data as unknown as WorkflowNode | undefined
      if (!orig) continue
      if (n.position.x !== orig.pos_x || n.position.y !== orig.pos_y) {
        workflowApi.updateNode(wid!, fwid!, Number(n.id), {
          pos_x: Math.round(n.position.x),
          pos_y: Math.round(n.position.y),
        }).catch(() => { })
      }
    }
    message.success('已自动布局')
  }

  const handleFit = () => rf.fitView({ padding: 0.2 })

  const handleDeleteNode = () => {
    if (!selectedNodeId) return
    removeNodeMut.mutate(Number(selectedNodeId))
    setRfNodes(ns => ns.filter(n => n.id !== selectedNodeId))
  }

  // ── 渲染 ─────────────────────────────────────────

  if (isLoading) return <div style={{ padding: 48, textAlign: 'center' }}><Spin /></div>
  if (!data) return <Empty description="工作流不存在" />

  return (
    <div style={{ height: 'calc(100vh - 120px)', display: 'flex', gap: 16 }}>
      {/* 左侧：React Flow 画布 */}
      <div style={{ flex: 1, position: 'relative', background: '#f8fafc', borderRadius: 8, overflow: 'hidden', border: '1px solid #e5e7eb' }}>
        {/* 工具栏 */}
        <div style={{
          position: 'absolute', top: 12, left: 12, zIndex: 10,
          display: 'flex', gap: 8, background: '#fff', padding: '8px 12px',
          borderRadius: 8, boxShadow: '0 2px 8px rgba(0,0,0,.08)',
        }}>
          <Button icon={<PlusOutlined />} onClick={() => setAddNodeOpen(true)}>添加节点</Button>
          <Tooltip title="自动布局">
            <Button icon={<ClusterOutlined />} onClick={handleAutoLayout} />
          </Tooltip>
          <Tooltip title="适应画布">
            <Button icon={<AimOutlined />} onClick={handleFit} />
          </Tooltip>
          <Tooltip title="刷新数据">
            <Button icon={<ReloadOutlined />} onClick={() => refetch()} />
          </Tooltip>
        </div>

        {/* 标题 */}
        <div style={{
          position: 'absolute', top: 12, right: 12, zIndex: 10,
          background: '#fff', padding: '8px 14px', borderRadius: 8,
          boxShadow: '0 2px 8px rgba(0,0,0,.08)',
        }}>
          <Space>
            <ApartmentOutlined style={{ color: '#3b82f6' }} />
            <Text strong>{data.name}</Text>
            <Tag color="blue">{data.nodes.length} 节点</Tag>
            <Tag color="purple">{data.edges.length} 边</Tag>
          </Space>
        </div>

        <ReactFlow
          nodes={rfNodes}
          edges={rfEdges}
          nodeTypes={nodeTypes}
          edgeTypes={edgeTypes}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={onConnect}
          onNodeDragStop={onNodeDragStop}
          onNodeDoubleClick={onNodeDoubleClick}
          onNodeClick={(_: unknown, node: Node) => setSelectedNodeId(node.id)}
          fitView
          deleteKeyCode={['Delete', 'Backspace']}
          proOptions={{ hideAttribution: true }}
          edgesFocusable
          connectOnClick
        >
          <Background variant={BackgroundVariant.Dots} gap={20} size={1} color="#cbd5e1" />
          <Controls showInteractive={false} position="bottom-left" />
          <MiniMap
            nodeColor="#3b82f6"
            nodeStrokeWidth={3}
            position="bottom-right"
            style={{ background: '#fff', border: '1px solid #e5e7eb', borderRadius: 8 }}
          />
        </ReactFlow>
      </div>

      {/* 右侧：Tabs 面板 */}
      <div style={{ width: 320, display: 'flex', flexDirection: 'column', background: '#fff', borderRadius: 8, border: '1px solid #e5e7eb' }}>
        <Tabs
          defaultActiveKey="node"
          size="small"
          style={{ padding: '0 8px' }}
          items={[
            {
              key: 'node',
              label: '节点属性',
              children: (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 12, padding: '8px 4px 12px' }}>
                  {selectedNode ? (
                    <NodeProperties
                      node={selectedNode}
                      tables={tables}
                      onUpdate={(payload) => {
                        const nid = Number(selectedNode.id)
                        updateNodeMut.mutate(nid, payload)
                        // 本地更新
                        setRfNodes(ns => ns.map(n => {
                          if (n.id !== selectedNode.id) return n
                          const newData = { ...(n.data as unknown as WorkflowNode), ...payload }
                          return { ...n, data: newData as unknown as Record<string, unknown> }
                        }))
                      }}
                      onDelete={handleDeleteNode}
                      isDeleting={removeNodeMut.isPending}
                    />
                  ) : (
                    <Text type="secondary" style={{ fontSize: 13 }}>点击节点查看/编辑属性</Text>
                  )}

                  <Card title="说明" size="small" styles={{ body: { padding: 12 } }}>
                    <div style={{ fontSize: 12, color: '#6b7280', lineHeight: 1.7 }}>
                      <div>• <strong>双击节点</strong> → 跳转绑定的数据表</div>
                      <div>• <strong>拖动手柄</strong> → 连线创建边</div>
                      <div>• <strong>Delete 键</strong> → 删除选中的节点/边</div>
                      <div>• <strong>拖动节点</strong> → 位置自动保存</div>
                    </div>
                  </Card>
                </div>
              ),
            },
            {
              key: 'graph',
              label: '关系图',
              children: (
                <div style={{ padding: '8px 4px 12px' }}>
                  <GraphMiniPanel
                    workspaceId={wid!}
                    onExpand={() => setGraphDrawerOpen(true)}
                    onNavigateToTable={(tid) => navigate(`/w/${wid}/tables/${tid}`)}
                  />
                </div>
              ),
            },
          ]}
        />
      </div>

      {/* 添加节点弹窗 */}
      <Modal
        title="添加节点"
        open={addNodeOpen}
        onCancel={() => { setAddNodeOpen(false); setAddNodeName(''); setAddNodeTableId(null) }}
        onOk={() => {
          if (!addNodeName.trim()) { message.warning('请输入节点名称'); return }
          addNodeMut.mutate()
        }}
        confirmLoading={addNodeMut.isPending}
      >
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <div>
            <div style={{ marginBottom: 4, fontSize: 13 }}>节点名称 *</div>
            <Input placeholder="如：需求审核" value={addNodeName} onChange={e => setAddNodeName(e.target.value)} />
          </div>
          <div>
            <div style={{ marginBottom: 4, fontSize: 13 }}>绑定数据表（可选）</div>
            <Select
              style={{ width: '100%' }}
              allowClear
              placeholder="选择数据表"
              value={addNodeTableId}
              onChange={v => setAddNodeTableId(v ?? null)}
              options={tables.map((t: any) => ({ label: t.name, value: t.id }))}
            />
          </div>
        </div>
      </Modal>

      {/* 关系图大图抽屉 */}
      <Drawer
        title="表关系图（完整）"
        open={graphDrawerOpen}
        onClose={() => setGraphDrawerOpen(false)}
        width={800}
        destroyOnClose
      >
        <GraphFullPanel
          workspaceId={wid!}
          onNavigateToTable={(tid) => {
            setGraphDrawerOpen(false)
            navigate(`/w/${wid}/tables/${tid}`)
          }}
        />
      </Drawer>
    </div>
  )
}

// ── 节点属性面板 ─────────────────────────────────────

interface NodePropertiesProps {
  node: Node
  tables: any[]
  onUpdate: (payload: Record<string, unknown>) => void
  onDelete: () => void
  isDeleting?: boolean
}

function NodeProperties({ node, tables, onUpdate, onDelete, isDeleting }: NodePropertiesProps) {
  const n = node.data as unknown as WorkflowNode
  const [name, setName] = useState(n.name)
  const [tableId, setTableId] = useState<ID | null>(n.table_id ?? null)

  useEffect(() => {
    setName(n.name)
    setTableId(n.table_id ?? null)
  }, [n.id, n.name, n.table_id])

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div>
        <div style={{ marginBottom: 4, fontSize: 13, color: '#6b7280' }}>节点 ID</div>
        <Text code>{n.id}</Text>
      </div>
      <div>
        <div style={{ marginBottom: 4, fontSize: 13 }}>名称</div>
        <Space.Compact style={{ width: '100%' }}>
          <Input value={name} onChange={e => setName(e.target.value)} />
          <Button
            type="primary"
            icon={<SaveOutlined />}
            onClick={() => {
              if (!name.trim()) { message.warning('名称不能为空'); return }
              onUpdate({ name: name.trim() })
            }}
          />
        </Space.Compact>
      </div>
      <div>
        <div style={{ marginBottom: 4, fontSize: 13 }}>绑定数据表</div>
        <Space.Compact style={{ width: '100%' }}>
          <Select
            style={{ flex: 1 }}
            allowClear
            placeholder="选择数据表"
            value={tableId}
            onChange={v => setTableId(v ?? null)}
            options={tables.map((t: any) => ({ label: t.name, value: t.id }))}
          />
          <Button
            type="primary"
            icon={<SaveOutlined />}
            onClick={() => onUpdate({ table_id: tableId })}
          />
        </Space.Compact>
      </div>
      {n.table && (
        <Descriptions size="small" column={1} bordered>
          <Descriptions.Item label="绑定表">{n.table.name}</Descriptions.Item>
          <Descriptions.Item label="行数">{n.table.row_count ?? '-'}</Descriptions.Item>
          <Descriptions.Item label="视图数">{n.table.view_count}</Descriptions.Item>
        </Descriptions>
      )}
      <Button danger block icon={<DeleteOutlined />} onClick={onDelete} loading={isDeleting}>
        删除节点
      </Button>
    </div>
  )
}

// ── 外层 Provider ────────────────────────────────────

export default function WorkflowEditorPage() {
  return (
    <ReactFlowProvider>
      <WorkflowEditorInner />
    </ReactFlowProvider>
  )
}
