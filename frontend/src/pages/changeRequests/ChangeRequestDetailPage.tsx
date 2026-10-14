/** 修改申请详情页 — items 字段级 diff + 逐项 merge 决策 + 流转 + 评论 + update-base.
 *
 * 数据源 changeRequestsApi.get（本体 + items[base_values/values/current_values/field_conflicts] + actions）。
 * 门控（前端仅隐藏入口，后端 403 兜底）：
 * - 合并/重开：工作区 owner/editor；
 * - 关闭：owner/editor 或提交人；
 * - update-base：提交人本人（stale 时刷新基准快照）。
 * queryKey 约定：['change-request', wid, tid, requestId]。
 */

import { useState } from 'react'
import {
  App as AntApp, Button, Card, Empty, Input, Segmented, Space, Spin, Tag, Typography,
} from 'antd'
import { ArrowLeftOutlined, CheckOutlined, RedoOutlined, SyncOutlined } from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate, useParams } from 'react-router-dom'
import { FieldDiffTable } from '@/components/DiffView'
import { formatDateTime } from '@/utils/datetime'
import { changeRequestsApi, workspaceApi } from '@/api'
import type { ChangeActionItem, ChangeItemDetail, ChangeOp, WorkspaceRole } from '@/api'
import { memberDisplayName, useMemberNameMap } from '@/hooks/useMemberNames'
import { useAuthStore } from '@/store'

const { Text, Title, Paragraph } = Typography

type Decision = 'apply' | 'skip'

const OP_META: Record<ChangeOp, { label: string; color: string }> = {
  create: { label: '新增', color: 'green' },
  update: { label: '修改', color: 'blue' },
  delete: { label: '删除', color: 'red' },
}

const STATUS_META: Record<string, { label: string; color: string }> = {
  open: { label: '待审核', color: 'green' },
  merged: { label: '已合并', color: 'purple' },
  closed: { label: '已关闭', color: 'default' },
}

const ACTION_TEXT: Record<ChangeActionItem['action'], string> = {
  comment: '评论',
  merge: '合并了申请',
  close: '关闭了申请',
  reopen: '重开了申请',
  update_base: '刷新了基准快照',
}

export default function ChangeRequestDetailPage() {
  const { wid = '', tid = '', requestId = '' } = useParams<{ wid: string; tid: string; requestId: string }>()
  const navigate = useNavigate()
  const { message } = AntApp.useApp()
  const queryClient = useQueryClient()
  const user = useAuthStore(s => s.user)
  const nameById = useMemberNameMap(wid)
  const [commentDraft, setCommentDraft] = useState('')
  /** 逐项合并决策：itemId → apply/skip；仅记录用户显式选择，未选择的项在合并时默认 apply */
  const [decisions, setDecisions] = useState<Record<string, Decision>>({})
  const [mergeComment, setMergeComment] = useState('')

  const detailKey = ['change-request', wid, tid, requestId] as const

  const { data: cr, isLoading } = useQuery({
    queryKey: detailKey,
    queryFn: () => changeRequestsApi.get(wid, tid, requestId),
    enabled: !!wid && !!tid && !!requestId,
  })

  const { data: wsDetail } = useQuery({
    queryKey: ['workspace-detail', wid],
    queryFn: () => workspaceApi.get(wid),
    enabled: !!wid,
  })

  const myRole = (wsDetail?.current_user_role ?? null) as WorkspaceRole | null
  const canReview = myRole === 'owner' || myRole === 'editor'
  const isSubmitter = !!user && cr?.submitted_by_id != null && String(cr.submitted_by_id) === String(user.id)

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: detailKey })
    queryClient.invalidateQueries({ queryKey: ['change-requests', wid, tid] })
    queryClient.invalidateQueries({ queryKey: ['pending-changes', `${wid}/${tid}`] })
    queryClient.invalidateQueries({ queryKey: ['table-records', `${wid}/${tid}`] })
  }

  const merge = useMutation({
    // 决策载荷以 cr.items 为准构建，用户显式选择（decisions）覆盖其上，未选择的项默认 apply
    mutationFn: () => changeRequestsApi.merge(wid, tid, requestId, {
      items: (cr?.items ?? []).map(it => ({
        item_id: it.id,
        action: decisions[String(it.id)] ?? 'apply' as Decision,
      })),
      comment: mergeComment.trim() || undefined,
    }),
    onSuccess: (res) => {
      message.success(`合并完成：应用 ${res.applied} 项，跳过 ${res.skipped} 项`)
      queryClient.setQueryData(detailKey, res.request)
      setMergeComment('')
      invalidate()
    },
    onError: (err) => message.error(err instanceof Error ? err.message : '合并失败'),
  })

  const close = useMutation({
    mutationFn: () => changeRequestsApi.close(wid, tid, requestId),
    onSuccess: (d) => {
      message.success('申请已关闭')
      queryClient.setQueryData(detailKey, d)
      invalidate()
    },
    onError: (err) => message.error(err instanceof Error ? err.message : '关闭失败'),
  })

  const reopen = useMutation({
    mutationFn: () => changeRequestsApi.reopen(wid, tid, requestId),
    onSuccess: (d) => {
      message.success('申请已重开')
      queryClient.setQueryData(detailKey, d)
      invalidate()
    },
    onError: (err) => message.error(err instanceof Error ? err.message : '重开失败'),
  })

  const updateBase = useMutation({
    mutationFn: () => changeRequestsApi.updateBase(wid, tid, requestId),
    onSuccess: (d) => {
      message.success('基准快照已刷新')
      queryClient.setQueryData(detailKey, d)
      invalidate()
    },
    onError: (err) => message.error(err instanceof Error ? err.message : '刷新基准失败'),
  })

  const addComment = useMutation({
    mutationFn: (content: string) => changeRequestsApi.addComment(wid, tid, requestId, content),
    onSuccess: () => {
      setCommentDraft('')
      invalidate()
    },
    onError: (err) => message.error(err instanceof Error ? err.message : '发表评论失败'),
  })

  const submitComment = () => {
    const content = commentDraft.trim()
    if (!content) return
    addComment.mutate(content)
  }

  const handleMerge = () => merge.mutate()

  if (isLoading) {
    return <div style={{ padding: 48, textAlign: 'center' }}><Spin /></div>
  }
  if (!cr) {
    return <div style={{ padding: 24 }}><Empty description="未找到该修改申请" /></div>
  }

  const canMergeNow = canReview && cr.status === 'open'
  const showUpdateBase = isSubmitter && cr.status === 'open' && cr.stale

  return (
    <div style={{ padding: '16px 24px', maxWidth: 860, margin: '0 auto' }}>
      <Button
        type="text"
        icon={<ArrowLeftOutlined />}
        onClick={() => navigate(`/w/${wid}/tables/${tid}/change-requests`)}
        style={{ marginBottom: 8 }}
      >
        返回修改申请
      </Button>

      <Title level={4} style={{ marginBottom: 8 }}>
        <Text type="secondary">#{cr.id} </Text>
        {cr.title}
      </Title>
      <Space size={8} wrap style={{ marginBottom: 8 }}>
        <Tag color={STATUS_META[cr.status]?.color ?? 'default'}>{STATUS_META[cr.status]?.label ?? cr.status}</Tag>
        {cr.stale && <Tag color="warning">基准已过期</Tag>}
        <Text type="secondary">
          {memberDisplayName(nameById, cr.submitted_by_id, '未知')} 提交于 {formatDateTime(cr.created_at)}
        </Text>
      </Space>
      {cr.description && <Paragraph type="secondary" style={{ whiteSpace: 'pre-wrap' }}>{cr.description}</Paragraph>}

      <Space size={8} wrap style={{ marginBottom: 16 }}>
        {showUpdateBase && (
          <Button size="small" icon={<SyncOutlined />} loading={updateBase.isPending} onClick={() => updateBase.mutate()}>
            刷新基准快照
          </Button>
        )}
        {(canReview || isSubmitter) && cr.status === 'open' && (
          <Button size="small" onClick={() => close.mutate()} loading={close.isPending}>关闭申请</Button>
        )}
        {canReview && cr.status === 'closed' && (
          <Button size="small" icon={<RedoOutlined />} loading={reopen.isPending} onClick={() => reopen.mutate()}>
            重开申请
          </Button>
        )}
      </Space>

      {/* 变更项列表（含逐项决策） */}
      <Title level={5}>变更项（{cr.items.length}）</Title>
      {cr.items.map((item: ChangeItemDetail) => (
        <Card key={item.id} size="small" style={{ marginBottom: 8 }}>
          <Space size={8} wrap style={{ marginBottom: item.field_conflicts.length ? undefined : 4 }}>
            <Tag color={OP_META[item.op].color} style={{ marginInlineEnd: 0 }}>{OP_META[item.op].label}</Tag>
            {item.row_id != null && <Text type="secondary">行 #{item.row_id}</Text>}
            {item.field_conflicts.length > 0 && (
              <Text type="danger" style={{ fontSize: 12 }}>{item.field_conflicts.length} 个字段基准已漂移</Text>
            )}
            {canMergeNow && (
              <Segmented
                size="small"
                value={decisions[String(item.id)] ?? 'apply'}
                onChange={(v) => setDecisions(prev => ({ ...prev, [String(item.id)]: v as Decision }))}
                options={[
                  { label: '应用', value: 'apply' },
                  { label: '跳过', value: 'skip' },
                ]}
              />
            )}
          </Space>
          <FieldDiffTable item={item} />
        </Card>
      ))}

      {canMergeNow && (
        <Card size="small" style={{ marginBottom: 24 }}>
          <Input.TextArea
            rows={2}
            value={mergeComment}
            onChange={(e) => setMergeComment(e.target.value)}
            placeholder="合并备注（可选，记录处理说明）"
            maxLength={2000}
          />
          <Button
            type="primary"
            icon={<CheckOutlined />}
            style={{ marginTop: 8 }}
            loading={merge.isPending}
            onClick={handleMerge}
          >
            执行合并
          </Button>
        </Card>
      )}

      {/* 评论 */}
      <Title level={5}>讨论</Title>
      <Input.TextArea
        rows={3}
        value={commentDraft}
        onChange={(e) => setCommentDraft(e.target.value)}
        placeholder="写下评论…"
        maxLength={2000}
      />
      <Button
        type="primary"
        style={{ marginTop: 8, marginBottom: 16 }}
        disabled={!commentDraft.trim()}
        loading={addComment.isPending}
        onClick={submitComment}
      >
        发表评论
      </Button>

      {/* 动作流水 */}
      <Title level={5}>动态</Title>
      <div style={{ marginBottom: 24 }}>
        {cr.actions.map((a: ChangeActionItem) => (
          <div key={a.id} style={{ padding: '4px 0' }}>
            <Text type="secondary">
              <Text strong>{memberDisplayName(nameById, a.acted_by_id)}</Text>
              {' '}{ACTION_TEXT[a.action] ?? a.action}
              {a.comment && <>：<Text>{a.comment}</Text></>}
              {' '}· {formatDateTime(a.created_at)}
            </Text>
          </div>
        ))}
      </div>
    </div>
  )
}
