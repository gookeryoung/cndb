/** 复用模块可见性展示口径（ADR 0118 + ADR 0153 D8）.
 *
 * - public：公开（跨工作区引用）
 * - team：同团队成员可用（拥有工作区所属团队）
 * - workspace：仅本工作区（历史文案沿用「私有」）
 */
export const LIBRARY_VISIBILITY_META: Record<string, { color: string; text: string }> = {
  public: { color: 'green', text: '公开' },
  team: { color: 'blue', text: '团队' },
  workspace: { color: 'default', text: '私有' },
}
