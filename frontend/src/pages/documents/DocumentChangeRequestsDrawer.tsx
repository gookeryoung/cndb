/**
 * 文档修改申请抽屉：单文档视角的待审列表 + 内容 DIFF 审核.
 *
 * 自持列表查询；卡片与操作复用 {@link ./ChangeRequestCard}（与工作区级列表页共用）。
 * 合并生效后只失效申请与版本文档相关缓存，不触碰编辑器正文缓存，
 * 避免审核者误丢自己未保存的编辑内容。
 */

import { Drawer, Empty, Spin } from 'antd'
import { useQuery, useQueryClient } from '@tanstack/react-query'

import type { WorkspaceRole } from '@/api'
import { documentsApi } from '@/api/documents'
import ChangeRequestCard from './ChangeRequestCard'

interface DrawerProps {
  open: boolean
  onClose: () => void
  workspaceId: number
  documentId: number
  /** 当前用户在工作区的角色（决定审核入口） */
  role: WorkspaceRole | null
}

export default function DocumentChangeRequestsDrawer({ open, onClose, workspaceId, documentId, role }: DrawerProps) {
  const qc = useQueryClient()

  const listKey = ['document-change-requests', workspaceId, documentId, 'all'] as const
  const { data, isLoading } = useQuery({
    queryKey: listKey,
    queryFn: () => documentsApi.changeRequests(workspaceId, { document_id: documentId, scope: 'all' }),
    enabled: open && Number.isFinite(documentId),
  })

  const invalidate = () => {
    void qc.invalidateQueries({ queryKey: ['document-change-requests', workspaceId, documentId] })
    void qc.invalidateQueries({ queryKey: ['document-change-request', workspaceId] })
    // 版本抽屉需要看到合并产生的新版本；不触碰编辑器正文缓存，避免覆盖未保存编辑
    void qc.invalidateQueries({ queryKey: ['documents', workspaceId, documentId, 'versions'] })
  }

  const items = data?.items ?? []
  const openCount = items.filter(i => i.status === 'open').length

  return (
    <Drawer
      title={`修改申请${openCount > 0 ? `（待审核 ${openCount}）` : ''}`}
      size={860}
      open={open}
      onClose={onClose}
      data-testid="dcr-drawer"
    >
      {isLoading ? (
        <div style={{ padding: 24, textAlign: 'center' }}>
          <Spin />
        </div>
      ) : items.length === 0 ? (
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description="暂无修改申请：查看者保存正文时自动生成，或由成员手动发起"
        />
      ) : (
        <div className="cn-dcr-list">
          {items.map(item => (
            <ChangeRequestCard key={item.id} cr={item} workspaceId={workspaceId} role={role} onChanged={invalidate} />
          ))}
        </div>
      )}
    </Drawer>
  )
}
