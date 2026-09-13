/** 数据标签自动配色工具.
 *
 * 配色完全基于 Ant Design v5 官方预设色板（不自行定义任何 HEX）.
 * - 基础预设 13 种（blue/purple/cyan/green/magenta/pink/red/orange/yellow/volcano/geekblue/lime/gold）
 * - inverse 变体 13 种（如 blue-inverse）
 * - status 预设 5 种（success/processing/error/default/warning）
 * 合计 31 种稳定色名；通过字符串 hash 映射，同值同色.
 *
 * 返回的是 antd Tag 组件可直接消费的 color 字符串（Tag 的 color 类型为
 * LiteralUnion<PresetColorType | PresetStatusColorType>）.
 */

/** Ant Design v5 完整预设色名清单（基础 + inverse + status） */
const ANTD_COLOR_NAMES: readonly string[] = [
  // —— 13 种基础预设 ——
  'blue', 'purple', 'cyan', 'green', 'magenta', 'pink', 'red',
  'orange', 'yellow', 'volcano', 'geekblue', 'lime', 'gold',
  // —— 13 种 inverse 变体 ——
  'blue-inverse', 'purple-inverse', 'cyan-inverse', 'green-inverse',
  'magenta-inverse', 'pink-inverse', 'red-inverse',
  'orange-inverse', 'yellow-inverse', 'volcano-inverse',
  'geekblue-inverse', 'lime-inverse', 'gold-inverse',
  // —— 5 种 status 预设 ——
  'success', 'processing', 'error', 'default', 'warning',
]

/** 标签值到颜色索引的缓存，保证同值同色 */
const valueIndexCache = new Map<string, number>()

/** 简单字符串 hash（djb2 变种） */
function hashString(str: string): number {
  let h = 5381
  for (let i = 0; i < str.length; i++) {
    h = ((h << 5) + h) + str.charCodeAt(i)
    h |= 0 // 转有符号 32 位
  }
  return Math.abs(h)
}

/** 根据标签值返回稳定的 Ant Design 预设色名字符串.
 *
 * 直接传给 <Tag color={name}> 即可由 antd 渲染，主题切换自动适配.
 */
export function getTagColorName(value: string | number): string {
  const key = String(value).trim()
  if (!key) return ANTD_COLOR_NAMES[0]!
  let idx = valueIndexCache.get(key)
  if (idx === undefined) {
    idx = hashString(key) % ANTD_COLOR_NAMES.length
    valueIndexCache.set(key, idx)
  }
  return ANTD_COLOR_NAMES[idx]!
}

/** 兼容旧 API — 同 getTagColorName（不再返回 HEX，返回 antd 色名） */
export function getTagColor(value: string | number): string {
  return getTagColorName(value)
}

/** 清空颜色缓存（主要用于测试） */
export function __resetTagColorCache(): void {
  valueIndexCache.clear()
}

/** 导出 antd 预设色名清单供外部校验 */
export { ANTD_COLOR_NAMES }
