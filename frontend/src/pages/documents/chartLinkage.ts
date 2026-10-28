/** 双轴模板主次值联动（ADR 0056 D2 / D3）：派生公式唯一入口.
 *
 * - 填次值ᵢ（同比增速）→ 主值ᵢ = 主值ᵢ₋₁ × (1 + 次值ᵢ/100)，与渲染端
 *   `render.py` `growth_at` 留空推算公式互逆；
 * - 改主值ᵢ → 次值ᵢ = round((主值ᵢ/主值ᵢ₋₁ − 1) × 1000) / 10（一位小数，
 *   与渲染端 `render.py` `growth_at` 同一舍入口径；JS Math.round 与 Python
 *   round 在半值边界有差异，属可接受的显示口径）；
 * - 上年基数缺失 / ≤0 时不联动（返回 null，只保留用户当前输入）；
 * - 联动不跨行级联：修改第 i 行只影响第 i 行的配对单元格。
 */

/** 主值一位小数舍入 */
const roundValue = (x: number): number => Math.round(x * 10) / 10

/** 上年基数是否可作为联动基准（类型谓词，收窄 null） */
export function hasBase(prevValue: number | null): prevValue is number {
  return prevValue !== null && Number.isFinite(prevValue) && prevValue > 0
}

/** 填次值联动主值（C3）：主值ᵢ = 主值ᵢ₋₁ × (1 + 次值ᵢ/100)；不可联动返回 null */
export function linkValueFromGrowth(prevValue: number | null, growth: number): number | null {
  if (!hasBase(prevValue) || !Number.isFinite(growth)) return null
  return roundValue(prevValue * (1 + growth / 100))
}

/** 改主值反向重算次值（Q4）：round((主值ᵢ/主值ᵢ₋₁ − 1) × 1000) / 10，与渲染端同一舍入口径；不可联动返回 null */
export function linkGrowthFromValue(value: number, prevValue: number | null): number | null {
  if (!hasBase(prevValue) || !Number.isFinite(value)) return null
  return Math.round((value / prevValue - 1) * 1000) / 10
}

/** 默认联动态显示值（ADR 0059 C2）：次值留空且按主值可推算 → 联动态，显示推算增速值；
 * 推算复用 `linkGrowthFromValue`（与渲染端 `growth_at` 同公式同舍入，I1 单一口径）；
 * 次值已有显式值或推算不可行 → 非联动态，显示原值 */
export function growthLinkedDisplay(
  growth: number | null,
  value: number | null,
  prevValue: number | null,
): { linked: boolean; display: number | null } {
  if (growth !== null) return { linked: false, display: growth }
  const derived = value !== null ? linkGrowthFromValue(value, prevValue) : null
  if (derived === null) return { linked: false, display: null }
  return { linked: true, display: derived }
}
