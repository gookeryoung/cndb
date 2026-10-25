/** 数据源同步 API — /api/v1/workspaces/{wid}/datasource/*
 *
 * - providers：可用适配器 + 参数表单描述（Provider 驱动的新建向导）
 * - sync-jobs：任务 CRUD / 立即运行 / 抓取预览 / 运行历史
 *
 * 个人级「大模型」配置（`/api/v1/llm/config`）见 `api/llm.ts`（ADR 0020 P0 迁移）；
 * 工作区级连接端点已删除，本文件不再提供 getLlmConfig / updateLlmConfig / testConnection。
 *
 * 类型内联在本文件（与 analytics 同口径），不再拆 types 子目录。
 */

import api from './client'

/** 调度模式 */
export type SyncScheduleMode = 'manual' | 'daily' | 'interval' | 'cron'
/** 运行状态 */
export type SyncRunStatus = 'running' | 'success' | 'partial' | 'failed'
/** 增量游标策略 */
export type SyncCursorStrategy = 'date' | 'datetime' | 'key_set' | 'backfill_date' | 'none'

/** 适配器参数表单中的一个字段 */
export interface ProviderField {
  name: string
  type: string
  label?: string
  required?: boolean
  default?: unknown
  placeholder?: string
  options?: string[]
  multiple?: boolean
}

export interface ProviderParamsSchema {
  fields?: ProviderField[]
  placeholders?: string[]
  notes?: string
}

export interface DatasourceProviderInfo {
  name: string
  label: string
  params_schema: ProviderParamsSchema
  default_cursor: SyncCursorStrategy
  supports_paging: boolean
}

/** 大模型提示词配置（`llm_prompt` provider） */
export interface SyncPromptConfig {
  /** 系统提示词；留空时后端补「只输出 JSON」约束 */
  system?: string
  /** 用户提示词，可含 {entrant} / {start} / {end} / {today} */
  user_template?: string
}

/** 模型参数（OpenAI 兼容） */
export interface SyncLlmConfig {
  model?: string
  temperature?: number
  max_tokens?: number
  json_mode?: boolean
}

/** 请求声明（与后端 RequestSpec 对齐） */
export interface SyncRequestSpec {
  /** `llm_prompt` 可省略：后端按当前用户的「个人设置 → 大模型」配置补齐 */
  url_template?: string
  method?: string
  headers_template?: Record<string, string>
  params_template?: Record<string, unknown>
  body_template?: unknown
  data_path?: string | null
  /** rows：响应即对象数组；columns：响应是「列名 → 数组」按列拼行；rows_array：数组的数组按位置拼行（ADR 0008/0034） */
  record_mode?: 'rows' | 'columns' | 'rows_array'
  /** 列式 / 行数组映射：{目标列名: 源键或位置索引} */
  record_layout?: Record<string, string | number>
  /** 并发抓取线程数（按标的×窗口分组，组内保持串行；ADR 0034 D5） */
  workers?: number
  /** 数值行过滤（如快照零值行剔除，作用于归一后的目标字段；ADR 0034 D4） */
  row_filter?: { field: string; op: string; value: number }
  /** 行级常量列（值支持 {today} / {entrant} 模板；ADR 0034 D4） */
  row_defaults?: Record<string, string | number>
  encoding?: string
  timeout?: number
  paging?: {
    mode?: 'none' | 'page' | 'offset'
    page_param?: string
    size_param?: string
    page_size?: number
    start_page?: number
    max_pages?: number
  }
  time_window?: {
    mode?: 'none' | 'range'
    start_param?: string
    end_param?: string
    date_format?: string
    chunk_days?: number
  }
  /** `llm_prompt`：提示词 */
  prompt?: SyncPromptConfig
  /** `llm_prompt`：模型参数 */
  llm?: SyncLlmConfig
}

export interface SyncCursorConfig {
  strategy: SyncCursorStrategy
  field?: string
  backfill_start?: string
  value?: string | null
}

export interface SyncScheduleConfig {
  mode: SyncScheduleMode
  at?: string
  seconds?: number
  expr?: string
  tz_offset_minutes?: number
  retry_backoff_seconds?: number
}

/** 字段映射项：null 表示丢弃该字段 */
export type SyncFieldMapping = Record<string, { name?: string; field_type?: string } | string | null>

export interface SyncJob {
  id: number
  workspace_id: number
  name: string
  provider: string
  table_id: number | null
  request_spec: SyncRequestSpec
  parser: string
  entrant_param: string | null
  entrant_keys: string[]
  /** 标的动态来源：从同工作区某表某字段 distinct 取值（ADR 0034 D3） */
  entrant_source?: {
    table: string
    field: string
    prefix_in?: string[]
  } | null
  match_keys: string[]
  field_mapping: SyncFieldMapping
  cursor: SyncCursorConfig
  schedule: SyncScheduleConfig
  enabled: boolean
  last_run_at: string | null
  last_status: string
  /** 凭证会话 id（请求头 + 密钥） */
  session_id?: number | null
  /** 相邻请求最小间隔（毫秒） */
  rate_limit_ms?: number
  created_at: string
  updated_at: string
}

export interface SyncJobPayload {
  name: string
  provider: string
  table_id?: number | null
  request_spec: SyncRequestSpec
  parser?: string
  entrant_param?: string | null
  entrant_keys?: string[]
  /** 标的动态来源（ADR 0034 D3）；编辑既有任务时原样回传以保留声明 */
  entrant_source?: SyncJob['entrant_source']
  match_keys?: string[]
  field_mapping?: SyncFieldMapping
  cursor?: SyncCursorConfig
  schedule?: SyncScheduleConfig
  enabled?: boolean
  session_id?: number | null
  rate_limit_ms?: number
  run_immediately?: boolean
}

/** 凭证会话（密钥只写不回显，列表只返回键名） */
export interface DatasourceSession {
  id: number
  workspace_id: number
  name: string
  headers: Record<string, string>
  secret_keys: string[]
  created_at: string
  updated_at: string
}

export interface DatasourceSessionPayload {
  name: string
  headers?: Record<string, string>
  secrets?: Record<string, string>
}

/** 领域模板包：按 provider 预置的分析配置 */
export interface DomainTemplate {
  id: string
  provider: string
  name: string
  description: string
  reason?: string
  formulas: Array<Record<string, unknown>>
  chart: Record<string, unknown> | null
  summary: Record<string, unknown> | null
}

export interface SyncRun {
  id: number
  job_id: number
  status: SyncRunStatus
  trigger: string
  started_at: string
  finished_at: string | null
  duration_ms: number
  cursor_from: string
  cursor_to: string
  fetched: number
  inserted: number
  updated: number
  skipped: number
  error_message: string
  detail: {
    plans?: number
    succeeded?: number
    failures?: Array<{ label: string; entrant?: string | null; page?: number | null; error: string }>
    normalize_failures?: Array<{ row_index: number; field: string; reason: string }>
    dropped_fields?: number
  }
}

export interface SyncPreviewResult {
  status: SyncRunStatus
  total: number
  columns: string[]
  plans: number
  succeeded: number
  cursor_from: string
  cursor_to: string
  rows: Array<Record<string, unknown>>
  failures: Array<{ label: string; entrant?: string | null; page?: number | null; error: string }>
  normalize_failures: Array<{ row_index: number; field: string; reason: string }>
  /** `llm_prompt`：后端从结果行自动识别的幂等键（用于提示，不落库） */
  suggested_match_keys?: string[]
}

const base = (wid: number | string) => `/v1/workspaces/${wid}/datasource`

export const datasourceApi = {
  providers: (wid: number | string) =>
    api.get<{ providers: DatasourceProviderInfo[] }>(`${base(wid)}/providers`).then(r => r.data.providers),
  listJobs: (wid: number | string) =>
    api.get<{ total: number; jobs: SyncJob[] }>(`${base(wid)}/sync-jobs`).then(r => r.data),
  createJob: (wid: number | string, data: SyncJobPayload) =>
    api.post<SyncJob>(`${base(wid)}/sync-jobs`, data).then(r => r.data),
  updateJob: (wid: number | string, id: number | string, data: Partial<SyncJobPayload>) =>
    api.put<SyncJob>(`${base(wid)}/sync-jobs/${id}`, data).then(r => r.data),
  removeJob: (wid: number | string, id: number | string) =>
    api.delete(`${base(wid)}/sync-jobs/${id}`).then(() => null),
  runJob: (wid: number | string, id: number | string) =>
    api.post<{ job: SyncJob; run: SyncRun }>(`${base(wid)}/sync-jobs/${id}/run`).then(r => r.data),
  previewJob: (wid: number | string, id: number | string, limit = 20) =>
    api.post<SyncPreviewResult>(`${base(wid)}/sync-jobs/${id}/preview`, { limit }).then(r => r.data),
  runs: (wid: number | string, id: number | string, params?: { limit?: number; offset?: number }) =>
    api
      .get<{ total: number; runs: SyncRun[] }>(`${base(wid)}/sync-jobs/${id}/runs`, { params })
      .then(r => r.data),
  sessions: (wid: number | string) =>
    api
      .get<{ total: number; sessions: DatasourceSession[] }>(`${base(wid)}/sessions`)
      .then(r => r.data.sessions),
  createSession: (wid: number | string, data: DatasourceSessionPayload) =>
    api.post<DatasourceSession>(`${base(wid)}/sessions`, data).then(r => r.data),
  updateSession: (wid: number | string, id: number | string, data: Partial<DatasourceSessionPayload>) =>
    api.put<DatasourceSession>(`${base(wid)}/sessions/${id}`, data).then(r => r.data),
  removeSession: (wid: number | string, id: number | string) =>
    api.delete(`${base(wid)}/sessions/${id}`).then(() => null),
  domainTemplates: (wid: number | string, provider?: string) =>
    api
      .get<{ templates: DomainTemplate[] }>(`${base(wid)}/domain-templates`, { params: { provider } })
      .then(r => r.data.templates),
}
