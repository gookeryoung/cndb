/** 表格弹性填充样式 —— 按列数计算 minWidth，避免窄列被挤压.

从 FileImportPreview.tsx 抽出。
*/

import { useEffect } from 'react'

export function useTableFlexFillStyle() {
  useEffect(() => {
    const id = '__import_preview_table_flex__'
    if (document.getElementById(id)) return
    const style = document.createElement('style')
    style.id = id
    style.textContent = `
      .import-preview-table-wrapper { flex: 1; min-height: 0; overflow: hidden; display: flex; flex-direction: column; }
      .import-preview-table-wrapper .ant-table { flex: 1; min-height: 0; display: flex; flex-direction: column; background: transparent; }
      .import-preview-table-wrapper .ant-table-container { flex: 1; min-height: 0; display: flex; flex-direction: column; }
      .import-preview-table-wrapper .ant-table-content { flex: 1; min-height: 0; overflow: hidden; }
      .import-preview-table-wrapper .ant-table-body { overflow-y: auto !important; flex: 1; min-height: 0; }
      .import-preview-table-wrapper .ant-table-placeholder { height: auto !important; }
    `
    document.head.appendChild(style)
    return () => { /* 保留样式供其他实例复用 */ }
  }, [])
}
