/**
 * 工作区统计页（一级导航「统计」，位于「工作区设置」左侧）—— 参考 GitHub Insights.
 *
 * 布局参考工作区设置：左侧 Sider 由 MainLayout 渲染「概览 / 贡献统计」分项，
 * 选中项由 URL `?section=` 驱动（缺省 / 未知回落「概览」），内容区只渲染当前分项。
 *
 * - 概览：统一为「使用概况 / 工作区信息 / 存储用量」三段，按启用的功能模块汇总
 *   数据表 / 视图 / 数据行 / 文档 / 设计 / 成员 / 存储。数据与工作区设置共用
 *   `workspace-detail` 查询缓存。
 * - 贡献统计：按编辑者聚合数据行创建 / 编辑、文档新建 / 保存、设计新建 / 保存；
 *   当前不是 owner / editor 但留下过直接写活动的人标记为「曾为编辑者」并保留展示。
 */

import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useParams, useSearchParams } from 'react-router-dom'
import { Avatar, Alert, Descriptions, Empty, Input, Progress, Select, Table, Tag, Tooltip } from 'antd'
import type { TableProps } from 'antd'
import {
  BarChartOutlined, FileTextOutlined, EyeOutlined, ColumnWidthOutlined,
  ReadOutlined, ToolOutlined, UserOutlined, HddOutlined, TeamOutlined, SearchOutlined,
} from '@ant-design/icons'
import { workspaceApi } from '@/api'
import type { WorkspaceContributionItem, WorkspaceContributions, WorkspaceDetail } from '@/api'
import { formatSize } from '@/utils/formatSize'
import { workspaceModulesFeatures, WORKSPACE_MODULE_LABEL, normalizeModules } from '@/utils/workspaceModules'
import { VISIBILITY_LABEL } from '@/pages/settings/workspaceRoles'
import { normalizeWorkspaceStatsSection } from './workspaceStatsSections'
import ContributionCharts from './ContributionCharts'
import {
  ContributionBreakdown,
  ContributionKpis,
  ContributionRanking,
  formatRelative,
  memberName,
} from './ContributionInsights'

const CONTRIBUTION_ROLE_LABEL: Record<string, string> = {
  owner: '所有者',
  editor: '编辑者',
  viewer: '查看者',
}

const CONTRIBUTION_FILTER_OPTIONS = [
  { value: 'all', label: '全部成员' },
  { value: 'active', label: '只看有贡献' },
  { value: 'former', label: '曾为编辑者' },
  { value: 'removed', label: '已移出' },
]

function ContributionSection({
  wid,
  features,
  memberCount,
}: {
  wid: string
  features: ReturnType<typeof workspaceModulesFeatures>
  memberCount?: number
}) {
  const { data, isLoading, isError } = useQuery<WorkspaceContributions>({
    queryKey: ['workspace-contributions', wid],
    queryFn: () => workspaceApi.contributions(wid),
    enabled: !!wid,
  })

  const [keyword, setKeyword] = useState('')
  const [roleFilter, setRoleFilter] = useState('all')

  const items = data?.items
  const grandTotal = (items ?? []).reduce((total, item) => total + item.total, 0)
  const filteredItems = useMemo(() => {
    const query = keyword.trim().toLowerCase()
    return (items ?? []).filter(item => {
      const nickname = (item.nickname ?? '').toLowerCase()
      const username = (item.username ?? '').toLowerCase()
      if (query && !nickname.includes(query) && !username.includes(query)) return false
      if (roleFilter === 'active') return item.total > 0
      if (roleFilter === 'former') return item.is_former_editor
      if (roleFilter === 'removed') return !item.is_member
      return true
    })
  }, [items, keyword, roleFilter])

  const columns: TableProps<WorkspaceContributionItem>['columns'] = [
    {
      title: '成员',
      key: 'member',
      width: 220,
      render: (_, item) => (
        <div className="cn-contrib-member">
          <Avatar size={28}>{memberName(item).slice(0, 1).toUpperCase()}</Avatar>
          <div className="cn-contrib-member-main">
            <div className="cn-contrib-member-name">
              {memberName(item)}
              {!item.is_member && <Tag>已移出</Tag>}
              {item.is_former_editor && <Tag color="orange">曾为编辑者</Tag>}
            </div>
            {item.username && item.username !== memberName(item) && (
              <div className="cn-contrib-member-username">@{item.username}</div>
            )}
            <div className="cn-contrib-member-role">
              {item.role
                ? CONTRIBUTION_ROLE_LABEL[item.role] ?? item.role
                : '非当前成员'}
            </div>
          </div>
        </div>
      ),
    },
    ...(features.tables
      ? [
          { title: '数据行新建', dataIndex: 'rows_created', key: 'rows_created', align: 'right' as const,
            sorter: (a: WorkspaceContributionItem, b: WorkspaceContributionItem) => a.rows_created - b.rows_created,
            render: (value: number) => value.toLocaleString() },
          { title: '数据行更新', dataIndex: 'rows_updated', key: 'rows_updated', align: 'right' as const,
            sorter: (a: WorkspaceContributionItem, b: WorkspaceContributionItem) => a.rows_updated - b.rows_updated,
            render: (value: number) => value.toLocaleString() },
        ]
      : []),
    ...(features.documents
      ? [
          { title: '文档新建', dataIndex: 'documents_created', key: 'documents_created', align: 'right' as const,
            sorter: (a: WorkspaceContributionItem, b: WorkspaceContributionItem) => a.documents_created - b.documents_created,
            render: (value: number) => value.toLocaleString() },
          { title: '文档保存', dataIndex: 'documents_edited', key: 'documents_edited', align: 'right' as const,
            sorter: (a: WorkspaceContributionItem, b: WorkspaceContributionItem) => a.documents_edited - b.documents_edited,
            render: (value: number) => value.toLocaleString() },
        ]
      : []),
    ...(features.design
      ? [
          { title: '设计新建', dataIndex: 'designs_created', key: 'designs_created', align: 'right' as const,
            sorter: (a: WorkspaceContributionItem, b: WorkspaceContributionItem) => a.designs_created - b.designs_created,
            render: (value: number) => value.toLocaleString() },
          { title: '设计保存', dataIndex: 'designs_edited', key: 'designs_edited', align: 'right' as const,
            sorter: (a: WorkspaceContributionItem, b: WorkspaceContributionItem) => a.designs_edited - b.designs_edited,
            render: (value: number) => value.toLocaleString() },
        ]
      : []),
    {
      title: '合计',
      dataIndex: 'total',
      key: 'total',
      align: 'right',
      defaultSortOrder: 'descend',
      sorter: (a: WorkspaceContributionItem, b: WorkspaceContributionItem) => a.total - b.total,
      render: (value: number) => <strong>{value.toLocaleString()}</strong>,
    },
    {
      title: '占比',
      key: 'share',
      width: 132,
      sorter: (a: WorkspaceContributionItem, b: WorkspaceContributionItem) => a.total - b.total,
      render: (_, item) => {
        const share = grandTotal > 0 ? (item.total / grandTotal) * 100 : 0
        return (
          <div className="cn-contrib-share">
            <span className="cn-contrib-share-bar"><i style={{ width: `${share}%` }} /></span>
            <span className="cn-contrib-share-value">{share.toFixed(1)}%</span>
          </div>
        )
      },
    },
    {
      title: '最近活动',
      dataIndex: 'last_active_at',
      key: 'last_active_at',
      sorter: (a: WorkspaceContributionItem, b: WorkspaceContributionItem) =>
        (a.last_active_at ?? '').localeCompare(b.last_active_at ?? ''),
      render: (value: string | null) => value ? (
        <Tooltip title={new Date(value).toLocaleString()}>
          <span>{formatRelative(value)}</span>
        </Tooltip>
      ) : '-',
    },
  ]

  const isEmpty = !isError && !isLoading && (items?.length ?? 0) === 0

  return (
    <div data-testid="ws-stats-contribution">
      <div className="cn-ws-stats-header cn-contrib-header">
        <div>
          <div className="cn-ws-stats-title"><TeamOutlined /> 贡献统计</div>
          <div className="cn-ws-stats-desc">
            按工作区编辑者汇总数据行、文档与设计的直接创建 / 保存，含曾为编辑者与已移出成员。
          </div>
        </div>
        {data?.generated_at && (
          <div className="cn-contrib-updated">
            更新于 {new Date(data.generated_at).toLocaleString()}
          </div>
        )}
      </div>
      {features.tables && (
        <div className="cn-contrib-notice">
          数据行贡献自本版本起统计：历史行操作未记录操作人，无法回溯归属。
        </div>
      )}
      {isError ? (
        <Alert type="error" showIcon message="贡献统计加载失败" description="请稍后重试。" />
      ) : isEmpty ? (
        <div className="cn-ws-stats-empty" data-testid="ws-contribution-empty">
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无贡献数据" />
          <div className="cn-ws-stats-empty-hint">
            成员在工作区创建数据行、保存文档或设计后，这里会自动生成贡献趋势、活动构成与成员排行。
          </div>
        </div>
      ) : data ? (
        <>
          <ContributionKpis data={data} items={data.items} memberCount={memberCount} />
          <div className="cn-contrib-layout">
            <div className="cn-contrib-col">
              <ContributionCharts data={data} items={data.items} />
            </div>
            <div className="cn-contrib-col">
              <ContributionBreakdown items={data.items} features={features} />
              <ContributionRanking items={data.items} />
            </div>
          </div>
          <section className="cn-ws-stats-section">
            <div className="cn-contrib-table-head">
              <div className="cn-ws-stats-section-title">成员贡献明细</div>
              <div className="cn-contrib-filters">
                <Input
                  size="small"
                  allowClear
                  prefix={<SearchOutlined />}
                  placeholder="搜索成员"
                  value={keyword}
                  onChange={event => setKeyword(event.target.value)}
                  style={{ width: 160 }}
                />
                <Select
                  size="small"
                  value={roleFilter}
                  onChange={setRoleFilter}
                  options={CONTRIBUTION_FILTER_OPTIONS}
                  style={{ width: 132 }}
                />
              </div>
            </div>
            <div className="cn-contrib-table-scroll">
              <Table<WorkspaceContributionItem>
                data-testid="ws-stats-contribution-table"
                rowKey="user_id"
                size="small"
                loading={isLoading}
                columns={columns}
                dataSource={filteredItems}
                pagination={false}
                locale={{
                  emptyText: (
                    <Empty
                      image={Empty.PRESENTED_IMAGE_SIMPLE}
                      description={keyword || roleFilter !== 'all' ? '没有匹配的成员' : '暂无贡献数据'}
                    />
                  ),
                }}
              />
            </div>
          </section>
        </>
      ) : null}
    </div>
  )
}

export default function WorkspaceStatsPage() {
  const { wid } = useParams<{ wid: string }>()
  const [searchParams] = useSearchParams()
  const section = normalizeWorkspaceStatsSection(searchParams.get('section'))
  const { data: detail } = useQuery<WorkspaceDetail>({
    queryKey: ['workspace-detail', wid],
    queryFn: () => workspaceApi.get(wid ?? ''),
    enabled: !!wid,
  })

  const features = workspaceModulesFeatures(detail?.modules)
  const statItems = [
    ...(features.tables
      ? [
          { label: '数据表', value: detail?.table_count ?? 0, icon: <FileTextOutlined /> },
          { label: '视图', value: detail?.view_count ?? 0, icon: <EyeOutlined /> },
          { label: '数据行', value: detail?.total_rows ?? 0, icon: <ColumnWidthOutlined /> },
        ]
      : []),
    ...(features.documents
      ? [{ label: '文档', value: detail?.document_count ?? 0, icon: <ReadOutlined /> }]
      : []),
    ...(features.design
      ? [{ label: '设计', value: detail?.design_count ?? 0, icon: <ToolOutlined /> }]
      : []),
    { label: '成员', value: detail?.member_count ?? 0, icon: <UserOutlined /> },
    { label: '占用空间', value: formatSize(detail?.storage_bytes ?? 0), icon: <HddOutlined /> },
  ]

  const storageUsed = detail?.storage_bytes ?? 0
  const storageQuota = detail?.storage_quota_bytes ?? 100 * 1024 * 1024
  const storagePercent = storageQuota > 0
    ? Math.min(100, (storageUsed / storageQuota) * 100)
    : 100
  const storageColor = storagePercent >= 100 ? '#dc2626' : storagePercent >= 80 ? '#f59e0b' : '#0ea5e9'

  return (
    <div className="cn-ws-settings-page">
      <div className="cn-ws-settings-card">
        {section === 'contribution' ? (
          <ContributionSection
            wid={wid ?? ''}
            features={features}
            memberCount={detail?.member_count}
          />
        ) : (
          <>
            <div className="cn-ws-stats-header">
              <div className="cn-ws-stats-title"><BarChartOutlined /> 概览</div>
              <div className="cn-ws-stats-desc">按当前启用的功能模块汇总，数据随工作区内容实时更新。</div>
            </div>

            <section className="cn-ws-stats-section">
              <div className="cn-ws-stats-section-title">使用概况</div>
              <div data-testid="ws-stats-grid" className="cn-ws-settings-stats">
                {statItems.map(item => (
                  <div key={item.label} className="cn-ws-settings-stat">
                    <div className="cn-ws-settings-stat-label">{item.icon} {item.label}</div>
                    <div className="cn-ws-settings-stat-value">
                      {typeof item.value === 'number' ? item.value.toLocaleString() : item.value}
                    </div>
                  </div>
                ))}
              </div>
            </section>

            <section className="cn-ws-stats-section">
              <div className="cn-ws-stats-section-title">工作区信息（只读）</div>
              <Descriptions
                bordered
                size="small"
                colon={false}
                column={{ xs: 1, sm: 1, md: 2 }}
                styles={{ label: { width: 112, whiteSpace: 'nowrap', color: 'var(--cn-text-secondary)' } }}
              >
                <Descriptions.Item label="ID">{detail?.id}</Descriptions.Item>
                <Descriptions.Item label="创建时间">
                  {detail?.created_at ? new Date(detail.created_at).toLocaleString() : '-'}
                </Descriptions.Item>
                <Descriptions.Item label="最后更新">
                  {detail?.updated_at ? new Date(detail.updated_at).toLocaleString() : '-'}
                </Descriptions.Item>
                <Descriptions.Item label="公开性">
                  {VISIBILITY_LABEL[detail?.visibility ?? 'member']}
                </Descriptions.Item>
                <Descriptions.Item label="功能模块">
                  {normalizeModules(detail?.modules).map(m => (
                    <Tag key={m} style={{ marginInlineEnd: 4 }}>{WORKSPACE_MODULE_LABEL[m]}</Tag>
                  ))}
                </Descriptions.Item>
                <Descriptions.Item label="标签">
                  {(detail?.tags ?? []).length > 0
                    ? (detail?.tags ?? []).map(t => <Tag key={t}>{t}</Tag>)
                    : <span style={{ color: 'var(--cn-text-muted)' }}>暂无标签</span>}
                </Descriptions.Item>
              </Descriptions>
            </section>

            <section className="cn-ws-stats-section">
              <div className="cn-ws-stats-section-title">存储用量</div>
              <div className="cn-ws-stats-storage-meta">
                <span>已用 / 配额</span>
                <span>{formatSize(storageUsed)} / {formatSize(storageQuota)}</span>
              </div>
              <Progress percent={Math.round(storagePercent * 10) / 10} strokeColor={storageColor} size="small" />
              <div className="cn-ws-stats-storage-hint">
                {storagePercent >= 100
                  ? '存储空间已用尽，请清理文件或联系管理员扩容'
                  : storagePercent >= 80
                    ? '存储空间即将用尽，建议清理或扩容'
                    : '可继续上传附件与保存文档'}
              </div>
            </section>
          </>
        )}
      </div>
    </div>
  )
}
