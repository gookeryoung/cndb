/** 工作区统计分项定义 —— 侧栏导航与页内内容共用同一份 key / 文案 / 图标. */

import { BarChartOutlined, TeamOutlined } from '@ant-design/icons'
import type { ReactNode } from 'react'

export type WorkspaceStatsSectionKey = 'overview' | 'contribution'

export interface WorkspaceStatsSection {
  key: WorkspaceStatsSectionKey
  label: string
  icon: ReactNode
}

/** 侧栏分项顺序：概览 → 贡献统计（2026-11-08 用户口径） */
export const WORKSPACE_STATS_SECTIONS: WorkspaceStatsSection[] = [
  { key: 'overview', label: '概览', icon: <BarChartOutlined /> },
  { key: 'contribution', label: '贡献统计', icon: <TeamOutlined /> },
]

/** URL 的 ?section= 归一化：未知 / 缺失一律落到「概览」. */
export function normalizeWorkspaceStatsSection(
  value: string | null | undefined,
): WorkspaceStatsSectionKey {
  return WORKSPACE_STATS_SECTIONS.some(s => s.key === value)
    ? (value as WorkspaceStatsSectionKey)
    : 'overview'
}
