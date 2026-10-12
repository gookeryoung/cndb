/** 审批中心页 — /w/:wid/approvals；面向所有成员的高频事务入口.
 *
 * 仅承载审批实例处理：「待我审批」（默认）与「我提交的」两个 Tab；
 * 审批流定义配置已移入工作区设置的「审批流」Tab（低频管理功能）。
 * 页签徽标数据 queryKey 与子 Tab 一致，react-query 去重共享缓存。
 */

import { useMemo } from 'react'
import { useParams } from 'react-router-dom'
import { Tabs, Tag, Typography } from 'antd'
import { AuditOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import {
  APPROVAL_STATUS_TEXT, approvalApi,
} from '@/api'
import type { ApprovalInstance, ApprovalStatus } from '@/api'
import ApprovalInboxTab, { STATUS_COLOR } from './ApprovalInboxTab'

const { Title, Text } = Typography

export default function ApprovalCenterPage() {
  const { wid } = useParams<{ wid: string }>()

  // 页签徽标数据：queryKey 与 ApprovalInboxTab 内部一致，进入子 Tab 命中共享缓存
  const { data: pendingItems = [], isSuccess: pendingReady } = useQuery<ApprovalInstance[]>({
    queryKey: ['workspaces', wid, 'approvals', 'pending_for_me'],
    queryFn: () => approvalApi.list(wid!, 'pending_for_me'),
  })
  const { data: mineItems = [], isSuccess: mineReady } = useQuery<ApprovalInstance[]>({
    queryKey: ['workspaces', wid, 'approvals', 'mine'],
    queryFn: () => approvalApi.list(wid!, 'mine'),
  })

  /** 我提交的：按状态类别计数（待审批=金 / 已通过=绿 / 已驳回=红，沿用 STATUS_COLOR） */
  const mineStatusCount = useMemo(() => {
    const c: Record<ApprovalStatus, number> = { pending: 0, approved: 0, rejected: 0 }
    for (const it of mineItems) c[it.status] += 1
    return c
  }, [mineItems])

  return (
    <div style={{ padding: 24 }}>
      <Title level={3} style={{ margin: 0, marginBottom: 12 }}>
        <AuditOutlined style={{ marginRight: 8 }} />审批中心
      </Title>
      <Text type="secondary" style={{ display: 'block', marginBottom: 16 }}>
        处理提交到你的审批与查看自己提交的进度；审批流的新建与编辑在工作区设置的「审批流」中配置。
      </Text>
      <Tabs
        defaultActiveKey="inbox"
        items={[
          {
            key: 'inbox',
            label: (
              <span>
                待我审批
                {pendingReady && (pendingItems.length > 0
                  ? <Tag color="gold" className="cn-ws-tab-count-tag">{pendingItems.length}</Tag>
                  : <span className="cn-ws-tab-count">0</span>)}
              </span>
            ),
            children: <ApprovalInboxTab wid={wid!} scope="pending_for_me" />,
          },
          {
            key: 'mine',
            label: (
              <span>
                我提交的
                {mineReady && (Object.keys(APPROVAL_STATUS_TEXT) as ApprovalStatus[]).map(s => (
                  <Tag key={s} color={STATUS_COLOR[s]} className="cn-ws-tab-count-tag">
                    {APPROVAL_STATUS_TEXT[s]} {mineStatusCount[s]}
                  </Tag>
                ))}
              </span>
            ),
            children: <ApprovalInboxTab wid={wid!} scope="mine" />,
          },
        ]}
      />
    </div>
  )
}
