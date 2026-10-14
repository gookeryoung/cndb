/** 表格/视图全局用户设置的类型与默认值.
 *
 * 运行时状态与 localStorage 持久化统一由 `@/store/tableSettings`（zustand persist）负责；
 * 本模块只保留纯类型、默认值与纯函数映射，避免出现第二套读写同一 key 的实现。
 */

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
  /** 新增行默认插入位置 */
  newRowPosition: NewRowPosition
  /** 是否锁定自动填充字段（新增行时预填的 default_value / auto_fill 字段只读，提高录入速度） */
  autoFillLocked: boolean
}

export const DEFAULT_TABLE_SETTINGS: TableSettings = {
  density: 'comfortable',
  defaultPageSize: 50,
  newRowPosition: 'tail',
  autoFillLocked: true,
}

/** density → antd Table 的 size 映射. */
export function densityToSize(density: Density): 'small' | 'middle' | 'large' {
  switch (density) {
    case 'compact': return 'small'
    case 'spacious': return 'large'
    default: return 'middle'
  }
}
