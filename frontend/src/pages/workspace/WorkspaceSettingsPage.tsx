/** 工作区设置页 —— /w/:wid/settings；导航由 MainLayout 的分页 tab 承担，页内仅渲染设置内容. */

import { useParams } from 'react-router-dom'
import WorkspaceSettingsContent from '@/pages/settings/WorkspaceSettingsContent'

export default function WorkspaceSettingsPage() {
  const { wid } = useParams<{ wid: string }>()

  return (
    <div className="cn-ws-settings-page">
      <div className="cn-ws-settings-card">
        <WorkspaceSettingsContent wid={wid ?? ''} />
      </div>
    </div>
  )
}
