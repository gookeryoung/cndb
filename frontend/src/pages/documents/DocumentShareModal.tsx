/** 文档分享弹层（ADR 0017）：创建 / 复制匿名只读链接、查看访问次数、撤销.
 *
 * 仅 owner / editor 打开（入口处按角色门控；后端 require_editor 再兜底）。
 * 本轮不提供密码 / 有效期入口，但会如实展示历史分享的状态。
 */

import { Alert, Button, Empty, List, Modal, Popconfirm, Space, Tag, Typography } from 'antd'
import { CopyOutlined, DeleteOutlined, LinkOutlined, PlusOutlined } from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { App } from 'antd'

import { documentsApi, type ShareItem } from '@/api/documents'

interface DocumentShareModalProps {
  open: boolean
  onClose: () => void
  workspaceId: number
  docId: number
  /** 文档状态：仅 published 可创建新分享 */
  docStatus: string
}

/** 分享链接（游客视角，免登录） */
export function shareLink(token: string): string {
  return `${window.location.origin}/public/share/${token}`
}

function formatTime(value?: string | null): string {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '—' : date.toLocaleString()
}

export default function DocumentShareModal({ open, onClose, workspaceId, docId, docStatus }: DocumentShareModalProps) {
  const { message } = App.useApp()
  const qc = useQueryClient()
  const queryKey = ['document-shares', workspaceId, docId]

  const sharesQuery = useQuery({
    queryKey,
    queryFn: () => documentsApi.shares(workspaceId, docId),
    enabled: open,
  })

  const createMut = useMutation({
    mutationFn: () => documentsApi.createShare(workspaceId, docId, { permission: 'viewer' }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey })
      message.success('分享链接已创建')
    },
    onError: (err: Error) => message.error(err.message || '创建分享链接失败'),
  })

  const revokeMut = useMutation({
    mutationFn: (shareId: number) => documentsApi.revokeShare(workspaceId, docId, shareId),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey })
      message.success('分享链接已撤销')
    },
    onError: (err: Error) => message.error(err.message || '撤销分享链接失败'),
  })

  const copy = async (share: ShareItem) => {
    try {
      await navigator.clipboard.writeText(shareLink(share.token))
      message.success('链接已复制')
    } catch {
      message.error('复制失败，请手动选择链接')
    }
  }

  const shares = sharesQuery.data ?? []
  const canCreate = docStatus === 'published'

  return (
    <Modal
      open={open}
      onCancel={onClose}
      footer={null}
      width={640}
      title={
        <Space>
          <LinkOutlined />
          分享文档
        </Space>
      }
      data-testid="document-share-modal"
    >
      <Typography.Paragraph type="secondary" style={{ marginTop: 0 }}>
        获得链接的人无需登录即可只读浏览这篇文档；撤销后链接立即失效。
      </Typography.Paragraph>
      {!canCreate && (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 12 }}
          title="仅已发布文档可创建分享链接；请先发布该文档"
          data-testid="document-share-unpublished"
        />
      )}
      <Space style={{ marginBottom: 12 }}>
        <Button
          type="primary"
          icon={<PlusOutlined />}
          loading={createMut.isPending}
          disabled={!canCreate}
          data-testid="document-share-create"
          onClick={() => createMut.mutate()}
        >
          创建链接
        </Button>
      </Space>

      {sharesQuery.isLoading ? (
        <Typography.Text type="secondary">加载中…</Typography.Text>
      ) : shares.length === 0 ? (
        <Empty description="还没有分享链接" image={Empty.PRESENTED_IMAGE_SIMPLE} />
      ) : (
        <List
          data-testid="document-share-list"
          size="small"
          dataSource={shares}
          renderItem={share => (
            <List.Item
              data-testid={`document-share-item-${share.id}`}
              actions={[
                <Button
                  key="copy"
                  type="link"
                  size="small"
                  icon={<CopyOutlined />}
                  disabled={!share.is_active}
                  onClick={() => void copy(share)}
                >
                  复制链接
                </Button>,
                <Popconfirm
                  key="revoke"
                  title="撤销后该链接立即失效，确定撤销？"
                  okText="撤销"
                  cancelText="取消"
                  disabled={!share.is_active}
                  onConfirm={() => revokeMut.mutate(share.id)}
                >
                  <Button
                    type="link"
                    size="small"
                    danger
                    icon={<DeleteOutlined />}
                    disabled={!share.is_active}
                  >
                    撤销
                  </Button>
                </Popconfirm>,
              ]}
            >
              <List.Item.Meta
                title={
                  <Space size={8}>
                    <Tag color={share.is_active ? 'green' : 'default'}>{share.is_active ? '有效' : '已撤销'}</Tag>
                    <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                      创建于 {formatTime(share.created_at)}
                    </Typography.Text>
                    {share.has_password && <Tag>需密码</Tag>}
                  </Space>
                }
                description={
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    访问 {share.view_count} 次
                  </Typography.Text>
                }
              />
            </List.Item>
          )}
        />
      )}
    </Modal>
  )
}
