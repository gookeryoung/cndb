/** 事件流页面 —— 统一事件/审计流（/api/v1/admin/events）.
 *
 * 展示跨插件的统一事件（登录、用户管理、记录变更等），支持动作/关键词/时间筛选与分页；
 * 与「用户管理 → 操作日志」互补：后者是域内明细，这里是全局串联视图（可按 request_id 追一次请求）。
 */

import { useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Input, Select, Table, Tag, Typography, Button } from 'antd'
import { ReloadOutlined, InfoCircleOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { adminApi } from '@/api'
import { useResponsive } from '@/hooks/useResponsive'
import type { CoreEventActionStat, CoreEventItem } from '@/api'

const { Text } = Typography

/** 动作 → 标签颜色（前缀匹配，未知动作用默认色） */
const ACTION_COLORS: Array<[string, string]> = [
  ['auth.login_failed', 'red'],
  ['auth.token_reuse_detected', 'red'],
  ['auth.password_changed', 'orange'],
  ['auth.logout', 'default'],
  ['auth.', 'blue'],
  ['user.', 'purple'],
  ['record.', 'cyan'],
  ['document.', 'green'],
]

function actionColor(action: string): string {
  const hit = ACTION_COLORS.find(([prefix]) => action === prefix || action.startsWith(prefix))
  return hit ? hit[1] : 'default'
}

function formatTime(value: string): string {
  const d = new Date(value)
  return Number.isNaN(d.getTime()) ? value : d.toLocaleString('zh-CN', { hour12: false })
}

export default function EventsPage() {
  // 筛选条件写入 URL（?action=&keyword=）：可分享、刷新保持，也便于测试与深链
  const [searchParams, setSearchParams] = useSearchParams()
  const appliedAction = searchParams.get('action') ?? undefined
  const appliedKeyword = searchParams.get('keyword') ?? ''
  const [keywordDraft, setKeywordDraft] = useState(appliedKeyword)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const { isMobile } = useResponsive()

  /** 更新 URL 中的筛选条件（去掉空值）并回到第一页 */
  const applyFilters = (next: { action?: string; keyword?: string }) => {
    setSearchParams((prev) => {
      const params = new URLSearchParams(prev)
      for (const [key, value] of Object.entries(next)) {
        if (value) params.set(key, value)
        else params.delete(key)
      }
      return params
    })
    setPage(1)
  }

  // URL 里的关键词变化时同步输入框（深链/前进后退）
  const appliedKeywordRef = useRef(appliedKeyword)
  if (appliedKeywordRef.current !== appliedKeyword) {
    appliedKeywordRef.current = appliedKeyword
    if (keywordDraft !== appliedKeyword) setKeywordDraft(appliedKeyword)
  }

  const actionsQuery = useQuery({
    queryKey: ['admin-event-actions'],
    queryFn: () => adminApi.listEventActions(),
    staleTime: 60_000,
  })

  const eventsQuery = useQuery({
    queryKey: ['admin-events', appliedAction, appliedKeyword, page, pageSize],
    queryFn: () =>
      adminApi.listEvents({
        action: appliedAction,
        keyword: appliedKeyword || undefined,
        page,
        page_size: pageSize,
      }),
    staleTime: 10_000,
  })

  const columns = [
    { title: '时间', dataIndex: 'created_at', width: 170, render: (v: string) => formatTime(v) },
    {
      title: '动作',
      dataIndex: 'action',
      width: 200,
      render: (v: string) => <Tag color={actionColor(v)}>{v}</Tag>,
    },
    { title: '操作人', dataIndex: 'actor_name', width: 120, render: (v: string | null) => v ?? '—' },
    { title: '摘要', dataIndex: 'summary', ellipsis: true },
    {
      title: '目标',
      dataIndex: 'target_type',
      width: 150,
      render: (_: unknown, row: CoreEventItem) => (
        <Text type="secondary">
          {row.target_type}
          {row.target_id ? `#${row.target_id}` : ''}
        </Text>
      ),
    },
    {
      title: 'request_id',
      dataIndex: 'request_id',
      width: 130,
      render: (v: string | null) =>
        v ? (
          <Text code style={{ fontSize: 12 }} title={v}>
            {v.slice(0, 8)}
          </Text>
        ) : (
          '—'
        ),
    },
  ]

  return (
    <div className="cn-admin-section" data-testid="events-page">
      <div className="cn-toolbar">
        <Select
          data-testid="event-action-filter"
          allowClear
          placeholder="按动作筛选"
          style={{ width: isMobile ? '100%' : 220 }}
          value={appliedAction}
          onChange={(v) => applyFilters({ action: v })}
          options={(actionsQuery.data ?? []).map((it: CoreEventActionStat) => ({
            value: it.action,
            label: `${it.action}（${it.count}）`,
          }))}
        />
        <Input.Search
          data-testid="event-keyword"
          allowClear
          placeholder="摘要 / 操作人关键词"
          style={{ width: isMobile ? '100%' : 240 }}
          value={keywordDraft}
          onChange={(e) => setKeywordDraft(e.target.value)}
          onSearch={(v) => applyFilters({ keyword: v })}
        />
        <div className="cn-toolbar-end">
          <span className="cn-record-pill">{eventsQuery.data?.total ?? 0} 条事件</span>
          <Button
            icon={<ReloadOutlined />}
            onClick={() => {
              void actionsQuery.refetch()
              void eventsQuery.refetch()
            }}
          >
            刷新
          </Button>
        </div>
      </div>

      <div className="cn-grid-card">
        <Table<CoreEventItem>
          className="cn-table-list"
          rowKey="id"
          size="small"
          data-testid="events-table"
          loading={eventsQuery.isLoading}
          dataSource={eventsQuery.data?.items ?? []}
          columns={columns}
          scroll={{ x: 'max-content' }}
          pagination={{
            current: page,
            pageSize,
            total: eventsQuery.data?.total ?? 0,
            showSizeChanger: true,
            onChange: (p, ps) => {
              setPage(p)
              setPageSize(ps)
            },
          }}
          locale={{ emptyText: '暂无事件' }}
        />
      </div>

      <div className="cn-hint">
        <InfoCircleOutlined />
        <div>
          统一事件流汇总各插件的关键动作（登录 / 用户管理 / 记录变更等）。域内明细仍在各处原始日志中；
          同一 <Text code>request_id</Text> 可在访问日志与慢查询日志中继续追踪。
        </div>
      </div>
    </div>
  )
}
