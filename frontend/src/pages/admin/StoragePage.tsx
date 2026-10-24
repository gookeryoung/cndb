/** 空间分配 — 管理台分区：为每个工作区分配存储配额（上限）。
 *
 * 用量口径：附件、文档外存文件、数据库内联文档正文 / 个人草稿、数据表记录
 * （含行回收站影子表）。统计成本随「工作区 × 表 × 行」线性增长，因此**不在请求
 * 内现算**（ADR 0024）：后端后台线程按周期重算并落库，本页只读快照。
 *
 * 页面据此做三件事：
 * - 秒开：`staleTime` 内直接渲染缓存，切回管理台不再等一轮统计；
 * - 透明：顶部展示「数据更新于 X 前 · 每 N 分钟自动同步」，未统计的条目显示
 *   「统计中」而不是 0；
 * - 可控：右上「立即刷新」异步投递重算，轮询到结果后自动回填。
 *
 * 列表按**工作区拥有者分组**：组头汇总该拥有者名下工作区数与合计已用 / 配额，
 * 组内逐工作区展示「已用 / 配额 / 使用率」，超过 80% 高亮、达到上限标红。
 */

import { useEffect, useMemo, useState } from 'react'
import {
  Table,
  Button,
  InputNumber,
  Progress,
  Space,
  Tag,
  Typography,
  App as AntApp,
  Collapse,
  Tooltip,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { HddOutlined, EditOutlined, ReloadOutlined, UserOutlined } from '@ant-design/icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { adminApi } from '@/api'
import type { WorkspaceStorageItem } from '@/api'
import { formatSize } from '@/utils/formatSize'

const { Text } = Typography

const MB = 1024 * 1024

/** 无拥有者（owner 成员缺失）分组键 */
const NO_OWNER_KEY = '__no_owner__'

/** 轮询间隔：后台统计进行中时每 2s 取一次 */
const POLL_INTERVAL_MS = 2000
/** 轮询兜底上限：超时即停止（避免刷新失败时无限轮询） */
const POLL_TIMEOUT_MS = 45_000
/** 「刚刚更新」阈值：快照年龄不大于该值即认为本轮已回填 */
const FRESH_SECONDS = 20

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

/** 使用率百分比（0–100，配额为 0 视为占满） */
function usagePercent(used: number, quota: number): number {
  return quota > 0 ? Number(Math.min(100, (used / quota) * 100).toFixed(1)) : 100
}

/** 快照年龄 → 人话（「刚刚」/「N 分钟前」） */
export function formatSnapshotAge(seconds: number | null): string {
  if (seconds === null) return '尚未统计'
  if (seconds < 60) return '刚刚'
  if (seconds < 3600) return `${Math.floor(seconds / 60)} 分钟前`
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} 小时前`
  return `${Math.floor(seconds / 86400)} 天前`
}

/** 同步周期 → 人话（0 表示关闭定时轮次） */
export function formatRefreshInterval(seconds: number): string {
  if (seconds <= 0) return '仅在手动刷新或数据变更时同步'
  if (seconds < 60) return `每 ${seconds} 秒自动同步`
  if (seconds % 60 === 0) return `每 ${seconds / 60} 分钟自动同步`
  return `每 ${Math.round(seconds / 60)} 分钟自动同步`
}

/** 按拥有者分组后的一组工作区（含组内合计） */
interface OwnerGroup {
  key: string
  /** 拥有者用户名；无拥有者成员时为 null */
  owner: string | null
  items: WorkspaceStorageItem[]
  /** 已统计部分的合计（未统计条目不计入） */
  used: number
  quota: number
  /** 组内尚未统计的工作区数 */
  pending: number
}

/** 按拥有者归类：组内保持后端顺序（工作区 id 升序），组间按用户名排序、无拥有者置后 */
function groupByOwner(items: WorkspaceStorageItem[]): OwnerGroup[] {
  const map = new Map<string, OwnerGroup>()
  for (const item of items) {
    const owner = item.owner_username?.trim() || null
    const key = owner ?? NO_OWNER_KEY
    let group = map.get(key)
    if (!group) {
      group = { key, owner, items: [], used: 0, quota: 0, pending: 0 }
      map.set(key, group)
    }
    group.items.push(item)
    if (item.used_bytes === null) {
      group.pending += 1
    } else {
      group.used += item.used_bytes
    }
    group.quota += item.quota_bytes
  }
  return [...map.values()].sort((a, b) => {
    if (a.owner === null) return 1
    if (b.owner === null) return -1
    return a.owner.localeCompare(b.owner, 'zh-CN')
  })
}

export default function StoragePage() {
  const { message } = AntApp.useApp()
  const queryClient = useQueryClient()
  // 手动刷新后轮询：直到后台统计结束且结果已回填
  const [polling, setPolling] = useState(false)

  const { data, isLoading, refetch } = useQuery({
    queryKey: ['admin-workspace-storage'],
    queryFn: adminApi.workspaceStorage,
    // 进入页面直接渲染缓存（后台同步由服务端负责），不再每次重新统计
    staleTime: 60_000,
    refetchOnWindowFocus: false,
    refetchInterval: (query) => {
      const snapshot = query.state.data
      if (polling || snapshot?.refreshing) return POLL_INTERVAL_MS
      return false
    },
  })

  // 轮询收敛：后台已不在统计，且最近一次快照足够新 → 停止
  useEffect(() => {
    if (!polling || !data) return
    const fresh = data.snapshot_age_seconds !== null && data.snapshot_age_seconds <= FRESH_SECONDS
    if (!data.refreshing && (fresh || data.pending_workspace_count === 0)) setPolling(false)
  }, [polling, data])

  // 兜底：后台异常 / 长时间未完成时停止轮询，让按钮恢复可点
  useEffect(() => {
    if (!polling) return
    const timer = window.setTimeout(() => setPolling(false), POLL_TIMEOUT_MS)
    return () => window.clearTimeout(timer)
  }, [polling])

  // 行内编辑：记录正在调整的工作区 id 与草稿（MB）
  const [editingId, setEditingId] = useState<number | null>(null)
  const [draftMb, setDraftMb] = useState<number>(100)
  // 展开的拥有者分组：null 表示跟随数据（全部展开）
  const [openKeys, setOpenKeys] = useState<string[] | null>(null)

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

  const refreshUsage = useMutation({
    mutationFn: () => adminApi.refreshWorkspaceStorage(),
    onSuccess: () => {
      setPolling(true)
      // 立刻取一次：小库可能已经跑完，避免空等一个轮询周期
      void refetch()
    },
    onError: (err) => message.error(err instanceof Error ? err.message : '触发统计失败'),
  })

  const items = useMemo(() => data?.items ?? [], [data])
  const defaultQuota = data?.default_quota_bytes ?? 100 * MB
  const pendingCount = data?.pending_workspace_count ?? 0
  const totalUsed = items.reduce((sum, it) => sum + (it.used_bytes ?? 0), 0)
  const busy = polling || refreshUsage.isPending || (data?.refreshing ?? false)

  const groups = useMemo(() => groupByOwner(items), [items])
  const activeKeys = openKeys ?? groups.map((g) => g.key)

  /** 尚未统计：不显示 0，明确告知正在统计（首次部署 / 新工作区） */
  const pendingText = <Text type="secondary" style={{ fontSize: 12 }}>统计中</Text>

  const columns: ColumnsType<WorkspaceStorageItem> = [
    {
      title: '工作区',
      dataIndex: 'name',
      key: 'name',
      render: (_: unknown, row) => (
        <Space size={6}>
          <Text strong>{row.name}</Text>
          <Text type="secondary" style={{ fontSize: 12 }}>#{row.workspace_id}</Text>
        </Space>
      ),
    },
    {
      title: '已用',
      dataIndex: 'used_bytes',
      key: 'used_bytes',
      align: 'right',
      width: 100,
      sorter: (a, b) => (a.used_bytes ?? -1) - (b.used_bytes ?? -1),
      render: (bytes: number | null) =>
        bytes === null ? pendingText : <Text>{formatSize(bytes)}</Text>,
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
        if (row.used_bytes === null) return pendingText
        const quota = row.quota_bytes
        return (
          <Progress
            percent={usagePercent(row.used_bytes, quota)}
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
        if (row.used_bytes === null) return <Tag bordered={false}>统计中</Tag>
        const full = row.quota_bytes <= 0 || row.used_bytes >= row.quota_bytes
        return full
          ? <Tag color="red">已达上限</Tag>
          : <Tag color="green">正常</Tag>
      },
    },
  ]

  /** 组头：拥有者 + 该拥有者名下工作区数 + 合计已用 / 配额 + 合计使用率 */
  const renderGroupHead = (group: OwnerGroup) => {
    const hasUsage = group.items.length > group.pending
    return (
      <div className="cn-owner-group-head">
        <UserOutlined className="cn-owner-group-icon" />
        <Text strong className="cn-owner-group-name">{group.owner ?? '未分配拥有者'}</Text>
        <Text type="secondary" className="cn-owner-group-meta">
          {group.items.length} 个工作区
          {hasUsage && ` · ${formatSize(group.used)} / ${formatSize(group.quota)}`}
          {group.pending > 0 && ` · ${group.pending} 个统计中`}
        </Text>
        {hasUsage && (
          <Progress
            className="cn-owner-group-usage"
            percent={usagePercent(group.used, group.quota)}
            strokeColor={usageColor(group.used, group.quota)}
            size="small"
            format={(p) => `${p ?? 0}%`}
          />
        )}
      </div>
    )
  }

  const freshness = (
    <>
      数据更新于 <Text strong>{formatSnapshotAge(data?.snapshot_age_seconds ?? null)}</Text>
      {' · '}
      {formatRefreshInterval(data?.refresh_interval_seconds ?? 0)}
      {busy && (
        <>
          {' · '}
          <Text style={{ color: 'var(--cn-brand-color)' }}>正在统计…</Text>
        </>
      )}
    </>
  )

  return (
    <div className="cn-admin-section">
      <div className="cn-hint cn-storage-head">
        <HddOutlined />
        <div className="cn-storage-head-text">
          <div>
            默认配额 <Text strong>{formatSize(defaultQuota, 0)}</Text>
            {' '}· 共 {items.length} 个工作区 / {groups.length} 位拥有者，合计占用{' '}
            <Text strong>{formatSize(totalUsed)}</Text>
            {pendingCount > 0 && (
              <>
                {' '}
                <Tag bordered={false} color="gold">{pendingCount} 个统计中</Tag>
              </>
            )}
          </div>
          <div className="cn-storage-head-sub">
            {freshness}
            {' · '}
            配额为每个工作区可用的存储上限（附件、文档与数据表记录合计），超出后不再允许上传新附件。
          </div>
        </div>
        <Tooltip title="重新统计全部工作区的用量（后台执行，完成后自动刷新）">
          <Button
            size="small"
            className="cn-storage-refresh"
            icon={<ReloadOutlined />}
            loading={busy}
            data-testid="storage-refresh"
            onClick={() => refreshUsage.mutate()}
          >
            {busy ? '统计中…' : '立即刷新'}
          </Button>
        </Tooltip>
      </div>

      <Collapse
        ghost
        size="small"
        className="cn-owner-groups"
        activeKey={activeKeys}
        onChange={(keys) => setOpenKeys(Array.isArray(keys) ? keys : [keys])}
        items={groups.map((group) => ({
          key: group.key,
          label: renderGroupHead(group),
          children: (
            <Table<WorkspaceStorageItem>
              rowKey="workspace_id"
              size="small"
              loading={isLoading}
              dataSource={group.items}
              columns={columns}
              pagination={group.items.length > 10 ? { pageSize: 10, size: 'small' } : false}
              scroll={{ x: 'max-content' }}
            />
          ),
        }))}
      />

      {!isLoading && groups.length === 0 && <Text type="secondary">暂无工作区</Text>}
    </div>
  )
}
