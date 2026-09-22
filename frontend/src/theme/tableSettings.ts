/** 视图全局用户设置 — localStorage 持久化，适用于所有视图（表格/看板/画廊/日历）. */

/** 内容密度 — 表格映射 antd Table 的 size 属性，看板/画廊/日历用于控制卡片间距.
 *  compact → small, comfortable → middle, spacious → large */
export type Density = 'compact' | 'comfortable' | 'spacious'

/** 新增行默认插入位置.
 *  - top:    表格顶部（作为第一条数据显示）
 *  - tail:   表格尾部（追加到数据源末尾，跨分页）
 *  - page:   页面尾部（追加到当前页末尾） */
export type NewRowPosition = 'top' | 'tail' | 'page'

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
  /** 新增行默认插入位置 */
  newRowPosition: NewRowPosition
  /** 是否锁定自动填充字段（新增行时预填的 default_value / auto_fill 字段只读，提高录入速度） */
  autoFillLocked: boolean
}

export const DEFAULT_TABLE_SETTINGS: TableSettings = {
  density: 'comfortable',
  defaultPageSize: 50,
  bordered: false,
  showHeader: true,
  striped: false,
  newRowPosition: 'tail',
  autoFillLocked: true,
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
