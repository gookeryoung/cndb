/** 问题详情页 — 描述 + 状态流转（关闭/重开）+ 评论列表/发表 + 事件流.
 *
 * 数据源 issuesApi.get（本体 + comments + events）；
 * 关闭/重开门控：工作区 owner/editor 或创建者本人（与后端一致，仅做入口隐藏，后端仍兜底 403）。
 * queryKey 约定：['issue', wid, tid, issueId]。
 */

import { useState } from 'react'
import {
  App as AntApp, Button, Card, Empty, Input, Space, Spin, Tag, Typography,
} from 'antd'
import { ArrowLeftOutlined, CheckOutlined, RedoOutlined } from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate, useParams } from 'react-router-dom'
import { formatDateTime } from '@/utils/datetime'
import { issuesApi, workspaceApi } from '@/api'
import type { IssueComment, IssueEvent, WorkspaceRole } from '@/api'
import { memberDisplayName, useMemberNameMap } from '@/hooks/useMemberNames'
import { useAuthStore } from '@/store'
import { ISSUE_CATEGORY_META } from './IssuesPage'

const { Text, Title, Paragraph } = Typography

const EVENT_TEXT: Record<IssueEvent['action'], string> = {
  created: '创建了问题',
  closed: '关闭了问题',
  reopened: '重开了问题',
}

export default function IssueDetailPage() {
  const { wid = '', tid = '', issueId = '' } = useParams<{ wid: string; tid: string; issueId: string }>()
  const navigate = useNavigate()
  const { message } = AntApp.useApp()
  const queryClient = useQueryClient()
  const user = useAuthStore(s => s.user)
  const [commentDraft, setCommentDraft] = useState('')

  const detailKey = ['issue', wid, tid, issueId] as const

  const { data: issue, isLoading } = useQuery({
    queryKey: detailKey,
    queryFn: () => issuesApi.get(wid, tid, issueId),
    enabled: !!wid && !!tid && !!issueId,
  })

  // 工作区信息：角色门控（owner/editor 可流转）+ 成员名映射（评论/事件展示）
  const { data: wsDetail } = useQuery({
    queryKey: ['workspace-detail', wid],
    queryFn: () => workspaceApi.get(wid),
    enabled: !!wid,
  })
  const nameById = useMemberNameMap(wid)

  const myRole = (wsDetail?.current_user_role ?? null) as WorkspaceRole | null
  const isCreator = !!user && issue?.created_by_id != null && String(issue.created_by_id) === String(user.id)
  const canManage = myRole === 'owner' || myRole === 'editor' || isCreator

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: detailKey })
    queryClient.invalidateQueries({ queryKey: ['issues', wid, tid] })
  }

  const close = useMutation({
    mutationFn: () => issuesApi.close(wid, tid, issueId),
    onSuccess: (d) => {
      message.success('问题已关闭')
      queryClient.setQueryData(detailKey, d)
      invalidate()
    },
    onError: (err) => message.error(err instanceof Error ? err.message : '关闭失败'),
  })

  const reopen = useMutation({
    mutationFn: () => issuesApi.reopen(wid, tid, issueId),
    onSuccess: (d) => {
      message.success('问题已重开')
      queryClient.setQueryData(detailKey, d)
      invalidate()
    },
    onError: (err) => message.error(err instanceof Error ? err.message : '重开失败'),
  })

  const addComment = useMutation({
    mutationFn: (content: string) => issuesApi.addComment(wid, tid, issueId, content),
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

  if (isLoading) {
    return <div style={{ padding: 48, textAlign: 'center' }}><Spin /></div>
  }
  if (!issue) {
    return <div style={{ padding: 24 }}><Empty description="未找到该问题" /></div>
  }

  const catMeta = ISSUE_CATEGORY_META[issue.category] ?? { label: issue.category, color: 'default' }

  return (
    <div style={{ padding: '16px 24px', maxWidth: 860, margin: '0 auto' }}>
      {/* 返回列表 */}
      <Button
        type="text"
        icon={<ArrowLeftOutlined />}
        onClick={() => navigate(`/w/${wid}/tables/${tid}/issues`)}
        style={{ marginBottom: 8 }}
      >
        返回问题清单
      </Button>

      <Title level={4} style={{ marginBottom: 8 }}>
        <Text type="secondary">#{issue.id} </Text>
        {issue.title}
      </Title>
      <Space size={8} wrap style={{ marginBottom: 16 }}>
        <Tag color={issue.status === 'open' ? 'green' : 'default'}>{issue.status === 'open' ? '待处理' : '已关闭'}</Tag>
        <Tag color={catMeta.color}>{catMeta.label}</Tag>
        {canManage && (issue.status === 'open' ? (
          <Button size="small" icon={<CheckOutlined />} loading={close.isPending} onClick={() => close.mutate()}>
            关闭问题
          </Button>
        ) : (
          <Button size="small" icon={<RedoOutlined />} loading={reopen.isPending} onClick={() => reopen.mutate()}>
            重开问题
          </Button>
        ))}
      </Space>

      <Card size="small" style={{ marginBottom: 16 }}>
        {issue.description
          ? <Paragraph style={{ marginBottom: 0, whiteSpace: 'pre-wrap' }}>{issue.description}</Paragraph>
          : <Text type="secondary" italic>（无描述）</Text>}
      </Card>

      {/* 评论 */}
      <Title level={5}>评论（{issue.comments.length}）</Title>
      {issue.comments.length === 0
        ? <Empty description="暂无评论" image={Empty.PRESENTED_IMAGE_SIMPLE} />
        : issue.comments.map((c: IssueComment) => (
          <Card key={c.id} size="small" style={{ marginBottom: 8 }}>
            <Text strong>{memberDisplayName(nameById, c.created_by_id, '已注销用户')}</Text>
            <Text type="secondary" style={{ marginLeft: 8, fontSize: 12 }}>{formatDateTime(c.created_at)}</Text>
            <Paragraph style={{ marginBottom: 0, marginTop: 4, whiteSpace: 'pre-wrap' }}>{c.content}</Paragraph>
          </Card>
        ))}

      <div style={{ marginTop: 8, marginBottom: 24 }}>
        <Input.TextArea
          rows={3}
          value={commentDraft}
          onChange={(e) => setCommentDraft(e.target.value)}
          placeholder="写下评论…"
          maxLength={2000}
        />
        <Button
          type="primary"
          style={{ marginTop: 8 }}
          disabled={!commentDraft.trim()}
          loading={addComment.isPending}
          onClick={submitComment}
        >
          发表评论
        </Button>
      </div>

      {/* 事件流 */}
      <Title level={5}>动态</Title>
      <div>
        {issue.events.map((e: IssueEvent) => (
          <div key={e.id} style={{ padding: '4px 0' }}>
            <Text type="secondary">
              <Text strong>{memberDisplayName(nameById, e.actor_id)}</Text>
              {' '}{EVENT_TEXT[e.action] ?? e.action} · {formatDateTime(e.created_at)}
            </Text>
          </div>
        ))}
      </div>
    </div>
  )
}
