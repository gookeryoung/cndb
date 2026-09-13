/** 视图全局用户设置 — localStorage 持久化，适用于所有视图（表格/看板/画廊/日历）. */

/** 内容密度 — 表格映射 antd Table 的 size 属性，看板/画廊/日历用于控制卡片间距.
 *  compact → small, comfortable → middle, spacious → large */
export type Density = 'compact' | 'comfortable' | 'spacious'

export interface TableSettings {
  /** 内容间距密度（适用于所有视图类型） */
  density: Density
  /** 默认每页行数（仅表格视图） */
  defaultPageSize: number
  /** 是否显示表格边框（仅表格视图） */
  bordered: boolean
  /** 是否显示表头（仅表格视图） */
  showHeader: boolean
  /** 是否启用斑马纹（仅表格视图） */
  striped: boolean
}

export const DEFAULT_TABLE_SETTINGS: TableSettings = {
  density: 'comfortable',
  defaultPageSize: 50,
  bordered: false,
  showHeader: true,
  striped: false,
}

const STORAGE_KEY = 'cndb_table_settings'

export function loadTableSettings(): TableSettings {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return { ...DEFAULT_TABLE_SETTINGS }
    const parsed = JSON.parse(raw) as Partial<TableSettings>
    // 合并默认值，确保新增字段有默认
    return { ...DEFAULT_TABLE_SETTINGS, ...parsed }
  } catch {
    return { ...DEFAULT_TABLE_SETTINGS }
  }
}

export function saveTableSettings(settings: TableSettings) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(settings))
  } catch { /* noop: localStorage 不可用时静默失败 */ }
}

/** density → antd Table 的 size 映射. */
export function densityToSize(density: Density): 'small' | 'middle' | 'large' {
  switch (density) {
    case 'compact': return 'small'
    case 'spacious': return 'large'
    default: return 'middle'
  }
}
