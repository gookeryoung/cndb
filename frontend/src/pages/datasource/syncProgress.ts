/** 数据源同步运行中速度展示的格式化工具（ADR 0040 D1/D2）.
 *
 * 速度与已用时间一律由后端按运行记录计算，这里只做展示格式化，
 * 不使用浏览器时钟做差，避免多端时间偏差。
 */

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
