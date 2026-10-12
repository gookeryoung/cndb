/** 工作区设置 - 审批流配置 Tab — 审批流定义（线性链）的新建 / 编辑 / 删除.
 *
 * 由原 ApprovalFlowsPage 拆出并迁入工作区设置（低频管理功能）。
 * 审批流形态为线性链 start → approval* → end：用「审批节点步骤列表」
 * 抽象编辑（增删/上下移/命名/角色阈值），保存时自动生成 start/end 与链式 edges。
 * 仅 admin/owner 可见该 Tab（由 WorkspaceSettingsContent 门控）。
 */

import { useEffect, useState } from 'react'
import {
  Alert, App as AntApp, Button, Drawer, Empty, Form, Input, Select, Space, Table, Tag, Typography,
} from 'antd'
import type { FormInstance } from 'antd'
import {
  ArrowDownOutlined, ArrowUpOutlined, DeleteOutlined, PlusOutlined,
} from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { workflowApi } from '@/api'
import type {
  WorkflowDefinition, WorkflowListItem, WorkflowPayload,
} from '@/api'

const { Text } = Typography

const ROLE_OPTIONS = [
  { value: 'viewer', label: 'viewer 及以上' },
  { value: 'editor', label: 'editor 及以上' },
  { value: 'admin', label: 'admin 及以上' },
  { value: 'owner', label: 'owner（工作区所有者）' },
]

interface EditorValues {
  name: string
  description?: string
}

/** 审批节点步骤（Drawer 编辑态；保存时自动生成 start/end 与 edges） */
interface Step {
  name: string
  approver_role: string
}

/** 由详情图推导步骤列表：沿 edges 从 start 走链，取 approval 节点 */
function deriveSteps(wf: WorkflowDefinition): Step[] {
  const byId = new Map(wf.nodes.map(n => [n.id, n]))
  const outEdge = new Map(wf.edges.map(e => [e.source, e.target]))
  const start = wf.nodes.find(n => n.node_type === 'start')
  const steps: Step[] = []
  let cur = start ? outEdge.get(start.id) : undefined
  const seen = new Set<number | string>()
  while (cur !== undefined && !seen.has(cur)) {
    seen.add(cur)
    const node = byId.get(cur)
    if (!node) break
    if (node.node_type === 'approval') {
      steps.push({ name: node.name, approver_role: node.approver_role || 'editor' })
    }
    cur = outEdge.get(cur)
  }
  return steps
}

/** 步骤列表 → 线性链载荷（start → approval* → end） */
function buildPayload(name: string, description: string, steps: Step[]): WorkflowPayload {
  const nodes = [
    { key: 's', name: '提交', node_type: 'start' as const },
    ...steps.map((s, i) => ({
      key: `a${i + 1}`,
      name: s.name || `审批 ${i + 1}`,
      node_type: 'approval' as const,
      approver_role: s.approver_role,
    })),
    { key: 'e', name: '结束', node_type: 'end' as const },
  ]
  const edges = nodes.slice(1).map((n, i) => ({ source: nodes[i].key, target: n.key }))
  return { name, description, nodes, edges }
}

/** 审批流配置内容：嵌入工作区设置 Tab 渲染，wid 由父级传入 */
export default function ApprovalFlowsSettings({ wid }: { wid: string }) {
  const { message, modal } = AntApp.useApp()
  const queryClient = useQueryClient()
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [editingId, setEditingId] = useState<number | string | null>(null)
  const [form] = Form.useForm<EditorValues>()

  const { data: flows = [], isLoading } = useQuery<WorkflowListItem[]>({
    queryKey: ['workspaces', wid, 'workflows'],
    queryFn: () => workflowApi.list(wid),
  })

  const remove = useMutation({
    mutationFn: (id: number | string) => workflowApi.remove(wid, id),
    onSuccess: () => {
      message.success('审批流已删除')
      void queryClient.invalidateQueries({ queryKey: ['workspaces', wid, 'workflows'] })
    },
    onError: (err) => message.error(err instanceof Error ? err.message : '删除审批流失败'),
  })

  const confirmDelete = (wf: WorkflowListItem) => {
    modal.confirm({
      title: `删除审批流「${wf.name}」？`,
      content: '已绑定该审批流的表单将无法提交审批（保存表单时需先解绑）。',
      okText: '删除', okType: 'danger', cancelText: '取消',
      onOk: () => remove.mutate(wf.id),
    })
  }

  const columns = [
    {
      title: '审批流名称',
      dataIndex: 'name',
      key: 'name',
      render: (n: string, r: WorkflowListItem) => (
        <a onClick={() => openEdit(r)}>{n}</a>
      ),
    },
    {
      title: '描述',
      dataIndex: 'description',
      key: 'description',
      ellipsis: true,
      render: (d: string) => d || <Text type="secondary" italic>—</Text>,
    },
    {
      title: '审批链',
      key: 'chain',
      render: (_: unknown, r: WorkflowListItem) => <ChainSummary wid={wid} item={r} />,
    },
    {
      title: '操作',
      key: 'actions',
      width: 160,
      render: (_: unknown, r: WorkflowListItem) => (
        <Space size="small">
          <Button size="small" type="link" onClick={() => openEdit(r)}>编辑</Button>
          <Button size="small" type="link" danger icon={<DeleteOutlined />} onClick={() => confirmDelete(r)} />
        </Space>
      ),
    },
  ]

  const openEdit = (wf: WorkflowListItem) => {
    setEditingId(wf.id)
    setDrawerOpen(true)
  }

  return (
    <div>
      <Text type="secondary" style={{ display: 'block', marginBottom: 12 }}>
        配置工作区多步审批流（线性链），并在表单中绑定；经表单提交的数据按链逐级审批，链尾通过才写入数据表。提交与审批记录见顶部「审批中心」。
      </Text>
      <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 12 }}>
        <Button
          type="primary" icon={<PlusOutlined />}
          onClick={() => { setEditingId(null); setDrawerOpen(true) }}
        >新建审批流</Button>
      </div>
      <Table
        rowKey="id"
        size="middle"
        loading={isLoading}
        columns={columns}
        dataSource={flows}
        pagination={false}
        locale={{ emptyText: <Empty description="还没有审批流，点击右上角新建" /> }}
      />
      <FlowEditorDrawer
        key={editingId ?? 'new'}
        open={drawerOpen}
        wid={wid}
        editingId={editingId}
        form={form}
        onClose={() => { setDrawerOpen(false); setEditingId(null); form.resetFields() }}
      />
    </div>
  )
}

/** 审批链摘要（懒加载详情后展示步骤） */
function ChainSummary({ wid, item }: { wid: string; item: WorkflowListItem }) {
  const { data: detail } = useQuery<WorkflowDefinition>({
    queryKey: ['workspaces', wid, 'workflows', item.id],
    queryFn: () => workflowApi.get(wid, item.id),
  })
  if (!detail) return <Text type="secondary">…</Text>
  const steps = deriveSteps(detail)
  if (steps.length === 0) return <Text type="secondary">（无审批节点）</Text>
  return (
    <Space size={[4, 4]} wrap>
      {steps.map((s, i) => (
        <Tag key={i} color="geekblue">{s.name} · {s.approver_role}</Tag>
      ))}
    </Space>
  )
}

interface FlowDrawerProps {
  open: boolean
  wid: string
  editingId: number | string | null
  form: FormInstance<EditorValues>
  onClose: () => void
}

function FlowEditorDrawer({ open, wid, editingId, form, onClose }: FlowDrawerProps) {
  const { message } = AntApp.useApp()
  const queryClient = useQueryClient()
  const [steps, setSteps] = useState<Step[]>([])

  useEffect(() => {
    if (!open) return
    if (editingId) {
      workflowApi.get(wid, editingId).then(detail => {
        form.setFieldsValue({ name: detail.name, description: detail.description })
        setSteps(deriveSteps(detail))
      }).catch(() => message.error('加载审批流详情失败'))
    } else {
      form.resetFields()
      setSteps([{ name: '主管审批', approver_role: 'editor' }])
    }
  }, [open]) // eslint-disable-line react-hooks/exhaustive-deps

  const create = useMutation({
    mutationFn: (payload: WorkflowPayload) => workflowApi.create(wid, payload),
    onSuccess: () => { message.success('审批流已创建'); finish() },
    onError: (err) => message.error(err instanceof Error ? err.message : '创建审批流失败'),
  })
  const update = useMutation({
    mutationFn: ({ id, payload }: { id: number | string; payload: WorkflowPayload }) =>
      workflowApi.update(wid, id, payload),
    onSuccess: () => { message.success('审批流已保存'); finish() },
    onError: (err) => message.error(err instanceof Error ? err.message : '保存审批流失败'),
  })

  const finish = () => {
    onClose()
    void queryClient.invalidateQueries({ queryKey: ['workspaces', wid, 'workflows'] })
  }

  const setStep = (i: number, patch: Partial<Step>) => {
    setSteps(prev => prev.map((s, idx) => (idx === i ? { ...s, ...patch } : s)))
  }
  const move = (i: number, dir: -1 | 1) => {
    setSteps(prev => {
      const j = i + dir
      if (j < 0 || j >= prev.length) return prev
      const copy = [...prev]
      ;[copy[i], copy[j]] = [copy[j], copy[i]]
      return copy
    })
  }

  const handleSubmit = (v: EditorValues) => {
    if (steps.length === 0) {
      message.error('至少需要一个审批节点')
      return
    }
    const payload = buildPayload(v.name, v.description || '', steps)
    if (editingId) update.mutate({ id: editingId, payload })
    else create.mutate(payload)
  }

  return (
    <Drawer
      title={editingId ? '编辑审批流' : '新建审批流'}
      open={open}
      onClose={onClose}
      width={640}
      destroyOnHidden
      footer={
        <div style={{ textAlign: 'right' }}>
          <Space>
            <Button onClick={onClose}>取消</Button>
            <Button type="primary" loading={create.isPending || update.isPending} onClick={() => form.submit()}>
              {editingId ? '保存' : '创建'}
            </Button>
          </Space>
        </div>
      }
    >
      <Form form={form} layout="vertical" onFinish={handleSubmit}>
        <Form.Item name="name" label="审批流名称" rules={[{ required: true, message: '请输入名称' }]}>
          <Input placeholder="例如：请假审批" />
        </Form.Item>
        <Form.Item name="description" label="描述（可选）">
          <Input.TextArea rows={1} placeholder="简单说明审批流用途" />
        </Form.Item>

        <Form.Item label="审批节点（按顺序逐级审批）" required>
          <div style={{ border: '1px solid var(--cn-border, #eee)', borderRadius: 8, padding: 8 }}>
            <Tag style={{ marginBottom: 8 }}>开始（提交）</Tag>
            {steps.map((s, i) => (
              <div
                key={i}
                data-testid={`approval-step-${i}`}
                style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '4px 0' }}
              >
                <Input
                  style={{ width: 180 }}
                  value={s.name}
                  aria-label={`第 ${i + 1} 级审批名称`}
                  placeholder="节点名称"
                  onChange={e => setStep(i, { name: e.target.value })}
                />
                <Select
                  style={{ width: 180 }}
                  value={s.approver_role}
                  aria-label={`第 ${i + 1} 级审批角色`}
                  options={ROLE_OPTIONS}
                  onChange={v => setStep(i, { approver_role: v })}
                />
                <Space size={0} style={{ marginLeft: 'auto' }}>
                  <Button type="text" size="small" icon={<ArrowUpOutlined />} disabled={i === 0} aria-label={`上移第 ${i + 1} 级审批`} onClick={() => move(i, -1)} />
                  <Button type="text" size="small" icon={<ArrowDownOutlined />} disabled={i === steps.length - 1} aria-label={`下移第 ${i + 1} 级审批`} onClick={() => move(i, 1)} />
                  <Button
                    type="text" size="small" danger icon={<DeleteOutlined />}
                    aria-label={`删除第 ${i + 1} 级审批`}
                    onClick={() => setSteps(prev => prev.filter((_, idx) => idx !== i))}
                  />
                </Space>
              </div>
            ))}
            <Tag style={{ margin: '8px 0 0' }}>结束（通过后数据落库）</Tag>
            <div style={{ marginTop: 8 }}>
              <Button
                size="small" icon={<PlusOutlined />}
                onClick={() => setSteps(prev => [...prev, { name: `审批 ${prev.length + 1}`, approver_role: 'editor' }])}
              >添加审批节点</Button>
            </div>
          </div>
        </Form.Item>
        <Alert
          type="info" showIcon
          message="审批按角色阈值判定：达到节点配置角色及以上的成员均可审批；链尾通过后数据才写入数据表，任一节点驳回即终止。"
        />
      </Form>
    </Drawer>
  )
}
