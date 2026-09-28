/** 工作区设置页 —— /w/:wid/settings；导航由 MainLayout 的分页 tab 承担，页内仅渲染设置内容. */

import { useParams } from 'react-router-dom'
import WorkspaceSettingsContent from '@/pages/settings/WorkspaceSettingsContent'

export default function WorkspaceSettingsPage() {
  const { wid } = useParams<{ wid: string }>()

  return (
    <div style={{ padding: 24 }}>
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
