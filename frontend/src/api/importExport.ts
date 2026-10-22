/** 导入导出 API — CSV/文件/API 导入、异步任务、导出下载、附件文件 */

import api from './client'
import type {
  CsvAnalyzeResult, CsvImportResult,
  FileAnalyzeResult, FileImportResult,
  ImportTaskInfo,
  ApiFetchRequest, ApiAnalyzeResult, ApiImportResult, ApiAppendResult,
  ApiConfigValidateResult, ApiConfigImportResult,
  AttachmentFile,
} from './types'

// ─────────────────── AI 动作（ADR 0020 P2）：只生成建议，不修改导入任务 ───────────────────

/** 一条列映射建议：`target` 必为目标表真实字段名（后端已按字段集合过滤） */
export interface ImportAiMappingItem {
  source: string
  target: string
  /** 模型置信度 0~1，可作 tooltip / 标记 */
  confidence: number
  reason: string
}

/** 列映射建议请求：目标表 + 源表头 + 少量抽样行（不含整表数据） */
export interface ImportAiMappingSuggestionPayload {
  target_table_id: number
  headers: string[]
  sample_rows: unknown[][]
  /** 用户已手工确认的映射（源表头 → 目标字段；null 表示跳过） */
  existing_mapping?: Record<string, string | null>
}

/** 列映射建议响应（只读建议，不修改 `ImportTask`；仍需用户确认导入） */
export interface ImportAiMappingSuggestionResponse {
  action: 'import.mapping_suggestion'
  run_id: number
  model: string
  usage: { prompt_tokens: number; completion_tokens: number; total_tokens: number }
  result: {
    mappings: ImportAiMappingItem[]
    /** 模型无法映射的源表头 */
    unmapped: string[]
  }
}

export const importApi = {
  analyzeCsv: (wid: number | string, csvText: string) =>
    api.post<CsvAnalyzeResult>(`/v1/workspaces/${wid}/import-csv/analyze`, { csv_text: csvText }).then(r => r.data),
  createFromCsv: (wid: number | string, tableName: string, csvText: string) =>
    api.post<CsvImportResult>(`/v1/workspaces/${wid}/import-csv`, { table_name: tableName, csv_text: csvText }).then(r => r.data),

  // ── 通用文件导入建表（支持 csv / tsv / json / xlsx） ──
  /** 上传文件 + 分析列类型（不写库）；headerRow 为人工指定的表头行（1-based，可选） */
  analyzeFile: (wid: number | string, file: File, headerRow?: number) => {
    const fd = new FormData()
    fd.append('file', file)
    if (headerRow != null) fd.append('header_row', String(headerRow))
    return api.post<FileAnalyzeResult>(`/v1/workspaces/${wid}/import-file/analyze`, fd, {
      headers: { 'Content-Type': 'multipart/form-data' },
    }).then(r => r.data)
  },
  /** 上传文件 + 自动建表 + 导入数据（tableName 留空则用文件名推断；columnOverrides 为可选字段类型覆盖） */
  createFromFile: (wid: number | string, file: File, tableName?: string, columnOverrides?: Record<string, { field_type: string; options?: string[] }>, headerRow?: number) => {
    const fd = new FormData()
    fd.append('file', file)
    if (tableName) fd.append('table_name', tableName)
    if (columnOverrides) fd.append('column_overrides', JSON.stringify(columnOverrides))
    if (headerRow != null) fd.append('header_row', String(headerRow))
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
  /** 确认导入：把 pending_confirm 任务推进到 running → done；headerRow 为用户选定的表头行（1-based，可选） */
  confirmImport: (
    wid: number | string,
    tid: number | string,
    taskId: number | string,
    matchKeys?: string[],
    unknownColsStrategy?: 'drop' | 'add_text_field',
    droppedColumns?: string[],
    cleaningActions?: Array<{ column?: string | null; action: string; strategy?: string; on_fail?: string }>,
    headerRow?: number,
    columnMapping?: Record<string, string | null>,
  ) =>
    api.post<{ task_id: number; status: string; message: string }>(
      `/v1/workspaces/${wid}/tables/${tid}/import/${taskId}/confirm`,
      // 后端 Body 参数：cleaning_actions 走 JSON body；match_keys / unknown_cols_strategy / dropped_columns / header_row 仍走 query params
      cleaningActions && cleaningActions.length > 0 ? { cleaning_actions: cleaningActions } : {},
      {
        params: {
          ...(matchKeys && matchKeys.length > 0 ? { match_keys: JSON.stringify(matchKeys) } : {}),
          ...(unknownColsStrategy ? { unknown_cols_strategy: unknownColsStrategy } : {}),
          ...(droppedColumns && droppedColumns.length > 0 ? { dropped_columns: JSON.stringify(droppedColumns) } : {}),
          ...(headerRow != null ? { header_row: headerRow } : {}),
          ...(columnMapping && Object.keys(columnMapping).length > 0
            ? { column_mapping: JSON.stringify(columnMapping) }
            : {}),
        },
      }
    ).then(r => r.data),
  /** 重新 analyze — 用户在 preview 阶段改参考列 / 表头行后重算 diff，返回新的 task 状态 */
  reanalyzeImport: (
    wid: number | string,
    tid: number | string,
    taskId: number | string,
    matchKeys?: string[],
    unknownColsStrategy?: 'drop' | 'add_text_field',
    headerRow?: number,
  ) =>
    api.post<ImportTaskInfo>(
      `/v1/workspaces/${wid}/tables/${tid}/import/${taskId}/reanalyze`,
      null,
      {
        params: {
          ...(matchKeys && matchKeys.length > 0 ? { match_keys: JSON.stringify(matchKeys) } : {}),
          ...(unknownColsStrategy && unknownColsStrategy !== 'drop' ? { unknown_cols_strategy: unknownColsStrategy } : {}),
          ...(headerRow != null ? { header_row: headerRow } : {}),
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

  // ── API 抓取（import-api 路由） ──
  /** 抓 API + 分析列类型（不写库） */
  fetchAnalyze: (wid: number | string, payload: ApiFetchRequest) =>
    api.post<ApiAnalyzeResult>(`/v1/workspaces/${wid}/import-api/analyze`, payload).then(r => r.data),
  /** 抓 API + 自动建表 + 导入数据 */
  fetchCreateTable: (wid: number | string, tableName: string, payload: ApiFetchRequest) =>
    api.post<ApiImportResult>(`/v1/workspaces/${wid}/import-api`, { ...payload, table_name: tableName }).then(r => r.data),
  /** 抓 API + 追加数据到已有表 */
  fetchAppend: (wid: number | string, tid: number | string, payload: ApiFetchRequest) =>
    api.post<ApiAppendResult>(`/v1/workspaces/${wid}/tables/${tid}/import-api`, payload).then(r => r.data),

  // ── JSON 配置文件批量建表 ──
  /** 校验 JSON 配置文件（不建表） */
  configValidate: (wid: number | string, configJson: string) =>
    api.post<ApiConfigValidateResult>(`/v1/workspaces/${wid}/import-api/config/validate`, { config_json: configJson }).then(r => r.data),
  /** 从 JSON 配置文件批量建表 */
  configImport: (wid: number | string, configJson: string, stopOnError = true) =>
    api.post<ApiConfigImportResult>(`/v1/workspaces/${wid}/import-api/config`, {
      config_json: configJson,
      stop_on_error: stopOnError,
    }).then(r => r.data),

  /** AI 列映射建议（只读建议：不修改导入任务、不写数据；回填前端映射编辑态后仍需用户确认导入） */
  aiMappingSuggestion: (wid: number | string, payload: ImportAiMappingSuggestionPayload) =>
    api.post<ImportAiMappingSuggestionResponse>(`/v1/workspaces/${wid}/import-file/ai/mapping-suggestion`, payload).then(r => r.data),
}

export const exportApi = {
  /** 导出为 JSON / CSV / XLSX（浏览器直接下载 blob）.
   *
   * 返回完整 AxiosResponse，调用方可通过 response.headers['content-disposition']
   * 解析后端设置的下载文件名；response.data 为 Blob.
   *
   *  @param wid 工作区 ID
   *  @param tid 表 ID
   *  @param format 导出格式
   *  @param viewId 可选的视图 ID，传入后按该视图的筛选条件导出子集
   */
  download: (wid: number | string, tid: number | string, format: 'json' | 'csv' | 'xlsx' = 'json', viewId?: number | string) => {
    const params: Record<string, unknown> = { format }
    if (viewId != null) params.view_id = viewId
    return api.get(`/v1/workspaces/${wid}/tables/${tid}/export`, { params, responseType: 'blob' })
  },
}

export const fileApi = {
  /**
   * 上传单个附件文件.
   *
   * ctx 携带归属上下文（表 + 行 / 文档）：后端据此登记文件归属，
   * 下载与删除时按宿主对象的权限校验（受限表、未发布文档、被行过滤挡掉的行）。
   * 不传则保持"工作区级文件"语义（成员 + 不可猜键）。
   */
  upload: (
    wid: number | string,
    file: File,
    ctx?: {
      tableId?: number | string
      rowId?: number | string
      documentId?: number | string
      /** 归属字段 id：后端据此执行字段级大小 / MIME 校验（图片/附件字段） */
      fieldId?: number | string
    },
    options?: {
      /** 上传进度（0-100）；用于图片字段的瓦片进度环 */
      onProgress?: (percent: number) => void
      /** 取消上传（组件卸载 / 用户点取消时 abort） */
      signal?: AbortSignal
    },
  ) => {
    const fd = new FormData()
    fd.append('file', file)
    if (ctx?.tableId != null) fd.append('table_id', String(ctx.tableId))
    if (ctx?.rowId != null) fd.append('row_id', String(ctx.rowId))
    if (ctx?.documentId != null) fd.append('document_id', String(ctx.documentId))
    if (ctx?.fieldId != null) fd.append('field_id', String(ctx.fieldId))
    return api.post<AttachmentFile>(`/v1/workspaces/${wid}/files`, fd, {
      headers: { 'Content-Type': 'multipart/form-data' },
      signal: options?.signal,
      onUploadProgress: event => {
        if (!options?.onProgress) return
        const total = event.total ?? 0
        options.onProgress(total > 0 ? Math.round((event.loaded / total) * 100) : 0)
      },
    }).then(r => r.data)
  },
  /** 生成附件下载/预览 URL（后端路径 + 查询参数） */
  getUrl: (wid: number | string, fileKey: string, inline = false) =>
    `/api/v1/workspaces/${wid}/files/${encodeURIComponent(fileKey)}${inline ? '?inline=true' : ''}`,
  /** 删除附件（硬清理） */
  remove: (wid: number | string, fileKey: string) =>
    api.delete(`/v1/workspaces/${wid}/files/${encodeURIComponent(fileKey)}`).then(() => true),
}
