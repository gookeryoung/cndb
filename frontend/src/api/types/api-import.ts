/** 外部 API 抓取导入（附件 / 抓取 / 分析 / 配置）. */

import type { ID } from './common'
import type { FieldType } from './tables'

export interface AttachmentFile {
  /** 后端 upload 返回的稳定存储键（uuid.ext） */
  file_key: string
  /** 原始文件名 */
  filename: string
  /** 字节数 */
  size?: number
  /** MIME 类型 */
  mime_type?: string
  /** ISO 时间 */
  created_at?: string
}


// ── API 自动建表 / 数据抓取 ────────────────────────

/** API 抓取通用请求体（对齐后端 ApiFetchRequest） */
export interface ApiFetchRequest {
  url: string
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'
  headers?: Record<string, string>
  params?: Record<string, unknown>
  body?: unknown
  data_path?: string | null
  timeout?: number
  /** 响应处理器：json / tencent_stock / 自定义 */
  response_handler?: string
  /** 响应编码，如 utf-8 / gbk */
  encoding?: string
  /** 查询间隔（秒），默认 60，最短 6 */
  query_interval?: number
}

/** 分析接口返回的列元数据（对齐后端 analyze_json_columns 的输出） */
export interface ApiAnalyzeColumn {
  name: string
  field_type: FieldType
  /** 非空样本数 */
  non_null_count?: number
  /** 空值比例 0-1 */
  null_ratio?: number
  /** 样本值（最多几条） */
  samples?: unknown[]
  /** 推测出的选项列表（select 类型） */
  options?: string[]
}

/** POST /{wid}/import-api/analyze 响应 */
export interface ApiAnalyzeResult {
  columns: ApiAnalyzeColumn[]
  total_rows: number
  sample_row_keys: string[]
}

/** POST /{wid}/import-api 响应（建表 + 导入） */
export interface ApiImportResult {
  table_id: ID
  table_name: string
  imported_rows: number
  field_count: number
  columns: ApiAnalyzeColumn[]
}

/** POST /{wid}/tables/{tid}/import-api 响应（追加） */
export interface ApiAppendResult {
  table_id: ID
  appended_rows: number
}

/** POST /{wid}/import-api/config 请求体 */
export interface ApiConfigRequest {
  config_json: string
  stop_on_error?: boolean
}

/** 配置文件校验结果 */
export interface ApiConfigValidateResult {
  valid: boolean
  table_count: number
  tables: Array<{
    table_name: string
    handler: string
    encoding: string
    query_interval: number
    url: string
  }>
}

/** 配置文件批量建表结果 */
export interface ApiConfigImportResult {
  success_count: number
  fail_count: number
  results: Array<{
    table_name: string
    table_id: ID
    imported_rows: number
    field_count: number
    query_interval: number
  }>
  errors: Array<{ table_name: string; error: string }>
  stopped_on_error: boolean
}

// ── 问题清单（issues 插件） ─────────────────────────
