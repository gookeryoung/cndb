/** 分组 / 分类取值 → 稳定颜色.
 *
 * 原先 GanttView 与 CalendarView 各自复制了一份完全相同的「色板 + 字符串 hash」实现，
 * WbsView 又照抄了同一 hash 公式（调色板换成 antd token）。这里收敛成单一实现，
 * 保证「同一个分组值在任何视图里都是同一个颜色」这一约定不会随视图各自漂移。
 */

/** 字符串稳定 hash（各视图历史实现一致：h*31 + charCode，取正 31 位） */
export function stableHash(value: string): number {
  let h = 0
  for (let i = 0; i < value.length; i++) h = (h * 31 + value.charCodeAt(i)) & 0x7fffffff
  return h
}

/** 从调色板按字符串 hash 取色（空串取第一项） */
export function pickPaletteColor<T>(value: string, palette: readonly T[]): T {
  return palette[stableHash(value) % palette.length]
}

/** 默认分组色板（10 色，甘特图与日历视图共用） */
export const GROUP_PALETTE = [
  '#1677ff',
  '#f5222d',
  '#fa8c16',
  '#52c41a',
  '#722ed1',
  '#eb2f96',
  '#13c2c2',
  '#faad14',
  '#2f54eb',
  '#a0d911',
] as const

/** 给分组值分配稳定颜色（基于字符串 hash） */
export function groupColor(value: string): string {
  return pickPaletteColor(value, GROUP_PALETTE)
}
