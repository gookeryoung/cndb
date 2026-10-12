/** 问题清单列表页 — open/closed/all 筛选 + 类别标签 + 评论数 + 新建问题.
 *
 * 数据源 issuesApi.list（status 查询参数，服务端过滤）；
 * 新建成功后跳转详情页。queryKey 约定：['issues', wid, tid, status]。
 */

import { useState } from 'react'
import {
  App as AntApp, Button, Empty, Form, Input, List, Modal, Segmented, Select, Space, Spin, Tag, Typography,
} from 'antd'
import { MessageOutlined, PlusOutlined } from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate, useParams } from 'react-router-dom'
import dayjs from 'dayjs'
import { issuesApi } from '@/api'
import type { IssueCategory, IssueListItem } from '@/api'

const { Text } = Typography

/** 类别 → 中文标签与颜色（GitHub label 风格，列表/详情共用） */
export const ISSUE_CATEGORY_META: Record<IssueCategory, { label: string; color: string }> = {
  data_error: { label: '数据异常', color: 'red' },
  suggestion: { label: '建议', color: 'orange' },
  question: { label: '疑问', color: 'blue' },
  other: { label: '其他', color: 'default' },
}

type StatusFilter = 'open' | 'closed' | 'all'

const STATUS_FILTER_OPTIONS: Array<{ label: string; value: StatusFilter }> = [
  { label: '开放', value: 'open' },
  { label: '已关闭', value: 'closed' },
  { label: '全部', value: 'all' },
]

function formatTime(value?: string): string {
  return value ? dayjs(value).format('YYYY-MM-DD HH:mm') : ''
}

export default function IssuesPage() {
  const { wid = '', tid = '' } = useParams<{ wid: string; tid: string }>()
  const navigate = useNavigate()
  const { message } = AntApp.useApp()
  const queryClient = useQueryClient()
  const [status, setStatus] = useState<StatusFilter>('open')
  const [createOpen, setCreateOpen] = useState(false)
  const [form] = Form.useForm<{ title: string; description?: string; category?: IssueCategory }>()

  const { data, isLoading } = useQuery({
    queryKey: ['issues', wid, tid, status],
    queryFn: () => issuesApi.list(wid, tid, status),
    enabled: !!wid && !!tid,
  })

  const create = useMutation({
    mutationFn: (v: { title: string; description?: string; category?: IssueCategory }) =>
      issuesApi.create(wid, tid, v),
    onSuccess: (detail) => {
      message.success('问题已提交')
      queryClient.invalidateQueries({ queryKey: ['issues', wid, tid] })
      setCreateOpen(false)
      form.resetFields()
      navigate(`/w/${wid}/tables/${tid}/issues/${detail.id}`)
    },
    onError: (err) => message.error(err instanceof Error ? err.message : '提交问题失败'),
  })

  const handleCreateOpen = () => {
    form.resetFields()
    setCreateOpen(true)
  }

  const handleCreateSubmit = () => {
    form.validateFields().then((v) => create.mutate(v)).catch(() => { /* 校验失败由表单展示错误 */ })
  }

  return (
    <div style={{ padding: '16px 24px', maxWidth: 860, margin: '0 auto' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <Segmented options={STATUS_FILTER_OPTIONS} value={status} onChange={(v) => setStatus(v as StatusFilter)} />
        <Button type="primary" icon={<PlusOutlined />} onClick={handleCreateOpen}>新建问题</Button>
      </div>

      <Spin spinning={isLoading}>
        {data && data.items.length === 0 ? (
          <Empty description="暂无问题" style={{ padding: 48 }} />
        ) : (
          <List
            dataSource={data?.items ?? []}
            renderItem={(item: IssueListItem) => (
              <List.Item
                style={{ cursor: 'pointer' }}
                onClick={() => navigate(`/w/${wid}/tables/${tid}/issues/${item.id}`)}
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
                  description={<Text type="secondary">#{item.id} · 创建于 {formatTime(item.created_at)}</Text>}
                />
              </List.Item>
            )}
          />
        )}
      </Spin>

      <Modal
        title="新建问题"
        open={createOpen}
        onCancel={() => setCreateOpen(false)}
        onOk={handleCreateSubmit}
        okText="提交"
        okButtonProps={{ loading: create.isPending }}
        destroyOnHidden
      >
        <Form form={form} layout="vertical" initialValues={{ category: 'other' }}>
          <Form.Item
            name="title"
            label="标题"
            rules={[{ required: true, message: '请输入标题' }, { max: 255, message: '标题最长 255 字' }]}
          >
            <Input placeholder="一句话描述问题" maxLength={255} showCount />
          </Form.Item>
          <Form.Item name="category" label="类别">
            <Select
              options={(Object.keys(ISSUE_CATEGORY_META) as IssueCategory[]).map((c) => ({
                value: c, label: ISSUE_CATEGORY_META[c].label,
              }))}
            />
          </Form.Item>
          <Form.Item name="description" label="描述（可选）">
            <Input.TextArea rows={4} maxLength={2000} showCount placeholder="补充复现步骤、期望结果等" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
