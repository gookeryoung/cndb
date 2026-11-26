/** 工作区链接 · 只读数据页（ADR 0154 P2）.
 *
 * 路由：`/w/:wid/links/:linkId`
 *
 * 只读边界（H54）：
 * - 页面不提供任何编辑 / 删除 / 批量入口，只用 antd Table 展示链接端点返回的行；
 * - 顶部固定展示「来源工作区 / 批准人 / 到期时间 / 我的可读状态」，不可读时给出可执行下一步；
 * - 数据经 `GET /{wid}/links/{id}/fields|rows` 取得（后端已按行级规则与字段隐藏裁剪）。
 */

import { useMemo, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { Link, useNavigate, useParams } from 'react-router-dom'
import {
  Alert, App as AntApp, Button, Empty, Skeleton, Space, Table, Tag, Typography,
} from 'antd'
import { ArrowLeftOutlined, DownloadOutlined, LinkOutlined, ReloadOutlined } from '@ant-design/icons'

import { linksApi } from '@/api'
import type { LinkField, WorkspaceLink } from '@/api'
import { useResponsive } from '@/hooks/useResponsive'
import { helpLink, subsectionAnchor } from '@/pages/help/helpNav'
import { formatDateTime } from '@/utils/datetime'

const { Text, Title } = Typography
const PAGE_SIZE = 50

const STATUS_META: Record<string, { color: string; text: string }> = {
  pending: { color: 'gold', text: '待源工作区批准' },
  active: { color: 'green', text: '生效中' },
  rejected: { color: 'red', text: '已拒绝' },
  expired: { color: 'default', text: '已到期' },
}

export default function LinkedTablePage() {
  const { wid, linkId } = useParams<{ wid: string; linkId: string }>()
  const navigate = useNavigate()
  const { message } = AntApp.useApp()
  const { isMobile } = useResponsive()
  const [offset, setOffset] = useState(0)

  const { data: links = [] } = useQuery<WorkspaceLink[]>({
    queryKey: ['workspace-links', wid],
    queryFn: () => linksApi.list(wid as string),
    enabled: !!wid,
  })
  const link = useMemo(
    () => links.find(item => String(item.id) === String(linkId)) ?? null,
    [links, linkId],
  )

  const { data: fieldsData, isLoading: fieldsLoading, error: fieldsError } = useQuery({
    queryKey: ['workspace-link-fields', wid, linkId],
    queryFn: () => linksApi.fields(wid as string, linkId as string),
    enabled: !!wid && !!linkId,
    retry: false,
  })

  const { data: rowsData, isLoading: rowsLoading, refetch } = useQuery({
    queryKey: ['workspace-link-rows', wid, linkId, offset],
    queryFn: () => linksApi.rows(wid as string, linkId as string, { offset, limit: PAGE_SIZE }),
    enabled: !!wid && !!linkId && !fieldsError,
    retry: false,
  })

  const download = useMutation({
    mutationFn: () => linksApi.exportCsv(wid as string, linkId as string),
    onSuccess: (blob) => {
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `${link?.alias ?? 'link'}.csv`
      a.click()
      URL.revokeObjectURL(url)
    },
    onError: (err) => message.error(err instanceof Error ? err.message : '导出失败'),
  })

  const columns = (fieldsData?.fields ?? []).map((field: LinkField) => ({
    title: field.name,
    dataIndex: field.name,
    key: field.name,
    ellipsis: true,
    render: (value: unknown) => (value === null || value === undefined || value === ''
      ? <Text type="secondary">—</Text>
      : String(value)),
  }))

  const denied = !!fieldsError
  const statusMeta = STATUS_META[link?.status ?? 'pending']

  return (
    <div style={{ padding: isMobile ? 12 : 16 }} data-testid="linked-table-page">
      <Space direction="vertical" size={12} style={{ width: '100%' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12, flexWrap: 'wrap' }}>
          <div>
            <Title level={3} style={{ margin: 0 }}>
              <LinkOutlined style={{ marginRight: 8 }} />
              {link?.alias ?? fieldsData?.table_name ?? '外部链接'}
            </Title>
            <Text type="secondary" data-testid="linked-table-source">
              来源工作区：{link?.source_workspace_name || '—'} · 表：{fieldsData?.table_name || link?.target_table_name || '—'}
              {fieldsData?.target_type === 'view' ? ' · 按视图筛选' : ''}
            </Text>
          </div>
          <Space wrap>
            <Button icon={<ArrowLeftOutlined />} onClick={() => navigate(`/w/${wid}/tables`)}>
              返回数据表
            </Button>
            <Button
              icon={<ReloadOutlined />}
              onClick={() => refetch()}
              data-testid="linked-table-refresh"
            >
              刷新
            </Button>
            <Button
              icon={<DownloadOutlined />}
              loading={download.isPending}
              disabled={denied || !fieldsData}
              onClick={() => download.mutate()}
              data-testid="linked-table-export"
            >
              导出 CSV
            </Button>
          </Space>
        </div>

        <div data-testid="linked-table-meta">
          <Space wrap size={8}>
            <Tag color={statusMeta.color}>{statusMeta.text}</Tag>
            <Text type="secondary">
              批准人：{link?.approved_by_name || '—'} · 到期：
              {link?.expires_at ? formatDateTime(link.expires_at) : '—'}
            </Text>
            <Tag color="blue">只读</Tag>
            <Link className="cn-help-inline-link" to={helpLink('tutorials', 'workspace-links', subsectionAnchor('link-lifecycle'))}>
              链接状态说明
            </Link>
          </Space>
        </div>

        {denied ? (
          <Alert
            type="warning"
            showIcon
            data-testid="linked-table-denied"
            message="你目前无法读取该链接的数据"
            description="链接为只读引用，需要你在源工作区具备读取权限。请联系源工作区拥有者把你加为查看者，或请其重新批准该链接。"
          />
        ) : fieldsLoading ? (
          <Skeleton active />
        ) : (
          <Table
            size="small"
            rowKey={(row) => String((row as Record<string, unknown>).id ?? Math.random())}
            loading={rowsLoading}
            columns={columns}
            dataSource={(rowsData?.rows ?? []) as Array<Record<string, unknown>>}
            scroll={{ x: 'max-content' }}
            pagination={{
              current: Math.floor(offset / PAGE_SIZE) + 1,
              pageSize: PAGE_SIZE,
              total: rowsData?.total ?? 0,
              showSizeChanger: false,
              onChange: (page) => setOffset((page - 1) * PAGE_SIZE),
            }}
            locale={{ emptyText: <Empty description="链接暂无可读数据" /> }}
            data-testid="linked-table-grid"
          />
        )}
      </Space>
    </div>
  )
}
