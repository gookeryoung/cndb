/** 团队页分区定义（需求 0157 C3）.
 *
 * 与工作区设置 / 统计页同范式：`?section=` 驱动，便于深链、刷新与回退保持。
 * 默认 `overview`；未知取值归一为 `overview`。
 */

export type TeamSectionKey = 'overview' | 'workspaces' | 'members' | 'policy' | 'search'

export interface TeamSectionMeta {
  key: TeamSectionKey
  label: string
}

export const TEAM_SECTIONS: readonly TeamSectionMeta[] = [
  { key: 'overview', label: '概览' },
  { key: 'workspaces', label: '工作区' },
  { key: 'members', label: '成员' },
  { key: 'policy', label: '策略' },
  { key: 'search', label: '搜索' },
] as const

export const DEFAULT_TEAM_SECTION: TeamSectionKey = 'overview'

export function normalizeTeamSection(value: string | null | undefined): TeamSectionKey {
  const hit = TEAM_SECTIONS.find(s => s.key === value)
  return hit?.key ?? DEFAULT_TEAM_SECTION
}

/** 团队分区深链（默认分区不带 query，保持 URL 简洁） */
export function teamSectionHref(tid: number | string, section: TeamSectionKey): string {
  return section === DEFAULT_TEAM_SECTION ? `/teams/${tid}` : `/teams/${tid}?section=${section}`
}
