/** 导入预览的类型定义 —— 页面与各子组件共用. */

/** 列分析项（后端 analyze 返回） */
export interface AnalyzeColumn {
  name: string
  field_type: string
  sample_values?: string[]
  null_ratio?: number
  options?: string[]
}

/** 用户编辑的覆盖项 —— 与后端 column_overrides 同结构 */
export interface ColumnOverride {
  field_type: string
  options?: string[]
}
