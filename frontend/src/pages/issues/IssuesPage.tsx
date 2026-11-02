/** 问题清单列表页 — open/closed/all 筛选 + 类别标签 + 评论数 + 新建问题.
 *
 * 数据源 issuesApi.list（status 查询参数，服务端过滤）；
 * 新建成功后跳转详情页。queryKey 约定：['issues', wid, tid, status]。
 */

import { useState } from 'react'
import {
  App as AntApp, Button, Empty, Form, Input, Listy, Modal, Segmented, Select, Space, Spin, Tag, Typography,
} from 'antd'
import { MessageOutlined, PlusOutlined } from '@ant-design/icons'
import CnListMeta from '@/components/CnListMeta'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate, useParams } from 'react-router-dom'
import { formatDateTime } from '@/utils/datetime'
import { issuesApi, tableApi } from '@/api'
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
  { label: '待处理', value: 'open' },
  { label: '已关闭', value: 'closed' },
  { label: '全部', value: 'all' },
]

export default function IssuesPage() {
  const { wid = '', tid = '' } = useParams<{ wid: string; tid?: string }>()
  // 无 :tid = 工作区级（数据表模块「问题清单」页签）；有 :tid = 单表视图
  const workspaceMode = !tid
  const navigate = useNavigate()
  const { message } = AntApp.useApp()
  const queryClient = useQueryClient()
  const [status, setStatus] = useState<StatusFilter>('open')
  const [createOpen, setCreateOpen] = useState(false)
  const [form] = Form.useForm<{ table_id?: number; title: string; description?: string; category?: IssueCategory }>()

  const { data, isLoading } = useQuery({
    queryKey: workspaceMode ? ['issues', wid, 'workspace', status] : ['issues', wid, tid, status],
    queryFn: () => (workspaceMode ? issuesApi.listWorkspace(wid, status) : issuesApi.list(wid, tid, status)),
    enabled: !!wid && (workspaceMode || !!tid),
  })

  // 工作区级新建问题需要先选目标表
  const { data: tableList = [] } = useQuery({
    queryKey: ['tables', wid],
    queryFn: () => tableApi.list(wid),
    enabled: !!wid && workspaceMode && createOpen,
  })
  const tableOptions = tableList.map(table => ({ value: Number(table.id), label: table.name }))

  const create = useMutation({
    mutationFn: (v: { table_id?: number; title: string; description?: string; category?: IssueCategory }) => {
      const targetTid = workspaceMode ? Number(v.table_id) : Number(tid)
      return issuesApi.create(wid, targetTid, { title: v.title, description: v.description, category: v.category })
    },
    onSuccess: (detail) => {
      message.success('问题已提交')
      queryClient.invalidateQueries({ queryKey: ['issues', wid] })
      setCreateOpen(false)
      form.resetFields()
      navigate(`/w/${wid}/tables/${detail.table_id}/issues/${detail.id}`)
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
          // antd List 弃用（ADR 0074）：Listy + 自绘 Meta / 操作区
          <Listy
            className="cn-listy-plain"
            items={data?.items ?? []}
            rowKey={item => item.id}
            itemRender={(item: IssueListItem) => (
              <div
                className="cn-list-item"
                style={{ cursor: 'pointer' }}
                onClick={() => navigate(`/w/${wid}/tables/${item.table_id}/issues/${item.id}`)}
              >
                <div className="cn-list-item-main">
                  <CnListMeta
                    title={
                      <Space size={8} wrap>
                        <Tag color={ISSUE_CATEGORY_META[item.category]?.color ?? 'default'} style={{ marginInlineEnd: 0 }}>
                          {ISSUE_CATEGORY_META[item.category]?.label ?? item.category}
                        </Tag>
                        {workspaceMode && item.table_name && (
                          <Tag color="blue" style={{ marginInlineEnd: 0 }}>表：{item.table_name}</Tag>
                        )}
                        {status === 'all' && item.status === 'closed' && <Tag style={{ marginInlineEnd: 0 }}>已关闭</Tag>}
                        <Text strong>{item.title}</Text>
                      </Space>
                    }
                    description={<Text type="secondary">#{item.id} · 创建于 {formatDateTime(item.created_at)}</Text>}
                  />
                </div>
                <div className="cn-list-item-actions">
                  <span aria-label={`评论数 ${item.comment_count}`}>
                    <MessageOutlined style={{ marginRight: 4, color: 'var(--cn-text-secondary)' }} />
                    {item.comment_count}
                  </span>
                </div>
              </div>
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
          {workspaceMode && (
            <Form.Item
              name="table_id"
              label="目标数据表"
              rules={[{ required: true, message: '请选择目标数据表' }]}
            >
              <Select
                options={tableOptions}
                showSearch
                optionFilterProp="label"
                placeholder="问题提交到哪张表"
              />
            </Form.Item>
          )}
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
