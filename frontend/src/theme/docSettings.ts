/** 文档渲染全局用户设置的类型与默认值.
 *
 * 运行时状态与 localStorage 持久化统一由 `@/store/docSettings`（zustand persist）负责；
 * 本模块只保留纯类型与默认值，避免出现第二套读写同一 key 的实现。
 */

/** 文档内表格/图片的水平对齐方式 */
export type DocAlign = 'left' | 'center'

export interface DocSettings {
  /** 数据表引用（{{table:…}}）的水平对齐方式，默认居中 */
  tableAlign: DocAlign
  /** 图片的水平对齐方式，默认居中 */
  imageAlign: DocAlign
  /** 数据表引用未显式指定 width 参数时的默认宽度（百分比），默认 75 */
  tableDefaultWidth: 50 | 75 | 100
  /** 图片的默认显示宽度（百分比），默认 50 */
  imageDefaultWidth: 50 | 75
}

export const DEFAULT_DOC_SETTINGS: DocSettings = {
  tableAlign: 'center',
  imageAlign: 'center',
  tableDefaultWidth: 75,
  imageDefaultWidth: 50,
}
