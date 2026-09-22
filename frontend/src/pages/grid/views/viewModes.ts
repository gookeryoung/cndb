/** 视图模式推导纯函数 — 从 GridPage.tsx 抽出，可独立单元测试.
 *
 * 职责：
 * - ViewMode 类型与合法模式集合（URL/storage 校验共用）
 * - 从数据表 views 列表推导右侧模式按钮组（仅渲染实际拥有的视图类型）
 */

// ── 类型与常量 ────────────────────────────────────────

/** 网格页支持的视图展示模式 */
export type ViewMode = 'grid' | 'kanban' | 'calendar' | 'gantt' | 'wbs'

/** 合法模式集合 —— URL ?mode= 与 localStorage 偏好校验共用 */
export const VALID_MODES: readonly ViewMode[] = ['grid', 'kanban', 'calendar', 'gantt', 'wbs']

// ── 推导函数 ──────────────────────────────────────────

/** 从视图列表收集数据表实际拥有的视图类型集合（grid 作为基础视图始终存在，非法 view_type 被过滤） */
export function collectAvailableViewTypes(views: Array<{ view_type?: string } | null | undefined>): Set<ViewMode> {
  const s = new Set<ViewMode>()
  for (const v of views) {
    const vt = v?.view_type as ViewMode | undefined
    if (vt && VALID_MODES.includes(vt)) s.add(vt)
  }
  // grid 作为基础视图，始终确保存在
  s.add('grid')
  return s
}

/** 推导模式按钮组：仅保留数据表拥有对应视图的按钮；仅剩 grid 一种时整个按钮组隐藏 */
export function deriveModeSwitch<T extends { mode: ViewMode }>(
  views: Array<{ view_type?: string } | null | undefined>,
  allButtons: readonly T[],
): { buttons: T[]; visible: boolean } {
  const available = collectAvailableViewTypes(views)
  const buttons = allButtons.filter((b) => available.has(b.mode))
  return { buttons, visible: buttons.length > 1 }
}
