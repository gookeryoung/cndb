/** 数据表设置独立页面 — /w/:wid/tables/:tid/settings. */

import { Breadcrumb, Button, Typography } from 'antd'
import { ArrowLeftOutlined, HomeOutlined } from '@ant-design/icons'
import { useNavigate, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { workspaceApi, tableApi } from '@/api'
import TableSettingsModal from '@/pages/modals/TableSettingsModal'

const { Title } = Typography

export default function TableSettingsPage() {
  const { wid, tid } = useParams<{ wid: string; tid: string }>()
  const navigate = useNavigate()

  const { data: workspace } = useQuery({
    queryKey: ['workspaces', wid],
    queryFn: () => workspaceApi.get(wid!),
    enabled: !!wid,
  })

  const { data: table } = useQuery({
    queryKey: ['table-settings', wid, tid],
    queryFn: () => tableApi.get(wid!, tid!),
    enabled: !!wid && !!tid,
  })

  const goWorkspaces = () => navigate('/w')
  const goTableList = () => navigate(`/w/${wid}/tables`)
  const goGrid = () => navigate(`/w/${wid}/tables/${tid}`)

  return (
    <div style={{ padding: 24 }}>
      {/* 面包屑 */}
      <Breadcrumb
        items={[
          { title: <a onClick={goWorkspaces}><HomeOutlined /> 工作区</a> },
          { title: <a onClick={goTableList}>{workspace?.name || '工作区'}</a> },
          { title: <a onClick={goGrid}>{table?.name || '表'}</a> },
          { title: '设置' },
        ]}
        style={{ marginBottom: 12 }}
      />

      {/* 标题 + 返回按钮 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <Title level={3} style={{ margin: 0 }}>
          表设置{table?.name ? ` — ${table.name}` : ''}
        </Title>
        <Button
          data-testid="settings-back-btn"
          icon={<ArrowLeftOutlined />}
          onClick={goGrid}
        >返回</Button>
      </div>

      {/* 设置内容（embedded 模式，不包 Modal） */}
      <div
        style={{
          background: 'var(--cn-bg-container)',
          border: '1px solid var(--cn-border)',
          borderRadius: 8,
          padding: 20,
        }}
      >
        <TableSettingsModal
          embedded
          wid={wid ?? ''}
          tid={tid ?? ''}
        />
      </div>
    </div>
  )
}
