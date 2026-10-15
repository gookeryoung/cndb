/**
 * 文档修改申请卡片：状态 / 基准信息 + 展开查看内容 DIFF + 审核操作.
 *
 * 抽屉（单文档视角）与工作区级修改申请列表共用；`showDocument` 为 true 时
 * 额外展示所属文档并提供跳转（工作区级列表需要跨文档导航）。
 */

import { useState } from 'react'
import { Alert, App as AntApp, Button, Popconfirm, Space, Spin, Tag, Typography } from 'antd'
import { CheckOutlined, CloseOutlined, DeleteOutlined, FileTextOutlined, SyncOutlined } from '@ant-design/icons'
import { useMutation, useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'

import type { WorkspaceRole } from '@/api'
import { documentsApi } from '@/api/documents'
import type { DocumentChangeRequestItem } from '@/api/documents'
import { DocumentDiffView } from '@/components/DiffView'
import { useAuthStore } from '@/store'
import { formatDateTime } from '@/utils/datetime'

const { Text } = Typography

export const CR_STATUS_META: Record<string, { label: string; color: string }> = {
  open: { label: '待审核', color: 'green' },
  merged: { label: '已通过', color: 'purple' },
  closed: { label: '已关闭', color: 'default' },
}

interface ChangeRequestCardProps {
  cr: DocumentChangeRequestItem
  workspaceId: number
  /** 当前用户在工作区的角色（决定审核入口） */
  role: WorkspaceRole | null
  /** 操作成功后回调（通常用于失效相关查询） */
  onChanged: () => void
  /** 工作区级列表：展示所属文档并可跳转 */
  showDocument?: boolean
}

export default function ChangeRequestCard({ cr, workspaceId, role, onChanged, showDocument }: ChangeRequestCardProps) {
  const { message } = AntApp.useApp()
  const navigate = useNavigate()
  const user = useAuthStore(s => s.user)
  const [expanded, setExpanded] = useState(false)

  const canReview = role === 'owner' || role === 'editor'
  const isSubmitter = !!user && cr.submitted_by_id != null && String(cr.submitted_by_id) === String(user.id)
  const isOpen = cr.status === 'open'

  const detail = useQuery({
    queryKey: ['document-change-request', workspaceId, cr.id],
    queryFn: () => documentsApi.changeRequest(workspaceId, cr.id),
    enabled: expanded,
  })

  const mergeMut = useMutation({
    mutationFn: () => documentsApi.mergeChangeRequest(workspaceId, cr.id),
    onSuccess: (res) => {
      message.success(`已通过并生成 v${res.version_number}`)
      onChanged()
    },
    onError: (err: unknown) => message.error(err instanceof Error ? err.message : '通过失败'),
  })

  const closeMut = useMutation({
    mutationFn: () => documentsApi.closeChangeRequest(workspaceId, cr.id),
    onSuccess: () => {
      message.success('已驳回')
      onChanged()
    },
    onError: (err: unknown) => message.error(err instanceof Error ? err.message : '驳回失败'),
  })

  const baseMut = useMutation({
    mutationFn: () => documentsApi.updateChangeRequestBase(workspaceId, cr.id),
    onSuccess: (updated) => {
      message.success(`基准已刷新至 v${updated.base_version_number}`)
      onChanged()
    },
    onError: (err: unknown) => message.error(err instanceof Error ? err.message : '刷新基准失败'),
  })

  const deleteMut = useMutation({
    mutationFn: () => documentsApi.deleteChangeRequest(workspaceId, cr.id),
    onSuccess: () => {
      message.success('草稿已删除')
      onChanged()
    },
    onError: (err: unknown) => message.error(err instanceof Error ? err.message : '删除失败'),
  })

  const busy = mergeMut.isPending || closeMut.isPending || baseMut.isPending || deleteMut.isPending

  return (
    <div className="cn-dcr-card" data-testid={`dcr-card-${cr.id}`}>
      <div className="cn-dcr-head">
        <Space size={6} wrap>
          <Tag color={CR_STATUS_META[cr.status]?.color ?? 'default'}>
            {CR_STATUS_META[cr.status]?.label ?? cr.status}
          </Tag>
          {cr.stale && isOpen && <Tag color="warning">基准已过期</Tag>}
          <Text strong>#{cr.id}</Text>
          <Text>{cr.title}</Text>
        </Space>
        {showDocument && (
          <Text type="secondary" className="cn-dcr-doc">
            <FileTextOutlined style={{ marginRight: 4 }} />
            <Button
              type="link"
              size="small"
              style={{ padding: 0, height: 'auto' }}
              onClick={() => navigate(`/w/${workspaceId}/documents/${cr.document_id}`)}
            >
              {cr.document_title ?? `文档 #${cr.document_id}`}
            </Button>
          </Text>
        )}
        <Text type="secondary" className="cn-dcr-meta">
          基准 v{cr.base_version_number} · 当前 v{cr.current_version_number} · {formatDateTime(cr.created_at)} · 提案{' '}
          {cr.proposed_size} B
        </Text>
        {cr.description && <div className="cn-dcr-desc">{cr.description}</div>}
        {cr.review_comment && (
          <Alert
            type={cr.status === 'merged' ? 'success' : 'info'}
            showIcon
            message={`审核意见：${cr.review_comment}`}
            style={{ marginTop: 6 }}
          />
        )}
      </div>

      <Space size={6} wrap className="cn-dcr-actions">
        <Button size="small" onClick={() => setExpanded(v => !v)} data-testid={`dcr-toggle-${cr.id}`}>
          {expanded ? '收起差异' : '查看差异'}
        </Button>
        {isOpen && canReview && (
          <>
            <Button
              size="small"
              type="primary"
              icon={<CheckOutlined />}
              loading={mergeMut.isPending}
              disabled={busy}
              data-testid={`dcr-merge-${cr.id}`}
              onClick={() => mergeMut.mutate()}
            >
              通过
            </Button>
            <Button
              size="small"
              icon={<CloseOutlined />}
              loading={closeMut.isPending}
              disabled={busy}
              data-testid={`dcr-close-${cr.id}`}
              onClick={() => closeMut.mutate()}
            >
              驳回
            </Button>
          </>
        )}
        {isOpen && isSubmitter && cr.stale && (
          <Button
            size="small"
            icon={<SyncOutlined />}
            loading={baseMut.isPending}
            disabled={busy}
            data-testid={`dcr-rebase-${cr.id}`}
            onClick={() => baseMut.mutate()}
          >
            刷新基准
          </Button>
        )}
        {isOpen && (isSubmitter || role === 'owner') && (
          <Popconfirm
            title="删除该修改申请？"
            description="草稿删除后不可恢复，文档正文不受影响。"
            okText="删除"
            cancelText="取消"
            onConfirm={() => deleteMut.mutate()}
          >
            <Button
              size="small"
              danger
              icon={<DeleteOutlined />}
              loading={deleteMut.isPending}
              disabled={busy}
              data-testid={`dcr-delete-${cr.id}`}
            >
              删除草稿
            </Button>
          </Popconfirm>
        )}
      </Space>

      {expanded && (
        <div className="cn-dcr-diff" data-testid={`dcr-diff-${cr.id}`}>
          {detail.isLoading ? (
            <div style={{ padding: 12, textAlign: 'center' }}>
              <Spin size="small" />
            </div>
          ) : detail.isError || !detail.data ? (
            <Alert type="error" showIcon message="差异加载失败" />
          ) : (
            <DocumentDiffView
              diff={detail.data.diff?.diff ?? ''}
              baseLabel={`v${detail.data.base_version_number}`}
              headLabel="提案"
            />
          )}
        </div>
      )}
    </div>
  )
}
