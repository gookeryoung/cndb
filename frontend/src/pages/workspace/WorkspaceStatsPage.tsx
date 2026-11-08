/**
 * 工作区统计页（一级导航「统计」，位于「工作区设置」左侧）—— 参考 GitHub Insights.
 *
 * 只做只读汇总：按当前启用的功能模块展示数据表 / 视图 / 数据行 / 文档 / 设计 / 成员 / 存储，
 * 再给出存储用量进度。数据与工作区设置共用 `workspace-detail` 查询缓存，切换入口不重复请求。
 */

import { useQuery } from '@tanstack/react-query'
import { useParams } from 'react-router-dom'
import { Card, Progress, Space } from 'antd'
import {
  BarChartOutlined, FileTextOutlined, EyeOutlined, ColumnWidthOutlined,
  ReadOutlined, ToolOutlined, UserOutlined, HddOutlined,
} from '@ant-design/icons'
import { workspaceApi } from '@/api'
import type { WorkspaceDetail } from '@/api'
import { formatSize } from '@/utils/formatSize'
import { workspaceModulesFeatures } from '@/utils/workspaceModules'

export default function WorkspaceStatsPage() {
  const { wid } = useParams<{ wid: string }>()
  const { data: detail } = useQuery<WorkspaceDetail>({
    queryKey: ['workspace-detail', wid],
    queryFn: () => workspaceApi.get(wid ?? ''),
    enabled: !!wid,
  })

  const features = workspaceModulesFeatures(detail?.modules)
  const statItems = [
    ...(features.tables
      ? [
          { label: '数据表', value: detail?.table_count ?? 0, icon: <FileTextOutlined />, color: 'var(--cn-brand-color)' },
          { label: '视图', value: detail?.view_count ?? 0, icon: <EyeOutlined />, color: '#10b981' },
          { label: '数据行', value: detail?.total_rows ?? 0, icon: <ColumnWidthOutlined />, color: '#f59e0b' },
        ]
      : []),
    ...(features.documents
      ? [{ label: '文档', value: detail?.document_count ?? 0, icon: <ReadOutlined />, color: '#08979c' }]
      : []),
    ...(features.design
      ? [{ label: '设计', value: detail?.design_count ?? 0, icon: <ToolOutlined />, color: '#7c3aed' }]
      : []),
    { label: '成员', value: detail?.member_count ?? 0, icon: <UserOutlined />, color: '#8b5cf6' },
    { label: '占用空间', value: formatSize(detail?.storage_bytes ?? 0), icon: <HddOutlined />, color: '#0ea5e9' },
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
        <div className="cn-ws-stats-header">
          <div className="cn-ws-stats-title"><BarChartOutlined /> 工作区统计</div>
          <div className="cn-ws-stats-desc">按当前启用的功能模块汇总，数据随工作区内容实时更新。</div>
        </div>

        <div data-testid="ws-stats-grid" className="cn-ws-settings-stats">
          {statItems.map(item => (
            <div key={item.label} className="cn-ws-settings-stat" style={{ borderLeft: `3px solid ${item.color}` }}>
              <div className="cn-ws-settings-stat-label">{item.icon} {item.label}</div>
              <div className="cn-ws-settings-stat-value">
                {typeof item.value === 'number' ? item.value.toLocaleString() : item.value}
              </div>
            </div>
          ))}
        </div>

        <Card size="small" title={<Space><HddOutlined /> 存储用量</Space>}>
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
        </Card>
      </div>
    </div>
  )
}
