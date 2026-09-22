/** 工作区设置独立页面 — /w/:wid/settings. */

import { Breadcrumb, Button, Typography } from 'antd'
import { ArrowLeftOutlined, HomeOutlined } from '@ant-design/icons'
import { useNavigate, useParams } from 'react-router-dom'
import WorkspaceSettingsContent from '@/pages/settings/WorkspaceSettingsContent'
import { useQuery } from '@tanstack/react-query'
import { workspaceApi } from '@/api'

const { Title } = Typography

export default function WorkspaceSettingsPage() {
  const { wid } = useParams<{ wid: string }>()
  const navigate = useNavigate()

  const { data: workspace } = useQuery({
    queryKey: ['workspaces', wid],
    queryFn: () => workspaceApi.get(wid!),
    enabled: !!wid,
  })

  const goBack = () => navigate(`/w/${wid}/tables`)

  return (
    <div style={{ padding: 24 }}>
      {/* 面包屑 */}
      <Breadcrumb
        items={[
          { title: <a onClick={() => navigate('/w')}><HomeOutlined /> 工作区</a> },
          { title: <a onClick={goBack}>{workspace?.name || '工作区'}</a> },
          { title: '设置' },
        ]}
        style={{ marginBottom: 12 }}
      />

      {/* 标题 + 返回按钮 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <Title level={3} style={{ margin: 0 }}>工作区设置</Title>
        <Button
          data-testid="settings-back-btn"
          icon={<ArrowLeftOutlined />}
          onClick={goBack}
        >返回</Button>
      </div>

      {/* 设置内容 */}
      <div
        style={{
          background: 'var(--cn-bg-container)',
          border: '1px solid var(--cn-border)',
          borderRadius: 8,
          padding: 20,
        }}
      >
        <WorkspaceSettingsContent wid={wid ?? ''} />
      </div>
    </div>
  )
}
