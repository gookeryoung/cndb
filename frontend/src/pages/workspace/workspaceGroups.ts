/** 首页工作区按团队分组（需求 0157 C1 / C5）.
 *
 * 团队单层、团队下工作区平铺（ADR 0153 C1 / C2）：这里只做「已收藏 → 团队组 → 个人」
 * 的确定性分组与排序，不引入树 / 嵌套。桌面首页、顶栏切换器、移动端抽屉共用同一套纯函数。
 *
 * 排序口径：
 *  - 团队组按 `updated_at` 倒序（最近有活动的团队靠前），同值按名称稳定兜底（N6）；
 *  - 团队组内保持调用方传入的顺序（首页已按 `workspace_order` 排过）；
 *  - 个人工作区恒为最后一组。
 */

/** 分组所需的最小工作区字段（与 `Workspace` 结构兼容） */
export interface GroupableWorkspace {
  id: number | string
  name?: string
  team_id?: number | null
  team?: { id: number | string; name: string } | null
  pinned?: boolean | null
}

/** 分组所需的团队字段 */
export interface GroupableTeam {
  id: number | string
  name: string
  updated_at?: string
  workspace_count?: number
}

export interface WorkspaceGroup<T> {
  /** 稳定 key：`team-<id>` / `personal`（折叠态持久化与 React key 共用） */
  key: string
  /** 团队 id；个人组为 null */
  teamId: number | null
  title: string
  /** 个人工作区分组 */
  isPersonal: boolean
  workspaces: T[]
  /** 团队组专属：所属团队 */
  team?: GroupableTeam
}

/** 团队排序：updated_at 倒序（无值垫底）→ 名称 → id */
function compareTeams(a: GroupableTeam, b: GroupableTeam): number {
  const ta = a.updated_at ? Date.parse(a.updated_at) : Number.NaN
  const tb = b.updated_at ? Date.parse(b.updated_at) : Number.NaN
  const va = Number.isNaN(ta) ? -Infinity : ta
  const vb = Number.isNaN(tb) ? -Infinity : tb
  if (va !== vb) return vb - va
  const byName = a.name.localeCompare(b.name, 'zh-Hans-CN')
  if (byName !== 0) return byName
  return Number(a.id) - Number(b.id)
}

/**
 * 按团队分组（默认剔除已收藏：收藏行由页面顶部「已收藏」独立承载，避免同一行出现两次，N5）。
 * 返回顺序 = 有工作区的团队组（排序后）→ 个人组（非空时）。
 */
export function groupWorkspacesByTeam<T extends GroupableWorkspace>(
  workspaces: readonly T[],
  teams: readonly GroupableTeam[],
): Array<WorkspaceGroup<T>> {
  const teamById = new Map<string, GroupableTeam>()
  for (const team of teams) teamById.set(String(team.id), team)

  const buckets = new Map<string, T[]>()
  const personal: T[] = []
  for (const ws of workspaces) {
    if (ws.pinned) continue
    if (ws.team_id == null) {
      personal.push(ws)
      continue
    }
    const key = String(ws.team_id)
    // 归属团队不在 `teams` 列表（如团队列表请求失败 / 被移出团队）：
    // 优先回退到工作区自带的 team 摘要，缺失时保留一个占位组，避免工作区被静默丢弃
    if (!teamById.has(key)) {
      teamById.set(key, ws.team
        ? { id: ws.team.id, name: ws.team.name }
        : { id: ws.team_id, name: `团队 #${ws.team_id}` })
    }
    const list = buckets.get(key) ?? []
    list.push(ws)
    buckets.set(key, list)
  }

  const groups: Array<WorkspaceGroup<T>> = []
  const orderedTeams = [...teamById.values()].sort(compareTeams)
  for (const team of orderedTeams) {
    const rows = buckets.get(String(team.id))
    if (!rows || rows.length === 0) continue
    groups.push({
      key: `team-${team.id}`,
      teamId: Number(team.id),
      title: team.name,
      isPersonal: false,
      team,
      workspaces: rows,
    })
  }
  if (personal.length > 0) {
    groups.push({
      key: 'personal',
      teamId: null,
      title: '个人工作区',
      isPersonal: true,
      workspaces: personal,
    })
  }
  return groups
}

/** 首页团队筛选的取值：全部 / 个人 / 某个团队 id */
export type WorkspaceScope = 'all' | 'personal' | number

/** 按首页团队筛选收窄工作区（`all` 原样返回） */
export function filterWorkspacesByScope<T extends GroupableWorkspace>(
  workspaces: readonly T[],
  scope: WorkspaceScope,
): T[] {
  if (scope === 'all') return [...workspaces]
  if (scope === 'personal') return workspaces.filter(w => w.team_id == null)
  return workspaces.filter(w => w.team_id != null && String(w.team_id) === String(scope))
}

/** 团队 chips 选项（全部 / 个人 / 各团队，带计数） */
export function scopeOptions(
  teams: readonly GroupableTeam[],
  workspaces: readonly GroupableWorkspace[],
): Array<{ value: WorkspaceScope; label: string; count: number }> {
  return [
    { value: 'all', label: '全部', count: workspaces.length },
    { value: 'personal', label: '个人工作区', count: workspaces.filter(w => w.team_id == null).length },
    ...teams.map(team => ({
      value: Number(team.id) as WorkspaceScope,
      label: team.name,
      count: workspaces.filter(w => w.team_id != null && String(w.team_id) === String(team.id)).length,
    })),
  ]
}

/** 按当前渲染的分组顺序拼接 id，作为一次拖拽排序的全量提交（含已收藏组） */
export function flattenGroupedOrder<T extends { id: number | string }>(
  starred: readonly T[],
  groups: ReadonlyArray<WorkspaceGroup<T>>,
): number[] {
  return [...starred, ...groups.flatMap(g => g.workspaces)].map(w => Number(w.id))
}

/** 判断首页是否需要展示团队分组（无团队 / 无团队归属时保持现状，C9） */
export function hasTeamGrouping(
  teams: readonly GroupableTeam[],
  workspaces: readonly GroupableWorkspace[],
): boolean {
  return teams.length > 0 && workspaces.some(w => w.team_id != null)
}
