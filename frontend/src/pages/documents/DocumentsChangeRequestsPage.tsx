/**
 * 文档区二级导航「修改申请」页 —— 工作区下全部文档的修改申请清单.
 *
 * 数据源 `GET /{wid}/document-change-requests?scope=`；卡片与审核操作复用
 * {@link ./ChangeRequestCard}（与编辑器内的抽屉共用同一套交互）。
 */

import { useState } from 'react'
import { Empty, Segmented, Space, Spin, Typography } from 'antd'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useParams } from 'react-router-dom'

import type { WorkspaceRole } from '@/api'
import { workspaceApi } from '@/api'
import { documentsApi } from '@/api/documents'
import ChangeRequestCard from './ChangeRequestCard'

const { Title, Text } = Typography

type Scope = 'open' | 'merged' | 'closed' | 'all'

const SCOPE_OPTIONS: Array<{ label: string; value: Scope }> = [
  { label: '待审核', value: 'open' },
  { label: '已通过', value: 'merged' },
  { label: '已关闭', value: 'closed' },
  { label: '全部', value: 'all' },
]

export default function DocumentsChangeRequestsPage() {
  const { wid = '' } = useParams<{ wid: string }>()
  const workspaceId = Number(wid)
  const qc = useQueryClient()
  const [scope, setScope] = useState<Scope>('open')

  const { data: wsDetail } = useQuery({
    queryKey: ['workspace-detail', wid],
    queryFn: () => workspaceApi.get(wid),
    enabled: !!wid,
  })
  const role = (wsDetail?.current_user_role ?? null) as WorkspaceRole | null

  const listKey = ['document-change-requests', wid, 'workspace', scope] as const
  const { data, isLoading } = useQuery({
    queryKey: listKey,
    queryFn: () => documentsApi.changeRequests(wid, { scope }),
    enabled: !!wid,
  })

  const invalidate = () => {
    void qc.invalidateQueries({ queryKey: ['document-change-requests', wid, 'workspace'] })
    void qc.invalidateQueries({ queryKey: ['document-change-request', wid] })
  }

  const items = data?.items ?? []

  return (
    <div className="cn-subpage" style={{ maxWidth: 960, margin: '0 auto' }}>
      <div className="cn-subpage-head">
        <Space size={8} align="center">
          <Title level={5} style={{ margin: 0 }}>
            文档修改申请
          </Title>
          <Text type="secondary">查看者保存正文时自动生成，通过后才会写入文档版本</Text>
        </Space>
        <Segmented options={SCOPE_OPTIONS} value={scope} onChange={v => setScope(v as Scope)} />
      </div>

      {isLoading ? (
        <div style={{ padding: 32, textAlign: 'center' }}>
          <Spin />
        </div>
      ) : items.length === 0 ? (
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description={scope === 'open' ? '暂无待审核的修改申请' : '暂无修改申请'}
          style={{ padding: 48 }}
        />
      ) : (
        <div className="cn-dcr-list" data-testid="dcr-workspace-list">
          {items.map(item => (
            <ChangeRequestCard
              key={item.id}
              cr={item}
              workspaceId={workspaceId}
              role={role}
              onChanged={invalidate}
              showDocument
            />
          ))}
        </div>
      )}
    </div>
  )
}
