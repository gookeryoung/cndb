/** 导入导出 API — CSV/文件导入、异步任务、导出下载、附件文件 */

import api from './client'
import type {
  CsvAnalyzeResult, CsvImportResult,
  FileAnalyzeResult, FileImportResult,
  ImportTaskInfo,
  AttachmentFile,
} from './types'

export const importApi = {
  analyzeCsv: (wid: number | string, csvText: string) =>
    api.post<CsvAnalyzeResult>(`/v1/workspaces/${wid}/import-csv/analyze`, { csv_text: csvText }).then(r => r.data),
  createFromCsv: (wid: number | string, tableName: string, csvText: string) =>
    api.post<CsvImportResult>(`/v1/workspaces/${wid}/import-csv`, { table_name: tableName, csv_text: csvText }).then(r => r.data),

  // ── 通用文件导入建表（支持 csv / tsv / json / xlsx） ──
  /** 上传文件 + 分析列类型（不写库） */
  analyzeFile: (wid: number | string, file: File) => {
    const fd = new FormData()
    fd.append('file', file)
    return api.post<FileAnalyzeResult>(`/v1/workspaces/${wid}/import-file/analyze`, fd, {
      headers: { 'Content-Type': 'multipart/form-data' },
    }).then(r => r.data)
  },
  /** 上传文件 + 自动建表 + 导入数据（tableName 留空则用文件名推断；columnOverrides 为可选字段类型覆盖） */
  createFromFile: (wid: number | string, file: File, tableName?: string, columnOverrides?: Record<string, { field_type: string; options?: string[] }>) => {
    const fd = new FormData()
    fd.append('file', file)
    if (tableName) fd.append('table_name', tableName)
    if (columnOverrides) fd.append('column_overrides', JSON.stringify(columnOverrides))
    return api.post<FileImportResult>(`/v1/workspaces/${wid}/import-file`, fd, {
      headers: { 'Content-Type': 'multipart/form-data' },
    }).then(r => r.data)
  },
  /** 同步导入现有表（文件上传） */
  syncImport: (wid: number | string, tid: number | string, file: File) => {
    const fd = new FormData()
    fd.append('file', file)
    return api.post<{ imported: number; ids: number[] }>(`/v1/workspaces/${wid}/tables/${tid}/import`, fd, {
      headers: { 'Content-Type': 'multipart/form-data' },
    }).then(r => r.data)
  },
  /** 异步导入现有表（文件上传），返回 task_id */
  asyncImport: (wid: number | string, tid: number | string, file: File) => {
    const fd = new FormData()
    fd.append('file', file)
    return api.post<ImportTaskInfo>(`/v1/workspaces/${wid}/tables/${tid}/import/async`, fd, {
      headers: { 'Content-Type': 'multipart/form-data' },
    }).then(r => r.data)
  },
  /** 轮询异步导入任务状态 */
  getTask: (wid: number | string, tid: number | string, taskId: number | string) =>
    api.get<ImportTaskInfo>(`/v1/workspaces/${wid}/tables/${tid}/import/async/${taskId}`).then(r => r.data),

  // ── 预览式导入（两阶段：analyze → confirm） ──
  /** 上传文件仅做解析+校验，返回 task_id（不写库） */
  previewAnalyze: (
    wid: number | string,
    tid: number | string,
    file: File,
    matchKeys?: string[],
    unknownColsStrategy?: 'drop' | 'add_text_field',
    droppedColumns?: string[],
  ) => {
    const fd = new FormData()
    fd.append('file', file)
    if (matchKeys && matchKeys.length > 0) {
      fd.append('match_keys', JSON.stringify(matchKeys))
    }
    if (unknownColsStrategy) {
      fd.append('unknown_cols_strategy', unknownColsStrategy)
    }
    if (droppedColumns && droppedColumns.length > 0) {
      fd.append('dropped_columns', JSON.stringify(droppedColumns))
    }
    return api.post<ImportTaskInfo>(`/v1/workspaces/${wid}/tables/${tid}/import/analyze`, fd, {
      headers: { 'Content-Type': 'multipart/form-data' },
    }).then(r => r.data)
  },
  /** 确认导入：把 pending_confirm 任务推进到 running → done */
  confirmImport: (
    wid: number | string,
    tid: number | string,
    taskId: number | string,
    matchKeys?: string[],
    unknownColsStrategy?: 'drop' | 'add_text_field',
    droppedColumns?: string[],
    cleaningActions?: Array<{ column?: string | null; action: string; strategy?: string; on_fail?: string }>,
  ) =>
    api.post<{ task_id: number; status: string; message: string }>(
      `/v1/workspaces/${wid}/tables/${tid}/import/${taskId}/confirm`,
      // 后端 Body 参数：cleaning_actions 走 JSON body；match_keys / unknown_cols_strategy / dropped_columns 仍走 query params
      cleaningActions && cleaningActions.length > 0 ? { cleaning_actions: cleaningActions } : {},
      {
        params: {
          ...(matchKeys && matchKeys.length > 0 ? { match_keys: JSON.stringify(matchKeys) } : {}),
          ...(unknownColsStrategy ? { unknown_cols_strategy: unknownColsStrategy } : {}),
          ...(droppedColumns && droppedColumns.length > 0 ? { dropped_columns: JSON.stringify(droppedColumns) } : {}),
        },
      }
    ).then(r => r.data),
  /** 重新 analyze — 用户在 preview 阶段改参考列后重算 diff，返回新的 task 状态 */
  reanalyzeImport: (
    wid: number | string,
    tid: number | string,
    taskId: number | string,
    matchKeys?: string[],
    unknownColsStrategy?: 'drop' | 'add_text_field',
  ) =>
    api.post<ImportTaskInfo>(
      `/v1/workspaces/${wid}/tables/${tid}/import/${taskId}/reanalyze`,
      null,
      {
        params: {
          ...(matchKeys && matchKeys.length > 0 ? { match_keys: JSON.stringify(matchKeys) } : {}),
          ...(unknownColsStrategy && unknownColsStrategy !== 'drop' ? { unknown_cols_strategy: unknownColsStrategy } : {}),
        },
      }
    ).then(r => r.data),
  /** 下载失败行文件 */
  downloadFailedRows: async (
    wid: number | string,
    tid: number | string,
    taskId: number | string,
    format: 'csv' | 'xlsx' | 'json' = 'csv',
  ): Promise<Blob> => {
    const resp = await api.get(
      `/v1/workspaces/${wid}/tables/${tid}/import/${taskId}/failed-rows`,
      { params: { format }, responseType: 'blob' }
    )
    return resp.data as unknown as Blob
  },
}

export const exportApi = {
  /** 导出为 JSON / CSV / XLSX（浏览器直接下载 blob）
   *  @param wid 工作区 ID
   *  @param tid 表 ID
   *  @param format 导出格式
   *  @param viewId 可选的视图 ID，传入后按该视图的筛选条件导出子集
   */
  download: (wid: number | string, tid: number | string, format: 'json' | 'csv' | 'xlsx' = 'json', viewId?: number | string) => {
    const params: Record<string, unknown> = { format }
    if (viewId != null) params.view_id = viewId
    return api.get(`/v1/workspaces/${wid}/tables/${tid}/export`, { params, responseType: 'blob' }).then(r => r.data)
  },
}

export const fileApi = {
  /** 上传单个附件文件 */
  upload: (wid: number | string, file: File) => {
    const fd = new FormData()
    fd.append('file', file)
    return api.post<AttachmentFile>(`/v1/workspaces/${wid}/files`, fd, {
      headers: { 'Content-Type': 'multipart/form-data' },
    }).then(r => r.data)
  },
  /** 生成附件下载/预览 URL（后端路径 + 查询参数） */
  getUrl: (wid: number | string, fileKey: string, inline = false) =>
    `/api/v1/workspaces/${wid}/files/${encodeURIComponent(fileKey)}${inline ? '?inline=true' : ''}`,
  /** 删除附件（硬清理） */
  remove: (wid: number | string, fileKey: string) =>
    api.delete(`/v1/workspaces/${wid}/files/${encodeURIComponent(fileKey)}`).then(() => true),
}
