/**
 * 工作区统计页（一级导航「统计」，位于「工作区设置」左侧）—— 参考 GitHub Insights.
 *
 * 布局参考工作区设置：左侧 Sider 由 MainLayout 渲染「概览 / 贡献统计」分项，
 * 选中项由 URL `?section=` 驱动（缺省 / 未知回落「概览」），内容区只渲染当前分项。
 *
 * - 概览：统一为「使用概况 / 工作区信息 / 存储用量」三段，按启用的功能模块汇总
 *   数据表 / 视图 / 数据行 / 文档 / 设计 / 成员 / 存储。数据与工作区设置共用
 *   `workspace-detail` 查询缓存。
 * - 贡献统计：当前后端没有贡献 / 活跃度聚合接口，先展示空状态占位。
 */

import { useQuery } from '@tanstack/react-query'
import { useParams, useSearchParams } from 'react-router-dom'
import { Descriptions, Progress, Tag } from 'antd'
import {
  BarChartOutlined, FileTextOutlined, EyeOutlined, ColumnWidthOutlined,
  ReadOutlined, ToolOutlined, UserOutlined, HddOutlined, TeamOutlined,
} from '@ant-design/icons'
import { workspaceApi } from '@/api'
import type { WorkspaceDetail } from '@/api'
import { formatSize } from '@/utils/formatSize'
import { workspaceModulesFeatures, WORKSPACE_MODULE_LABEL, normalizeModules } from '@/utils/workspaceModules'
import { VISIBILITY_LABEL } from '@/pages/settings/workspaceRoles'
import { normalizeWorkspaceStatsSection } from './workspaceStatsSections'

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
          <div data-testid="ws-stats-contribution">
            <div className="cn-ws-stats-header">
              <div className="cn-ws-stats-title"><TeamOutlined /> 贡献统计</div>
              <div className="cn-ws-stats-desc">按成员汇总在工作区内的创建与编辑记录。</div>
            </div>
            <div className="cn-ws-stats-empty">
              <TeamOutlined className="cn-ws-stats-empty-icon" />
              <div className="cn-ws-stats-empty-title">暂无贡献数据</div>
              <div className="cn-ws-stats-empty-desc">
                贡献统计需要后端按成员聚合活动记录，待数据接入后在此展示。
              </div>
            </div>
          </div>
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
