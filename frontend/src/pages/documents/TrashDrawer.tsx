/** 回收站抽屉 —— 自持软删列表查询、恢复与彻底删除. */

import { useCallback } from 'react'
import { App as AntApp, Button, Drawer, Empty, List, Popconfirm, Space, Typography } from 'antd'
import { FileTextOutlined, FolderOutlined } from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { documentsApi } from '@/api/documents'
import type { TrashItem } from '@/api/documents'
import { useResponsive } from '@/hooks/useResponsive'
import { formatTime } from './documentDisplay'

const { Text } = Typography

interface TrashDrawerProps {
  open: boolean
  onClose: () => void
  /** 工作区 ID（数字形式，与页面内 workspaceId 同源） */
  wid: number
}

export default function TrashDrawer({ open, onClose, wid }: TrashDrawerProps) {
  const { message } = AntApp.useApp()
  const qc = useQueryClient()
  const { isMobile } = useResponsive()

  const invalidate = useCallback(() => {
    void qc.invalidateQueries({ queryKey: ['documents', wid] })
  }, [qc, wid])

  // 回收站：软删除文档列表（打开抽屉时拉取，按删除时间倒序）
  const trashQuery = useQuery({
    queryKey: ['documents', wid, 'trash'],
    queryFn: () => documentsApi.trash(wid, { limit: 200 }),
    enabled: Number.isFinite(wid) && open,
  })

  const restoreMut = useMutation({
    mutationFn: (docId: number) => documentsApi.restore(wid, docId),
    onSuccess: data => {
      message.success(data.reparented_to_root ? '已恢复（原父目录仍在回收站，已挂到根目录）' : '已恢复')
      invalidate()
    },
    onError: (err: unknown) => {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      message.error(detail ?? '恢复失败')
    },
  })

  const purgeMut = useMutation({
    mutationFn: (docId: number) => documentsApi.purge(wid, docId),
    onSuccess: data => {
      message.success(`已彻底删除 ${data.purged_count} 项`)
      invalidate()
    },
    onError: (err: unknown) => {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      message.error(detail ?? '彻底删除失败')
    },
  })

  return (
    <Drawer
      title="回收站"
      width={isMobile ? '100%' : 520}
      open={open}
      onClose={onClose}
      data-testid="doc-trash-drawer"
    >
          {trashQuery.isLoading ? (
            <div>加载中…</div>
          ) : (trashQuery.data?.items ?? []).length === 0 ? (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="回收站为空" />
          ) : (
            <List
              dataSource={trashQuery.data?.items ?? []}
              renderItem={(item: TrashItem) => (
                <List.Item
                  key={item.id}
                  data-testid={`doc-trash-item-${item.id}`}
                  actions={[
                    <Button
                      key="restore"
                      size="small"
                      data-testid={`doc-trash-restore-${item.id}`}
                      loading={restoreMut.isPending && restoreMut.variables === item.id}
                      onClick={() => restoreMut.mutate(item.id)}
                    >
                      恢复
                    </Button>,
                    <Popconfirm
                      key="purge"
                      title={
                        item.is_folder
                          ? '彻底删除将连同回收站中的子项与全部历史版本一并清除，且不可恢复，确认？'
                          : '彻底删除将清除全部历史版本与外存内容，且不可恢复，确认？'
                      }
                      okType="danger"
                      okText="彻底删除"
                      cancelText="取消"
                      onConfirm={() => purgeMut.mutate(item.id)}
                    >
                      <Button size="small" danger data-testid={`doc-trash-purge-${item.id}`}>
                        彻底删除
                      </Button>
                    </Popconfirm>,
                  ]}
                >
                  <List.Item.Meta
                    title={
                      <Space size={6}>
                        {item.is_folder ? <FolderOutlined /> : <FileTextOutlined />}
                        <Text strong>{item.title}</Text>
                      </Space>
                    }
                    description={
                      <Text type="secondary" style={{ fontSize: 12 }}>
                        {item.is_folder ? '文件夹' : '文档'} · 删除于{' '}
                        {item.deleted_at ? formatTime(item.deleted_at) : '未知时间'}
                      </Text>
                    }
                  />
                </List.Item>
              )}
            />
          )}
    </Drawer>
  )
}
