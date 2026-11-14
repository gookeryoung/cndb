/** 文档「并排查看」本地偏好：编辑区与渲染预览左右并排（全局单键，跨文档复用）.
 *
 * 默认关闭（保持既有编辑体验）；读取失败 / 存储损坏时同样回退关闭，
 * 偏好问题不应阻断编辑器渲染。
 */
export const SPLIT_PREF_KEY = 'cndb_doc_split_view'

export const DEFAULT_SPLIT_OPEN = false

export function loadSplitOpen(): boolean {
  try {
    return localStorage.getItem(SPLIT_PREF_KEY) === '1'
  } catch {
    return DEFAULT_SPLIT_OPEN
  }
}

export function saveSplitOpen(open: boolean): void {
  try {
    localStorage.setItem(SPLIT_PREF_KEY, open ? '1' : '0')
  } catch {
    /* 隐私模式 / 配额不足：偏好写入失败不影响页面 */
  }
}

/** 并排查看「同步滚动」开关：两栏作为一组跟随滚动（默认启用，可单独关闭） */
export const SPLIT_SYNC_PREF_KEY = 'cndb_doc_split_sync'

export const DEFAULT_SPLIT_SYNC = true

export function loadSplitSync(): boolean {
  try {
    const raw = localStorage.getItem(SPLIT_SYNC_PREF_KEY)
    // 未写过 = 默认启用；只有显式存 '0' 才关闭（脏值回退默认）
    if (raw === '1') return true
    if (raw === '0') return false
    return DEFAULT_SPLIT_SYNC
  } catch {
    return DEFAULT_SPLIT_SYNC
  }
}

export function saveSplitSync(on: boolean): void {
  try {
    localStorage.setItem(SPLIT_SYNC_PREF_KEY, on ? '1' : '0')
  } catch {
    /* 隐私模式 / 配额不足：偏好写入失败不影响页面 */
  }
}
