/** 工作区设置页 —— /w/:wid/settings?section=...；分项导航由 MainLayout 侧栏承担，页内渲染当前分项内容. */

import { useParams, useSearchParams } from 'react-router-dom'
import WorkspaceSettingsContent from '@/pages/settings/WorkspaceSettingsContent'
import { normalizeWorkspaceSettingsSection } from '@/pages/settings/workspaceSettingsSections'

export default function WorkspaceSettingsPage() {
  const { wid } = useParams<{ wid: string }>()
  const [searchParams] = useSearchParams()
  const section = normalizeWorkspaceSettingsSection(searchParams.get('section'))

  return (
    <div className="cn-ws-settings-page">
      <div className="cn-ws-settings-card">
        <WorkspaceSettingsContent wid={wid ?? ''} section={section} />
      </div>
    </div>
  )
}
