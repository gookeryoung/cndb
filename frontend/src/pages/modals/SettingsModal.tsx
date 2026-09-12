/** 用户设置面板 — 主题切换. */

import { Modal, Button, Space, Switch } from 'antd'
import { useTheme } from '@/theme/ThemeProvider'

interface Props {
  open: boolean
  onClose: () => void
}

export default function SettingsModal({ open, onClose }: Props) {
  const { mode, toggle } = useTheme()

  return (
    <Modal
      title="个人设置"
      open={open}
      onCancel={onClose}
      footer={[<Button key="close" onClick={onClose}>关闭</Button>]}
      width={400}
      destroyOnHidden
    >
      <div style={{ padding: '24px 0' }}>
        <Space size="large">
          <span>暗色模式</span>
          <Switch checked={mode === 'dark'} onChange={toggle} />
        </Space>
        <div style={{ marginTop: 12, fontSize: 12, color: '#64748b' }}>
          设置会自动保存到浏览器。
        </div>
      </div>
    </Modal>
  )
}
