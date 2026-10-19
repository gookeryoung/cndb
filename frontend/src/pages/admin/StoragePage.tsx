/** 空间分配 — 管理台分区：为每个工作区分配存储配额（上限）。
 *
 * 数据来源 `/api/v1/admin/workspaces/storage`：已用空间按附件、文档外存文件与
 * 数据库内联文档正文、数据表记录实际占用汇总。默认配额 100MB，管理员可逐工作区
 * 调整（单位 MB）。列表紧凑呈现「已用 / 配额 / 使用率」，超过 80% 高亮、达到上限标红。
 */

import { useState } from 'react'
import { Table, Button, InputNumber, Progress, Space, Tag, Typography, App as AntApp } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { HddOutlined, EditOutlined } from '@ant-design/icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { adminApi } from '@/api'
import type { WorkspaceStorageItem } from '@/api'
import { formatSize } from '@/utils/formatSize'

const { Text } = Typography

const MB = 1024 * 1024

/** 字节 → MB（保留一位小数） */
const toMb = (bytes: number) => Math.round((bytes / MB) * 10) / 10

/** 使用率配色：≥100% 红、≥80% 橙、其余品牌色 */
function usageColor(used: number, quota: number): string {
  if (quota <= 0) return '#dc2626'
  const ratio = used / quota
  if (ratio >= 1) return '#dc2626'
  if (ratio >= 0.8) return '#f59e0b'
  return 'var(--cn-brand-color)'
}

export default function StoragePage() {
  const { message } = AntApp.useApp()
  const queryClient = useQueryClient()
  const { data, isLoading } = useQuery({
    queryKey: ['admin-workspace-storage'],
    queryFn: adminApi.workspaceStorage,
  })

  // 行内编辑：记录正在调整的工作区 id 与草稿（MB）
  const [editingId, setEditingId] = useState<number | null>(null)
  const [draftMb, setDraftMb] = useState<number>(100)

  const saveQuota = useMutation({
    mutationFn: ({ id, quotaBytes }: { id: number; quotaBytes: number }) =>
      adminApi.updateWorkspaceQuota(id, quotaBytes),
    onSuccess: () => {
      message.success('配额已更新')
      setEditingId(null)
      queryClient.invalidateQueries({ queryKey: ['admin-workspace-storage'] })
    },
    onError: (err) => message.error(err instanceof Error ? err.message : '更新配额失败'),
  })

  const items = data?.items ?? []
  const defaultQuota = data?.default_quota_bytes ?? 100 * MB
  const totalUsed = items.reduce((sum, it) => sum + it.used_bytes, 0)

  const columns: ColumnsType<WorkspaceStorageItem> = [
    {
      title: '工作区',
      dataIndex: 'name',
      key: 'name',
      render: (_: unknown, row) => (
        <Space size={6}>
          <Text strong>{row.name}</Text>
          <Text type="secondary" style={{ fontSize: 12 }}>#{row.workspace_id}</Text>
          {row.owner_username && <Tag bordered={false}>{row.owner_username}</Tag>}
        </Space>
      ),
    },
    {
      title: '已用',
      dataIndex: 'used_bytes',
      key: 'used_bytes',
      align: 'right',
      width: 100,
      sorter: (a, b) => a.used_bytes - b.used_bytes,
      render: (bytes: number) => <Text>{formatSize(bytes)}</Text>,
    },
    {
      title: '配额',
      dataIndex: 'quota_bytes',
      key: 'quota_bytes',
      align: 'right',
      width: 190,
      sorter: (a, b) => a.quota_bytes - b.quota_bytes,
      render: (quota: number, row) => {
        if (editingId === row.workspace_id) {
          return (
            <Space.Compact size="small">
              <InputNumber
                autoFocus
                min={0}
                step={10}
                precision={1}
                value={draftMb}
                onChange={(v) => setDraftMb(v ?? 0)}
                addonAfter="MB"
                style={{ width: 120 }}
                data-testid={`quota-input-${row.workspace_id}`}
              />
              <Button
                size="small"
                type="primary"
                loading={saveQuota.isPending}
                onClick={() => saveQuota.mutate({ id: row.workspace_id, quotaBytes: Math.round(draftMb * MB) })}
              >
                保存
              </Button>
              <Button size="small" onClick={() => setEditingId(null)}>取消</Button>
            </Space.Compact>
          )
        }
        return (
          <Space size={6}>
            <Text>{formatSize(quota)}</Text>
            <Button
              size="small"
              type="text"
              icon={<EditOutlined />}
              data-testid={`quota-edit-${row.workspace_id}`}
              onClick={() => { setEditingId(row.workspace_id); setDraftMb(toMb(quota)) }}
            >
              调整
            </Button>
          </Space>
        )
      },
    },
    {
      title: '使用率',
      key: 'usage',
      width: 200,
      render: (_, row) => {
        const quota = row.quota_bytes
        const percent = quota > 0 ? Math.min(100, (row.used_bytes / quota) * 100) : 100
        return (
          <Progress
            percent={Number(percent.toFixed(1))}
            strokeColor={usageColor(row.used_bytes, quota)}
            size="small"
            format={(p) => `${p ?? 0}%`}
          />
        )
      },
    },
    {
      title: '状态',
      key: 'status',
      width: 90,
      render: (_, row) => {
        const full = row.quota_bytes <= 0 || row.used_bytes >= row.quota_bytes
        return full
          ? <Tag color="red">已达上限</Tag>
          : <Tag color="green">正常</Tag>
      },
    },
  ]

  return (
    <div className="cn-admin-section">
      <div className="cn-hint" style={{ marginBottom: 12 }}>
        <HddOutlined />
        <div>
          默认配额 <Text strong>{formatSize(defaultQuota, 0)}</Text>
          {' '}· 共 {items.length} 个工作区，合计占用 <Text strong>{formatSize(totalUsed)}</Text>。
          配额为每个工作区可用的存储上限（附件、文档与数据表记录合计），超出后不再允许上传新附件。
        </div>
      </div>

      <Table<WorkspaceStorageItem>
        rowKey="workspace_id"
        size="small"
        loading={isLoading}
        dataSource={items}
        columns={columns}
        pagination={items.length > 20 ? { pageSize: 20, size: 'small' } : false}
        scroll={{ x: 'max-content' }}
      />
    </div>
  )
}
