/** 数据源同步运行中速度展示的格式化工具（ADR 0040 D1/D2）.
 *
 * 速度与已用时间一律由后端按运行记录计算，这里只做展示格式化，
 * 不使用浏览器时钟做差，避免多端时间偏差。
 */

/** 运行中任务列表常显上限（超出折叠，ADR 0041 D3）.*/
export const RUNNING_ROWS_LIMIT = 5

/** 已用毫秒 → 中文短文案（如 `9秒` / `1分40秒` / `1小时02分`）.*/
export function formatElapsed(ms: number): string {
  const totalSeconds = Number.isFinite(ms) && ms > 0 ? Math.floor(ms / 1000) : 0
  if (totalSeconds < 60) return `${totalSeconds}秒`
  const minutes = Math.floor(totalSeconds / 60)
  if (minutes < 60) return `${minutes}分${totalSeconds % 60}秒`
  const hours = Math.floor(minutes / 60)
  return `${hours}小时${String(minutes % 60).padStart(2, '0')}分`
}

/** 累计平均写入速度 → `行/秒` 文案（如 `12.3 行/秒`）.*/
export function formatRate(rowsPerSecond: number): string {
  if (!Number.isFinite(rowsPerSecond) || rowsPerSecond <= 0) return '0 行/秒'
  if (rowsPerSecond >= 1000) return `${Math.round(rowsPerSecond).toLocaleString('zh-CN')} 行/秒`
  return `${rowsPerSecond.toFixed(1)} 行/秒`
}

/** 运行中任务排序：最新开始在前，同刻按任务 ID 倒序（ADR 0041 C3）.*/
export function sortRunningJobs<T extends { id: number; last_run_at: string | null }>(jobs: T[]): T[] {
  return [...jobs].sort((left, right) => {
    const leftAt = Date.parse(left.last_run_at ?? '') || 0
    const rightAt = Date.parse(right.last_run_at ?? '') || 0
    if (leftAt !== rightAt) return rightAt - leftAt
    return right.id - left.id
  })
}

/** 运行中任务列表可见行：未展开时截断到常显上限，返回被折叠的数量（ADR 0041 C3）.*/
export function visibleRunningJobs<T extends { id: number; last_run_at: string | null }>(
  jobs: T[],
  expanded: boolean,
): { visible: T[]; hidden: number } {
  const sorted = sortRunningJobs(jobs)
  if (expanded) return { visible: sorted, hidden: 0 }
  return {
    visible: sorted.slice(0, RUNNING_ROWS_LIMIT),
    hidden: Math.max(0, sorted.length - RUNNING_ROWS_LIMIT),
  }
}
