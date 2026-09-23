/** 工作区设置对话框 — Modal 包装 WorkspaceSettingsContent. */

import { Button, Modal } from 'antd'
import WorkspaceSettingsContent from './WorkspaceSettingsContent'

interface Props {
  open: boolean
  wid: string
  onClose: () => void
  /** 设置保存后通知工作区列表刷新 */
  onUpdated?: () => void
  /** 指定打开时的 Tab，默认 basic */
  initialTab?: 'basic' | 'permissions' | 'stats'
}

export default function WorkspaceSettingsModal({
  open, wid, onClose, onUpdated, initialTab = 'basic',
}: Props) {
  return (
    <Modal
      title="工作区设置"
      open={open}
      onCancel={onClose}
      width={720}
      destroyOnHidden
      footer={[
        <Button key="close" onClick={onClose}>关闭</Button>,
      ]}
    >
      <WorkspaceSettingsContent
        wid={wid}
        initialTab={initialTab}
        onUpdated={onUpdated}
        onDeleted={onClose}
      />
    </Modal>
  )
}
