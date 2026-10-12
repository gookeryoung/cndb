/** 修改申请列表页 — scope 筛选（开放/全部/我的）+ 状态/stale/冲突标记.
 *
 * 数据源 changeRequestsApi.list（scope 查询参数，服务端过滤）；
 * 后端 scope 语义：open=在途、all=全部（含 merged/closed，列表页补状态 Tag）、mine=我提交的。
 * queryKey 约定：['change-requests', wid, tid, scope]。
 */

import { useState } from 'react'
import {
  App as AntApp, Button, Empty, List, Segmented, Space, Spin, Tag, Typography,
} from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { useNavigate, useParams } from 'react-router-dom'
import dayjs from 'dayjs'
import { changeRequestsApi } from '@/api'
import type { ChangeRequest } from '@/api'
import { memberDisplayName, useMemberNameMap } from '@/hooks/useMemberNames'

const { Text } = Typography

type Scope = 'open' | 'all' | 'mine'

const SCOPE_OPTIONS: Array<{ label: string; value: Scope }> = [
  { label: '开放', value: 'open' },
  { label: '全部', value: 'all' },
  { label: '我的', value: 'mine' },
]

const STATUS_META: Record<ChangeRequest['status'], { label: string; color: string }> = {
  open: { label: '开放', color: 'green' },
  merged: { label: '已合并', color: 'purple' },
  closed: { label: '已关闭', color: 'default' },
}

function formatTime(value?: string): string {
  return value ? dayjs(value).format('YYYY-MM-DD HH:mm') : ''
}

export default function ChangeRequestsPage() {
  const { wid = '', tid = '' } = useParams<{ wid: string; tid: string }>()
  const navigate = useNavigate()
  const { message } = AntApp.useApp()
  const [scope, setScope] = useState<Scope>('open')
  const nameById = useMemberNameMap(wid)

  const { data, isLoading } = useQuery({
    queryKey: ['change-requests', wid, tid, scope],
    queryFn: () => changeRequestsApi.list(wid, tid, scope),
    enabled: !!wid && !!tid,
  })

  const openNewDialog = () => {
    // 新建修改申请入口：写路径（单元格/行详情/批量删除）已按双轨自动生成申请，
    // 手动多行申请对话框将在后续迭代补充；当前引导用户直接在网格中编辑触发
    message.info('请直接在表格中编辑数据，系统会自动生成修改申请')
  }

  return (
    <div style={{ padding: '16px 24px', maxWidth: 860, margin: '0 auto' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <Segmented options={SCOPE_OPTIONS} value={scope} onChange={(v) => setScope(v as Scope)} />
        <Button type="primary" icon={<PlusOutlined />} onClick={openNewDialog}>新建修改申请</Button>
      </div>

      <Spin spinning={isLoading}>
        {data && data.items.length === 0 ? (
          <Empty description="暂无修改申请" style={{ padding: 48 }} />
        ) : (
          <List
            dataSource={data?.items ?? []}
            renderItem={(item: ChangeRequest) => (
              <List.Item
                style={{ cursor: 'pointer' }}
                onClick={() => navigate(`/w/${wid}/tables/${tid}/change-requests/${item.id}`)}
              >
                <List.Item.Meta
                  title={
                    <Space size={8} wrap>
                      {(scope !== 'open') && (
                        <Tag color={STATUS_META[item.status].color} style={{ marginInlineEnd: 0 }}>
                          {STATUS_META[item.status].label}
                        </Tag>
                      )}
                      <Text strong>{item.title}</Text>
                      {item.stale && <Tag color="warning" style={{ marginInlineEnd: 0 }}>基准已过期</Tag>}
                      {(item.conflicts_count ?? 0) > 0 && (
                        <Tag color="orange" style={{ marginInlineEnd: 0 }}>与 {item.conflicts_count} 行在途申请冲突</Tag>
                      )}
                    </Space>
                  }
                  description={
                    <Text type="secondary">
                      #{item.id} · {memberDisplayName(nameById, item.submitted_by_id, '未知')} 提交于 {formatTime(item.created_at)}
                    </Text>
                  }
                />
              </List.Item>
            )}
          />
        )}
      </Spin>
    </div>
  )
}
