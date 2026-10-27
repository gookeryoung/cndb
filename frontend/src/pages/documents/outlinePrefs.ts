/** 文档大纲栏的本地偏好：展开态与宽度（全局单键，跨文档复用）.
 *
 * 读取失败 / 存储损坏 / 宽度越界时统一回退默认，避免偏好问题阻断文档渲染。
 */

export const OUTLINE_WIDTH_MIN = 180
export const OUTLINE_WIDTH_MAX = 400
export const OUTLINE_WIDTH_DEFAULT = 240
export const OUTLINE_PREFS_KEY = 'cndb_doc_outline'

export interface OutlinePrefs {
  open: boolean
  width: number
}

export const DEFAULT_OUTLINE_PREFS: OutlinePrefs = {
  open: true,
  width: OUTLINE_WIDTH_DEFAULT,
}

/** 宽度唯一收口：非有限数回退默认，其余四舍五入并夹到 [MIN, MAX]. */
export function clampOutlineWidth(width: number): number {
  if (!Number.isFinite(width)) return OUTLINE_WIDTH_DEFAULT
  return Math.min(OUTLINE_WIDTH_MAX, Math.max(OUTLINE_WIDTH_MIN, Math.round(width)))
}

export function loadOutlinePrefs(): OutlinePrefs {
  try {
    const raw = localStorage.getItem(OUTLINE_PREFS_KEY)
    if (!raw) return { ...DEFAULT_OUTLINE_PREFS }
    const parsed: unknown = JSON.parse(raw)
    if (!parsed || typeof parsed !== 'object') return { ...DEFAULT_OUTLINE_PREFS }
    const { open, width } = parsed as { open?: unknown; width?: unknown }
    return {
      open: typeof open === 'boolean' ? open : DEFAULT_OUTLINE_PREFS.open,
      width: typeof width === 'number' ? clampOutlineWidth(width) : DEFAULT_OUTLINE_PREFS.width,
    }
  } catch {
    return { ...DEFAULT_OUTLINE_PREFS }
  }
}

export function saveOutlinePrefs(prefs: OutlinePrefs): void {
  try {
    localStorage.setItem(
      OUTLINE_PREFS_KEY,
      JSON.stringify({ open: prefs.open, width: clampOutlineWidth(prefs.width) }),
    )
  } catch {
    /* 隐私模式 / 配额不足：偏好写入失败不影响页面 */
  }
}
