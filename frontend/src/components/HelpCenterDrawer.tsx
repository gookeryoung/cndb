/** HelpCenterDrawer — 应用内帮助中心抽屉.
 *
 * 左侧主题导航 + 右侧内容区，内容来自 helpContent.tsx（静态 JSX）。
 * 底部提供「重新播放新手引导」按钮（经 onboarding store 发出重放信号）。
 */

import { useState } from 'react'
import { Button, Drawer, Menu, Space, Typography } from 'antd'
import { PlayCircleOutlined } from '@ant-design/icons'
import { useOnboardingStore } from '@/store/onboarding'
import { HELP_CENTER_TITLE, HELP_TOPICS } from './helpContent'

const { Text } = Typography

export interface HelpCenterDrawerProps {
  open: boolean
  onClose: () => void
}

export default function HelpCenterDrawer({ open, onClose }: HelpCenterDrawerProps) {
  const [activeKey, setActiveKey] = useState(HELP_TOPICS[0]!.key)
  const requestTour = useOnboardingStore(s => s.requestTour)
  const active = HELP_TOPICS.find(t => t.key === activeKey) ?? HELP_TOPICS[0]!

  const handleReplayTour = () => {
    requestTour()
    onClose()
  }

  return (
    <Drawer
      title={HELP_CENTER_TITLE}
      open={open}
      onClose={onClose}
      width={620}
      data-testid="help-center-drawer"
      footer={
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <Text type="secondary" style={{ fontSize: 12 }}>
            使用中遇到问题？先看看这里，或把鼠标悬停在按钮上查看提示。
          </Text>
          <Button
            icon={<PlayCircleOutlined />}
            onClick={handleReplayTour}
            data-testid="replay-tour-btn"
          >
            重新播放新手引导
          </Button>
        </div>
      }
    >
      <div style={{ display: 'flex', gap: 12, minHeight: '100%' }}>
        <Menu
          mode="inline"
          selectedKeys={[activeKey]}
          onClick={({ key }) => setActiveKey(key)}
          style={{ width: 150, flexShrink: 0, borderInlineEnd: '1px solid var(--cn-border)' }}
          items={HELP_TOPICS.map(t => ({ key: t.key, label: t.label }))}
        />
        <div style={{ flex: 1, minWidth: 0 }}>
          <Space direction="vertical" size={12} style={{ width: '100%' }}>
            {active.content}
          </Space>
        </div>
      </div>
    </Drawer>
  )
}
