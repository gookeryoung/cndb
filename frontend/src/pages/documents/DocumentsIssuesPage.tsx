/**
 * 文档区二级导航「问题清单」页 —— 工作区下全部文档的问题反馈.
 *
 * 数据源 `GET /{wid}/document-issues?status=`；支持新建问题（选择所属文档）、
 * 详情抽屉内评论与关闭/重开。类别标签与数据表问题清单共用一套中文文案。
 */

import { useMemo, useState } from 'react'
import {
  App as AntApp, Button, Drawer, Empty, Form, Input, List, Modal, Segmented, Select, Space, Spin, Tag, Typography,
} from 'antd'
import { CheckCircleOutlined, MessageOutlined, PlusOutlined, RedoOutlined, UndoOutlined } from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate, useParams } from 'react-router-dom'

import { workspaceApi } from '@/api'
import { documentsApi } from '@/api/documents'
import type { DocumentIssueCategory, DocumentIssueDetail, DocumentIssueItem } from '@/api/documents'
import { useAuthStore } from '@/store'
import { formatDateTime } from '@/utils/datetime'

const { Text, Title, Paragraph } = Typography

/** 类别 → 中文标签与颜色（与数据表问题清单保持一致） */
export const ISSUE_CATEGORY_META: Record<DocumentIssueCategory, { label: string; color: string }> = {
  data_error: { label: '数据异常', color: 'red' },
  suggestion: { label: '建议', color: 'orange' },
  question: { label: '疑问', color: 'blue' },
  other: { label: '其他', color: 'default' },
}

const EVENT_TEXT: Record<string, string> = {
  created: '创建了问题',
  closed: '关闭了问题',
  reopened: '重开了问题',
}

type StatusFilter = 'open' | 'closed' | 'all'

const STATUS_OPTIONS: Array<{ label: string; value: StatusFilter }> = [
  { label: '待处理', value: 'open' },
  { label: '已关闭', value: 'closed' },
  { label: '全部', value: 'all' },
]

export default function DocumentsIssuesPage() {
  const { wid = '' } = useParams<{ wid: string }>()
  const navigate = useNavigate()
  const { message } = AntApp.useApp()
  const qc = useQueryClient()
  const user = useAuthStore(s => s.user)

  const [status, setStatus] = useState<StatusFilter>('open')
  const [createOpen, setCreateOpen] = useState(false)
  const [detailId, setDetailId] = useState<number | null>(null)
  const [commentDraft, setCommentDraft] = useState('')
  const [form] = Form.useForm<{ document_id: number; title: string; category?: DocumentIssueCategory; description?: string }>()

  const { data: wsDetail } = useQuery({
    queryKey: ['workspace-detail', wid],
    queryFn: () => workspaceApi.get(wid),
    enabled: !!wid,
  })
  const role = wsDetail?.current_user_role ?? null
  const canReview = role === 'owner' || role === 'editor'

  const listKey = ['document-issues', wid, status] as const
  const { data, isLoading } = useQuery({
    queryKey: listKey,
    queryFn: () => documentsApi.issues(wid, { status }),
    enabled: !!wid,
  })

  // 新建问题时的文档候选（文件夹不参与：问题针对内容）
  const { data: tree = [] } = useQuery({
    // key 用数字 wid，与文档页/侧栏共享同一缓存并在其变更时同步失效
    queryKey: ['documents', Number(wid), 'tree'],
    queryFn: () => documentsApi.tree(Number(wid)),
    enabled: !!wid && createOpen,
  })
  const documentOptions = useMemo(
    () => tree.filter(d => !d.is_folder).map(d => ({ value: d.id, label: d.title })),
    [tree],
  )

  const detailKey = ['document-issue', wid, detailId] as const
  const detail = useQuery({
    queryKey: detailKey,
    queryFn: () => documentsApi.issue(wid, detailId!),
    enabled: !!wid && detailId != null,
  })

  const invalidate = () => {
    void qc.invalidateQueries({ queryKey: ['document-issues', wid] })
    if (detailId != null) void qc.invalidateQueries({ queryKey: ['document-issue', wid, detailId] })
  }

  const create = useMutation({
    mutationFn: (v: { document_id: number; title: string; category?: DocumentIssueCategory; description?: string }) =>
      documentsApi.createIssue(wid, v),
    onSuccess: (created) => {
      message.success('问题已提交')
      invalidate()
      setCreateOpen(false)
      form.resetFields()
      setDetailId(created.id)
    },
    onError: (err: unknown) => message.error(err instanceof Error ? err.message : '提交问题失败'),
  })

  const addComment = useMutation({
    mutationFn: (content: string) => documentsApi.addIssueComment(wid, detailId!, content),
    onSuccess: () => {
      setCommentDraft('')
      invalidate()
    },
    onError: (err: unknown) => message.error(err instanceof Error ? err.message : '发表评论失败'),
  })

  const closeIssue = useMutation({
    mutationFn: () => documentsApi.closeIssue(wid, detailId!),
    onSuccess: () => {
      message.success('问题已关闭')
      invalidate()
    },
    onError: (err: unknown) => message.error(err instanceof Error ? err.message : '关闭失败'),
  })

  const reopenIssue = useMutation({
    mutationFn: () => documentsApi.reopenIssue(wid, detailId!),
    onSuccess: () => {
      message.success('问题已重开')
      invalidate()
    },
    onError: (err: unknown) => message.error(err instanceof Error ? err.message : '重开失败'),
  })

  const items = data?.items ?? []
  const current: DocumentIssueDetail | undefined = detail.data
  const canManageCurrent =
    !!current && (canReview || (current.created_by_id != null && String(current.created_by_id) === String(user?.id)))

  return (
    <div className="cn-subpage" style={{ maxWidth: 960, margin: '0 auto' }}>
      <div className="cn-subpage-head">
        <Space size={8} align="center">
          <Title level={5} style={{ margin: 0 }}>
            文档问题清单
          </Title>
          <Text type="secondary">工作区成员均可提交与评论，owner/editor 或创建者可关闭</Text>
        </Space>
        <Space size={8} className="cn-subpage-head-actions">
          <Segmented options={STATUS_OPTIONS} value={status} onChange={v => setStatus(v as StatusFilter)} />
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)} data-testid="doc-issue-create">
            新建问题
          </Button>
        </Space>
      </div>

      <Spin spinning={isLoading}>
        {items.length === 0 ? (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description={status === 'open' ? '暂无待处理问题' : '暂无问题'}
            style={{ padding: 48 }}
          />
        ) : (
          <List
            dataSource={items}
            renderItem={(item: DocumentIssueItem) => (
              <List.Item
                style={{ cursor: 'pointer' }}
                data-testid={`doc-issue-row-${item.id}`}
                onClick={() => setDetailId(item.id)}
                actions={[
                  <span key="comments" aria-label={`评论数 ${item.comment_count}`}>
                    <MessageOutlined style={{ marginRight: 4, color: 'var(--cn-text-secondary)' }} />
                    {item.comment_count}
                  </span>,
                ]}
              >
                <List.Item.Meta
                  title={
                    <Space size={8} wrap>
                      <Tag color={ISSUE_CATEGORY_META[item.category]?.color ?? 'default'} style={{ marginInlineEnd: 0 }}>
                        {ISSUE_CATEGORY_META[item.category]?.label ?? item.category}
                      </Tag>
                      {status === 'all' && item.status === 'closed' && <Tag style={{ marginInlineEnd: 0 }}>已关闭</Tag>}
                      <Text strong>{item.title}</Text>
                    </Space>
                  }
                  description={
                    <Text type="secondary">
                      #{item.id} · {item.document_title ?? `文档 #${item.document_id}`} · 创建于{' '}
                      {formatDateTime(item.created_at)}
                    </Text>
                  }
                />
              </List.Item>
            )}
          />
        )}
      </Spin>

      {/* 新建问题 */}
      <Modal
        title="新建文档问题"
        open={createOpen}
        onCancel={() => setCreateOpen(false)}
        onOk={() => form.validateFields().then(v => create.mutate(v)).catch(() => { /* 校验错误由表单展示 */ })}
        okText="提交"
        okButtonProps={{ loading: create.isPending }}
        destroyOnHidden
      >
        <Form form={form} layout="vertical" initialValues={{ category: 'other' }}>
          <Form.Item name="document_id" label="所属文档" rules={[{ required: true, message: '请选择文档' }]}>
            <Select
              showSearch
              optionFilterProp="label"
              placeholder="选择要反馈的文档"
              options={documentOptions}
              data-testid="doc-issue-document"
            />
          </Form.Item>
          <Form.Item
            name="title"
            label="标题"
            rules={[{ required: true, message: '请输入标题' }, { max: 255, message: '标题最长 255 字' }]}
          >
            <Input placeholder="一句话描述问题" maxLength={255} showCount />
          </Form.Item>
          <Form.Item name="category" label="类别">
            <Select
              options={(Object.keys(ISSUE_CATEGORY_META) as DocumentIssueCategory[]).map(c => ({
                value: c,
                label: ISSUE_CATEGORY_META[c].label,
              }))}
            />
          </Form.Item>
          <Form.Item name="description" label="描述（可选）">
            <Input.TextArea rows={4} maxLength={2000} showCount placeholder="补充上下文、期望结果等" />
          </Form.Item>
        </Form>
      </Modal>

      {/* 问题详情 */}
      <Drawer
        title={current ? `问题 #${current.id}` : '问题详情'}
        size={720}
        open={detailId != null}
        onClose={() => setDetailId(null)}
      >
        {detail.isLoading ? (
          <div style={{ padding: 24, textAlign: 'center' }}>
            <Spin />
          </div>
        ) : !current ? (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="问题不存在或已删除" />
        ) : (
          <div>
            <Space size={8} wrap style={{ marginBottom: 8 }}>
              <Tag color={ISSUE_CATEGORY_META[current.category]?.color ?? 'default'}>
                {ISSUE_CATEGORY_META[current.category]?.label ?? current.category}
              </Tag>
              <Tag color={current.status === 'open' ? 'green' : 'default'}>
                {current.status === 'open' ? '待处理' : '已关闭'}
              </Tag>
              <Text type="secondary">
                所属文档：
                <Button
                  type="link"
                  size="small"
                  style={{ padding: 0, height: 'auto' }}
                  onClick={() => navigate(`/w/${wid}/documents/${current.document_id}`)}
                >
                  {current.document_title ?? `#${current.document_id}`}
                </Button>
              </Text>
            </Space>
            <Title level={5} style={{ marginTop: 0 }}>
              {current.title}
            </Title>
            {current.description && (
              <Paragraph type="secondary" style={{ whiteSpace: 'pre-wrap' }}>
                {current.description}
              </Paragraph>
            )}
            <Text type="secondary" style={{ fontSize: 12 }}>
              创建于 {formatDateTime(current.created_at)}
            </Text>

            <Space size={8} style={{ margin: '12px 0' }}>
              {current.status === 'open' ? (
                <Button
                  size="small"
                  icon={<CheckCircleOutlined />}
                  disabled={!canManageCurrent}
                  loading={closeIssue.isPending}
                  data-testid="doc-issue-close"
                  onClick={() => closeIssue.mutate()}
                >
                  关闭问题
                </Button>
              ) : (
                <Button
                  size="small"
                  icon={<RedoOutlined />}
                  disabled={!canManageCurrent}
                  loading={reopenIssue.isPending}
                  data-testid="doc-issue-reopen"
                  onClick={() => reopenIssue.mutate()}
                >
                  重开问题
                </Button>
              )}
            </Space>

            <Title level={5}>评论（{current.comments.length}）</Title>
            {current.comments.length === 0 ? (
              <Text type="secondary">暂无评论</Text>
            ) : (
              current.comments.map(c => (
                <div key={c.id} style={{ padding: '6px 0', borderBottom: '1px solid var(--cn-border-soft)' }}>
                  <Text>{c.content}</Text>
                  <div>
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      {formatDateTime(c.created_at)}
                    </Text>
                  </div>
                </div>
              ))
            )}
            <Input.TextArea
              rows={3}
              style={{ marginTop: 8 }}
              value={commentDraft}
              onChange={e => setCommentDraft(e.target.value)}
              placeholder="写下评论…"
              maxLength={2000}
            />
            <Button
              type="primary"
              style={{ marginTop: 8 }}
              disabled={!commentDraft.trim()}
              loading={addComment.isPending}
              onClick={() => addComment.mutate(commentDraft.trim())}
            >
              发表评论
            </Button>

            <Title level={5} style={{ marginTop: 20 }}>
              动态
            </Title>
            {current.events.map(e => (
              <div key={e.id} style={{ padding: '2px 0' }}>
                <Text type="secondary" style={{ fontSize: 12 }}>
                  <UndoOutlined style={{ marginRight: 4 }} />
                  {EVENT_TEXT[e.action] ?? e.action} · {formatDateTime(e.created_at)}
                </Text>
              </div>
            ))}
          </div>
        )}
      </Drawer>
    </div>
  )
}
