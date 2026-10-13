/** 修改申请列表页 — scope 筛选（待审核/已合并/全部/我的）+ 状态/stale/冲突标记 + 写模式权限标注.
 *
 * 数据源 changeRequestsApi.list（scope 查询参数，服务端过滤）；
 * 后端 scope 语义：open=在途、merged=已合并、all=全部（含 merged/closed，列表页补状态 Tag）、mine=我提交的。
 * 响应附带 write_mode（direct/change_request/denied，与写路径双轨分派同源）：
 * 列表头部展示权限标注，新建按钮提示按模式适配，避免直编用户被"自动生成申请"文案误导。
 * queryKey 约定：['change-requests', wid, tid, scope]。
 */

import { useState } from 'react'
import {
  Alert, App as AntApp, Button, Empty, List, Segmented, Space, Spin, Tag, Typography,
} from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { useNavigate, useParams } from 'react-router-dom'
import dayjs from 'dayjs'
import { changeRequestsApi } from '@/api'
import type { ChangeRequest, TableWriteMode } from '@/api'
import { memberDisplayName, useMemberNameMap } from '@/hooks/useMemberNames'

const { Text } = Typography

type Scope = 'open' | 'merged' | 'all' | 'mine'

const SCOPE_OPTIONS: Array<{ label: string; value: Scope }> = [
  { label: '待审核', value: 'open' },
  { label: '已合并', value: 'merged' },
  { label: '全部', value: 'all' },
  { label: '我的', value: 'mine' },
]

const STATUS_META: Record<ChangeRequest['status'], { label: string; color: string }> = {
  open: { label: '待审核', color: 'green' },
  merged: { label: '已合并', color: 'purple' },
  closed: { label: '已关闭', color: 'default' },
}

/** 写模式 → 列表头部权限标注（type 直接复用 AntD Alert 语义色） */
const WRITE_MODE_BANNER: Record<TableWriteMode, { type: 'success' | 'info' | 'warning'; label: string; message: string }> = {
  direct: {
    type: 'success',
    label: '直编模式',
    message: '当前账号可直接在表格中修改数据：编辑立即生效，不会自动生成修改申请。',
  },
  change_request: {
    type: 'info',
    label: '申请模式',
    message: '在表格中编辑数据会自动生成修改申请，经审批合并后生效。',
  },
  denied: {
    type: 'warning',
    label: '只读',
    message: '当前账号对该表无编辑权限，写操作将被拒绝。',
  },
}

/** 新建修改申请按钮的引导文案（按写模式适配，消除提示与实际行为矛盾） */
function newRequestHint(writeMode: TableWriteMode): string {
  if (writeMode === 'direct') {
    return '当前账号具备直接修改权限：在表格中编辑会直接生效，不会自动生成修改申请。'
  }
  if (writeMode === 'denied') {
    return '当前账号对该表只读，无法提交数据变更。'
  }
  return '请直接在表格中编辑数据，系统会自动生成修改申请'
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

  // 旧响应无 write_mode 时按申请模式兜底（与 viewer 工况一致）
  const writeMode: TableWriteMode = data?.write_mode ?? 'change_request'
  const banner = WRITE_MODE_BANNER[writeMode]

  const openNewDialog = () => {
    // 新建修改申请入口：写路径（单元格/行详情/批量删除）已按双轨自动分派，
    // 提示按当前写模式适配 —— 直编用户明确告知"编辑直接生效、不会生成申请"
    message.info(newRequestHint(writeMode))
  }

  return (
    <div style={{ padding: '16px 24px', maxWidth: 860, margin: '0 auto' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <Segmented options={SCOPE_OPTIONS} value={scope} onChange={(v) => setScope(v as Scope)} />
        <Button type="primary" icon={<PlusOutlined />} onClick={openNewDialog}>新建修改申请</Button>
      </div>

      <Alert
        type={banner.type}
        showIcon
        style={{ marginBottom: 16 }}
        message={(
          <Space size={8} wrap>
            <Tag color={banner.type === 'success' ? 'green' : banner.type === 'warning' ? 'default' : 'blue'} style={{ marginInlineEnd: 0 }}>
              {banner.label}
            </Tag>
            <Text type="secondary">{banner.message}</Text>
          </Space>
        )}
      />

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
                        <Tag color="orange" style={{ marginInlineEnd: 0 }}>与 {item.conflicts_count} 行待审批申请冲突</Tag>
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
