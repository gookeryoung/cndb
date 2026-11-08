/** 工作区设置分项定义 —— 侧栏导航与页内内容共用同一份 key / 文案 / 图标. */

import {
  SettingOutlined, SafetyOutlined,
} from '@ant-design/icons'
import type { ReactNode } from 'react'

export type WorkspaceSettingsSectionKey = 'basic' | 'permissions'

export interface WorkspaceSettingsSection {
  key: WorkspaceSettingsSectionKey
  label: string
  icon: ReactNode
}

export const WORKSPACE_SETTINGS_SECTIONS: WorkspaceSettingsSection[] = [
  { key: 'basic', label: '常规设置', icon: <SettingOutlined /> },
  { key: 'permissions', label: '权限管理', icon: <SafetyOutlined /> },
]

/** URL 的 ?section= 归一化：未知 / 缺失一律落到「常规设置」. */
export function normalizeWorkspaceSettingsSection(
  value: string | null | undefined,
): WorkspaceSettingsSectionKey {
  return WORKSPACE_SETTINGS_SECTIONS.some(s => s.key === value)
    ? (value as WorkspaceSettingsSectionKey)
    : 'basic'
}
