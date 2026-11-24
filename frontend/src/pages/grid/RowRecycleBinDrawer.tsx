/** 行回收站抽屉（ADR 0139 C8）.
 *
 * 数据表级「已删行」列表：删除时间 / 操作人 / 行摘要 + 恢复 + 彻底删除（二次确认）。
 * - 门控：入口按 `EDIT_RECORDS` 显示；后端 restore / purge 仍自行校验，越行范围 404。
 * - 彻底删除不可恢复：必须 Popconfirm 二次确认，文案明确。
 * - 列表走 `records.list({ trashed: 'only' })`，与网格共用同一读路径（行级权限同源）。
 */

import { Modal, Button, Popconfirm, Space, Table, Tag, Typography, Empty, App as AntApp } from 'antd'
import { RedoOutlined, DeleteOutlined } from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { recordApi } from '@/api'
import type { TrashedRow } from '@/api'

interface Props {
  open: boolean
  wid: number | string
  tid: number | string
  tableName?: string
  onClose: () => void
  /** 恢复 / 彻底删除后通知父级刷新网格 */
  onChanged?: () => void
}

/** 行摘要：取前 3 个非系统、非空字段值拼一行（回收站不需要整行预览） */
export function rowSummary(row: TrashedRow, limit = 3): string {
  const parts: string[] = []
  for (const [key, value] of Object.entries(row)) {
    if (key.startsWith('_') || key === 'id') continue
    if (value == null || value === '') continue
    if (Array.isArray(value)) {
      if (!value.length) continue
      const text = value.map(item => (typeof item === 'object' && item !== null ? String((item as { value?: unknown }).value ?? '') : String(item))).join('、')
      if (text) parts.push(text)
    } else if (typeof value === 'object') {
      continue
    } else {
      parts.push(String(value))
    }
    if (parts.length >= limit) break
  }
  return parts.join(' · ') || '（无内容）'
}

function formatTime(value?: string | null): string {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '—' : date.toLocaleString()
}

export default function RowRecycleBinDrawer({ open, wid, tid, tableName, onClose, onChanged }: Props) {
  const { message } = AntApp.useApp()
  const qc = useQueryClient()
  const queryKey = ['table-records-trash', wid, tid]

  const listQuery = useQuery({
    queryKey,
    queryFn: () => recordApi.list(wid, tid, { trashed: 'only', limit: 200 }),
    enabled: open,
  })

  const invalidateAll = () => {
    void qc.invalidateQueries({ queryKey })
    void qc.invalidateQueries({ queryKey: ['table-records', `${wid}/${tid}`] })
    onChanged?.()
  }

  const restoreMut = useMutation<unknown, Error, Array<number | string>>({
    mutationFn: (ids: Array<number | string>) =>
      ids.length === 1 ? recordApi.restore(wid, tid, ids[0]) : recordApi.restoreMany(wid, tid, ids),
    onSuccess: () => {
      message.success('已恢复')
      invalidateAll()
    },
    onError: (err: Error) => message.error(err.message || '恢复失败'),
  })

  const purgeMut = useMutation<unknown, Error, Array<number | string>>({
    mutationFn: (ids: Array<number | string>) =>
      ids.length === 1 ? recordApi.purge(wid, tid, ids[0]) : recordApi.purgeMany(wid, tid, ids),
    onSuccess: () => {
      message.success('已彻底删除')
      invalidateAll()
    },
    onError: (err: Error) => message.error(err.message || '彻底删除失败'),
  })

  const rows = listQuery.data?.items ?? []

  return (
    <Modal
      open={open}
      onCancel={onClose}
      footer={null}
      width={860}
      title={<Space><DeleteOutlined />回收站{tableName ? ` · ${tableName}` : ''}</Space>}
      data-testid="row-recycle-bin"
    >
      <Typography.Paragraph type="secondary" style={{ marginTop: 0 }}>
        删除的行保留在这里，可恢复到原位置；「彻底删除」不可恢复。
        超过保留期的行由运维任务自动清理。
      </Typography.Paragraph>
      {listQuery.isLoading ? (
        <div className="cn-state">加载中…</div>
      ) : rows.length === 0 ? (
        <Empty description="回收站是空的" image={Empty.PRESENTED_IMAGE_SIMPLE} />
      ) : (
        <Table<TrashedRow>
          rowKey="id"
          size="small"
          pagination={false}
          dataSource={rows}
          scroll={{ y: 420 }}
          columns={[
            {
              title: '行',
              dataIndex: 'id',
              width: 90,
              render: (_value, row) => <Typography.Text code>#{String(row.id)}</Typography.Text>,
            },
            {
              title: '内容摘要',
              render: (_value, row) => (
                <Typography.Text ellipsis={{ tooltip: rowSummary(row, 6) }} style={{ maxWidth: 320 }}>
                  {rowSummary(row)}
                </Typography.Text>
              ),
            },
            {
              title: '删除时间',
              dataIndex: '_trashed_at',
              width: 180,
              render: (value: string | null) => <span className="cn-text-secondary">{formatTime(value)}</span>,
            },
            {
              title: '删除人',
              dataIndex: '_trashed_by_name',
              width: 140,
              render: (value: string | null | undefined) => value ?? <Tag>未知</Tag>,
            },
            {
              title: '操作',
              width: 190,
              render: (_value, row) => (
                <Space size={4}>
                  <Button
                    type="link"
                    size="small"
                    icon={<RedoOutlined />}
                    loading={restoreMut.isPending}
                    onClick={() => restoreMut.mutate([row.id])}
                  >
                    恢复
                  </Button>
                  <Popconfirm
                    title="彻底删除后不可恢复，确定？"
                    okText="彻底删除"
                    okButtonProps={{ danger: true }}
                    cancelText="取消"
                    onConfirm={() => purgeMut.mutate([row.id])}
                  >
                    <Button type="link" size="small" danger loading={purgeMut.isPending}>
                      彻底删除
                    </Button>
                  </Popconfirm>
                </Space>
              ),
            },
          ]}
        />
      )}
    </Modal>
  )
}
