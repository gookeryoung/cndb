/** 审批实例收件箱 Tab — 待我审批（pending_for_me）/ 我提交的（mine）共用列表.
 *
 * 由原 ApprovalFlowsPage 拆出，供审批中心页引用；scope 决定列差异：
 * pending_for_me 显示提交人与通过/驳回操作列，mine 显示落库行列。
 * STATUS_COLOR 一并导出，供审批中心页签徽标复用。
 */

import { App as AntApp, Button, Empty, Space, Table, Tag, Typography } from 'antd'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  APPROVAL_STATUS_TEXT, approvalApi,
} from '@/api'
import type { ApprovalInstance, ApprovalStatus } from '@/api'

const { Text } = Typography

/** 实例状态 → 徽标配色（金=待审 / 绿=通过 / 红=驳回） */
export const STATUS_COLOR: Record<ApprovalStatus, string> = {
  pending: 'gold',
  approved: 'green',
  rejected: 'red',
}

/** 审批实例收件箱：scope='pending_for_me' 待我审批（含操作列）；scope='mine' 我提交的（含落库行列） */
export default function ApprovalInboxTab({ wid, scope }: { wid: string; scope: 'pending_for_me' | 'mine' }) {
  const { message, modal } = AntApp.useApp()
  const queryClient = useQueryClient()

  const { data: items = [], isLoading } = useQuery<ApprovalInstance[]>({
    queryKey: ['workspaces', wid, 'approvals', scope],
    queryFn: () => approvalApi.list(wid, scope),
  })

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ['workspaces', wid, 'approvals'] })
  }

  const act = useMutation({
    mutationFn: ({ id, action }: { id: number | string; action: 'approve' | 'reject' }) =>
      action === 'approve' ? approvalApi.approve(wid, id) : approvalApi.reject(wid, id),
    onSuccess: (inst) => {
      message.success(inst.status === 'approved' ? '已通过，数据已落库' : inst.status === 'rejected' ? '已驳回' : '已审批')
      invalidate()
    },
    onError: (err) => message.error(err instanceof Error ? err.message : '审批操作失败'),
  })

  const onAction = (inst: ApprovalInstance, action: 'approve' | 'reject') => {
    if (action === 'approve') {
      act.mutate({ id: inst.id, action })
      return
    }
    modal.confirm({
      title: '驳回这条提交？',
      content: '驳回后实例终止，数据不会写入数据表。',
      okText: '驳回', okType: 'danger', cancelText: '取消',
      onOk: () => act.mutate({ id: inst.id, action }),
    })
  }

  const columns = [
    { title: '审批流', dataIndex: 'workflow_name', key: 'workflow_name', width: 140 },
    { title: '来源表单', dataIndex: 'form_name', key: 'form_name', width: 140 },
    ...(scope === 'mine'
      ? []
      : [{ title: '提交人', dataIndex: 'submitted_by_name', key: 'submitted_by_name', width: 100 }]),
    {
      title: '提交数据',
      dataIndex: 'values',
      key: 'values',
      ellipsis: true,
      render: (v: Record<string, unknown>) => (
        <Text style={{ fontFamily: 'monospace', fontSize: 12 }}>
          {Object.entries(v).map(([k, val]) => `${k}: ${String(val)}`).join('；') || '—'}
        </Text>
      ),
    },
    {
      title: '当前节点',
      key: 'current',
      width: 140,
      render: (_: unknown, r: ApprovalInstance) =>
        r.status === 'pending'
          ? <Tag color="gold">{r.current_node_name || r.current_approver_role || '待审批'}</Tag>
          : <Tag color={STATUS_COLOR[r.status]}>{APPROVAL_STATUS_TEXT[r.status]}</Tag>,
    },
    ...(scope === 'pending_for_me'
      ? [{
          title: '操作',
          key: 'actions',
          width: 150,
          render: (_: unknown, r: ApprovalInstance) => (
            <Space size="small">
              <Button
                size="small" type="primary"
                aria-label={`批准 ${r.form_name}`}
                loading={act.isPending && act.variables?.id === r.id}
                onClick={() => onAction(r, 'approve')}
              >通过</Button>
              <Button size="small" danger aria-label={`驳回 ${r.form_name}`} onClick={() => onAction(r, 'reject')}>驳回</Button>
            </Space>
          ),
        }]
      : [{
          title: '落库行',
          dataIndex: 'record_id',
          key: 'record_id',
          width: 90,
          render: (rid: number | null) => (rid ? <Tag color="green">#{rid}</Tag> : <Text type="secondary">—</Text>),
        }]),
  ]

  return (
    <Table
      rowKey="id"
      size="middle"
      loading={isLoading}
      columns={columns}
      dataSource={items}
      pagination={false}
      locale={{ emptyText: <Empty description={scope === 'pending_for_me' ? '暂无待你审批的提交' : '你还没有提交过审批'} /> }}
    />
  )
}
