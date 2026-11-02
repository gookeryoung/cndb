/** 采集策略 API — /api/v1/workspaces/{wid}/acquisition/*（ADR 0085）
 *
 * - channels：渠道目录（可引用的同步任务 + 渠道简写 + provider 元信息）
 * - strategies：四段式规则（scope / filter_rule / targets / iteration）+ 调度
 * - preview：真实抓取 + 筛选，零写入；run：同步执行一次并返回终态
 * - runs：运行历史 / 轮次时间线 / 复核续跑 / 取消 / 失败诊断
 * - rule-drafts：自然语言 → 规则草案（只回草案，不落策略）
 */

import api from './client'

const base = (wid: number | string) => `/v1/workspaces/${wid}/acquisition`

/** 渠道目录中的一条可选渠道 */
export interface AcquisitionChannelOption {
  value: string
  label: string
  kind: 'job' | 'preset' | 'provider'
  provider: string
  requires_key: boolean
  hint: string
}

/** 已注册 provider 的元信息 */
export interface AcquisitionProviderOption {
  name: string
  label: string
  params_schema: Record<string, unknown>
  supports_paging: boolean
}

export interface AcquisitionChannelCatalog {
  channels: AcquisitionChannelOption[]
  providers: AcquisitionProviderOption[]
  llm_actions: string[]
}

/** 规则四段（后端为 JSON，前端只约束常用键） */
export interface AcquisitionScope {
  channels: string[]
  query?: string
  max_results_per_channel?: number
  [key: string]: unknown
}

export interface AcquisitionFilterRule {
  must_have_keywords?: string[]
  optional_keywords?: string[]
  exclude_keywords?: string[]
  authors?: string[]
  institutions?: string[]
  categories?: string[]
  document_types?: string[]
  date_from?: string
  date_to?: string
  min_citations?: number
  require_fulltext?: boolean
  query_boolean?: string
}

export interface AcquisitionIteration {
  max_rounds?: number
  top_keywords_per_round?: number
  expand?: { review?: 'auto' | 'llm' | 'manual' }
  budget?: { max_requests?: number; max_llm_calls?: number }
  [key: string]: unknown
}

export interface AcquisitionTarget {
  kind: 'table' | 'document'
  table_id?: number
  parent_id?: number | null
  match_keys?: string[]
  tags?: string[]
  [key: string]: unknown
}

export interface AcquisitionStrategy {
  id: number
  workspace_id: number
  name: string
  enabled: boolean
  scope: AcquisitionScope
  filter_rule: AcquisitionFilterRule
  targets: AcquisitionTarget[]
  iteration: AcquisitionIteration
  llm: Record<string, unknown>
  schedule: Record<string, unknown>
  rule_version: number
  last_run_at: string | null
  last_status: string
  created_at: string | null
  updated_at: string | null
}

export interface AcquisitionStrategyPayload {
  name: string
  scope: AcquisitionScope
  filter_rule: AcquisitionFilterRule
  targets: AcquisitionTarget[]
  iteration: AcquisitionIteration
  llm?: Record<string, unknown>
  schedule?: Record<string, unknown>
  enabled?: boolean
}

export interface AcquisitionRound {
  id: number
  run_id: number
  round_no: number
  query: string
  channels: unknown[]
  stats: Record<string, unknown>
  new_items: number
  accumulated_items: number
  top_keywords: Array<{ term?: string; source?: string; count?: number; reason?: string; dropped?: boolean }>
  next_query: string
  gap: Record<string, unknown>
  review_state: string
  stop_reason: string
  status: string
  error_message: string
  duration_ms: number
}

export interface AcquisitionRun {
  id: number
  strategy_id: number
  trigger: string
  status: string
  round_count: number
  progress: number
  progress_message: string
  fetched: number
  inserted: number
  updated: number
  skipped: number
  docs_created: number
  docs_updated: number
  docs_skipped: number
  budget_used: Record<string, number>
  error_message: string
  detail: Record<string, unknown>
  started_at: string | null
  finished_at: string | null
  duration_ms: number
}

export interface AcquisitionPreview {
  status: string
  collected: number
  after_dedup: number
  after_filter: number
  by_channel: Record<string, number>
  samples: Array<{ title: string; url: string; published_at: string; match_score: number }>
  channel_errors: Array<{ channel: string; error: string }>
}

export interface AcquisitionRuleDraftResponse {
  draft: {
    scope?: AcquisitionScope
    filter_rule?: AcquisitionFilterRule
    targets?: AcquisitionTarget[]
    iteration?: AcquisitionIteration
    notes?: string
  }
  model: string
  run_id: number | null
  degraded: string
  error: string
}

export interface AcquisitionRuleValidateResponse {
  ok: boolean
  errors: string[]
}

export const acquisitionApi = {
  channels: (wid: number | string) =>
    api.get<AcquisitionChannelCatalog>(`${base(wid)}/channels`).then(r => r.data),

  listStrategies: (wid: number | string) =>
    api.get<{ total: number; strategies: AcquisitionStrategy[] }>(`${base(wid)}/strategies`).then(r => r.data),

  createStrategy: (wid: number | string, data: AcquisitionStrategyPayload) =>
    api.post<AcquisitionStrategy>(`${base(wid)}/strategies`, data).then(r => r.data),

  updateStrategy: (wid: number | string, id: number, data: Partial<AcquisitionStrategyPayload>) =>
    api.put<AcquisitionStrategy>(`${base(wid)}/strategies/${id}`, data).then(r => r.data),

  deleteStrategy: (wid: number | string, id: number) =>
    api.delete(`${base(wid)}/strategies/${id}`).then(() => undefined),

  enableStrategy: (wid: number | string, id: number) =>
    api.post<AcquisitionStrategy>(`${base(wid)}/strategies/${id}/enable`).then(r => r.data),

  disableStrategy: (wid: number | string, id: number) =>
    api.post<AcquisitionStrategy>(`${base(wid)}/strategies/${id}/disable`).then(r => r.data),

  preview: (wid: number | string, id: number, query?: string) =>
    api
      .post<AcquisitionPreview>(`${base(wid)}/strategies/${id}/preview`, query ? { query } : {})
      .then(r => r.data),

  run: (wid: number | string, id: number) =>
    api.post<AcquisitionRun>(`${base(wid)}/strategies/${id}/run`).then(r => r.data),

  runs: (wid: number | string, id: number) =>
    api.get<{ total: number; runs: AcquisitionRun[] }>(`${base(wid)}/strategies/${id}/runs`).then(r => r.data),

  runDetail: (wid: number | string, runId: number) =>
    api
      .get<{ run: AcquisitionRun; rounds: AcquisitionRound[] }>(`${base(wid)}/runs/${runId}`)
      .then(r => r.data),

  resume: (wid: number | string, runId: number, payload: { keywords?: string[]; query?: string }) =>
    api.post<AcquisitionRun>(`${base(wid)}/runs/${runId}/resume`, payload).then(r => r.data),

  cancel: (wid: number | string, runId: number) =>
    api.post<AcquisitionRun>(`${base(wid)}/runs/${runId}/cancel`).then(r => r.data),

  diagnose: (wid: number | string, runId: number) =>
    api
      .post<{ text: string; model: string; run_id: number | null; degraded: string }>(
        `${base(wid)}/runs/${runId}/diagnose`,
      )
      .then(r => r.data),

  ruleDraft: (wid: number | string, payload: { description: string; table_id?: number; parent_id?: number }) =>
    api.post<AcquisitionRuleDraftResponse>(`${base(wid)}/rule-drafts`, payload).then(r => r.data),

  validateRules: (
    wid: number | string,
    payload: {
      scope: AcquisitionScope
      filter_rule: AcquisitionFilterRule
      targets: AcquisitionTarget[]
      iteration: AcquisitionIteration
    },
  ) => api.post<AcquisitionRuleValidateResponse>(`${base(wid)}/rules/validate`, payload).then(r => r.data),
}
