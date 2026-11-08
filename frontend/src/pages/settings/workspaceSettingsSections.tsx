/** 工作区设置分项定义 —— 侧栏导航与页内内容共用同一份 key / 文案 / 图标. */

import {
  SettingOutlined, SafetyOutlined, RocketOutlined,
} from '@ant-design/icons'
import type { ReactNode } from 'react'

export type WorkspaceSettingsSectionKey = 'basic' | 'permissions' | 'lifecycle'

export interface WorkspaceSettingsSection {
  key: WorkspaceSettingsSectionKey
  label: string
  icon: ReactNode
}

export const WORKSPACE_SETTINGS_SECTIONS: WorkspaceSettingsSection[] = [
  { key: 'basic', label: '基本设置', icon: <SettingOutlined /> },
  { key: 'permissions', label: '权限', icon: <SafetyOutlined /> },
  { key: 'lifecycle', label: '生命周期', icon: <RocketOutlined /> },
]

/** URL 的 ?section= 归一化：未知 / 缺失一律落到「基本设置」. */
export function normalizeWorkspaceSettingsSection(
  value: string | null | undefined,
): WorkspaceSettingsSectionKey {
  return WORKSPACE_SETTINGS_SECTIONS.some(s => s.key === value)
    ? (value as WorkspaceSettingsSectionKey)
    : 'basic'
}
