/** 流水线检查 API — /api/v1/workspaces/{wid}/pipelines 与 /pipeline-runs
 *
 * 类型与后端 `pipeline/schemas.py` 对齐；`compiled` 为 DSL 编译快照（`on` / `jobs`），
 * 前端只做只读展示与运行摘要，不在前端复算。
 */

import api from './client'

/** 运行状态（与后端 RUN_STATUS_* 对齐） */
export type PipelineRunStatus = 'pending' | 'running' | 'success' | 'partial' | 'failed' | 'canceled'
/** 触发来源 */
export type PipelineTrigger = 'manual' | 'event' | 'schedule'
/** 发现物严重度 */
export type PipelineSeverity = 'error' | 'warn' | 'info'
/** job / step 结论 */
export type PipelineConclusion = 'success' | 'failed' | 'skipped'

/** 发现物计数（stats.findings） */
export interface PipelineFindingCounts {
  error: number
  warn: number
  info: number
}

/** 运行统计中的单个 step（stats.jobs[].steps[]） */
export interface PipelineStepStat {
  uses: string
  severity: string
  conclusion: string
  findings: number
  error?: string
}

/** 运行统计中的单个 job（stats.jobs[]） */
export interface PipelineJobStat {
  id: string
  conclusion: string
  steps: PipelineStepStat[]
}

/** 运行统计（后端 stats JSON） */
export interface PipelineRunStats {
  jobs_total?: number
  jobs_done?: number
  steps_total?: number
  findings?: Partial<PipelineFindingCounts>
  duration_ms?: number
  jobs?: PipelineJobStat[]
  warnings?: string[]
}

/** 最近一次运行摘要（WorkflowResponse.last_run） */
export interface PipelineRunSummary {
  id: number
  status: PipelineRunStatus
  trigger: PipelineTrigger
  stats: PipelineRunStats
  created_at: string | null
}

/** 流水线定义 */
export interface PipelineWorkflow {
  id: number
  workspace_id: number
  name: string
  content: string
  compiled: {
    name?: string
    on?: { manual?: boolean; events?: string[]; schedule?: string }
    vars?: Record<string, unknown>
    jobs?: Array<{ needs?: string[]; if?: string; steps?: Array<Record<string, unknown>> }>
  }
  enabled: boolean
  created_by_id: number | null
  created_at: string
  updated_at: string
  last_run: PipelineRunSummary | null
}

/** 新建 / 更新载荷 */
export interface PipelineWorkflowPayload {
  name?: string | null
  content?: string
  enabled?: boolean
}

/** 纯编译校验结果 */
export interface PipelineValidateResult {
  ok: boolean
  error: string
  name: string
  job_count: number
  step_count: number
}

/** 检查动作输入项 */
export interface PipelineCheckInput {
  name: string
  type: string
  description: string
  required: boolean
  default: unknown
}

/** 检查动作目录项 */
export interface PipelineCheckSpec {
  uses: string
  title: string
  category: string
  severity: PipelineSeverity
  target_types: string[]
  inputs: PipelineCheckInput[]
}

/** 运行详情 */
export interface PipelineRun {
  id: number
  workflow_id: number
  workspace_id: number
  trigger: PipelineTrigger
  trigger_payload: Record<string, unknown>
  status: PipelineRunStatus
  stats: PipelineRunStats
  error_message: string
  created_at: string
  updated_at: string
  workflow_name: string
}

/** 运行历史分页 */
export interface PipelineRunPage {
  total: number
  items: PipelineRun[]
}

/** 检查发现物 */
export interface PipelineFinding {
  id: number
  run_id: number
  check: string
  severity: PipelineSeverity
  target_type: string
  target_id: number | null
  locator: Record<string, unknown>
  message: string
  detail: Record<string, unknown>
  created_at: string
}

/** 发现物分页 */
export interface PipelineFindingPage {
  total: number
  items: PipelineFinding[]
}

/** 发现物查询参数 */
export interface PipelineFindingQuery {
  severity?: PipelineSeverity
  target_type?: string
  check?: string
  limit?: number
  offset?: number
}

const base = (wid: number | string) => `/v1/workspaces/${wid}/pipelines`
const runsBase = (wid: number | string) => `/v1/workspaces/${wid}/pipeline-runs`

export const pipelinesApi = {
  /** 列出工作区流水线（按更新时间倒序） */
  list: (wid: number | string) =>
    api.get<PipelineWorkflow[]>(base(wid)).then(r => r.data),
  /** 新建（保存期编译校验，DSL 非法返回 400） */
  create: (wid: number | string, data: PipelineWorkflowPayload) =>
    api.post<PipelineWorkflow>(base(wid), data).then(r => r.data),
  /** 纯编译校验（编辑器实时校验用） */
  validate: (wid: number | string, data: { content: string; name?: string | null }) =>
    api.post<PipelineValidateResult>(`${base(wid)}/validate`, data).then(r => r.data),
  /** 检查动作目录 */
  checks: (wid: number | string) =>
    api.get<PipelineCheckSpec[]>(`${base(wid)}/checks`).then(r => r.data),
  /** 定义详情 */
  get: (wid: number | string, workflowId: number | string) =>
    api.get<PipelineWorkflow>(`${base(wid)}/${workflowId}`).then(r => r.data),
  /** 更新（content 变更时重新编译） */
  update: (wid: number | string, workflowId: number | string, data: PipelineWorkflowPayload) =>
    api.put<PipelineWorkflow>(`${base(wid)}/${workflowId}`, data).then(r => r.data),
  /** 删除（级联清理运行与发现物） */
  remove: (wid: number | string, workflowId: number | string) =>
    api.delete<void>(`${base(wid)}/${workflowId}`).then(r => r.data),
  /** 手动触发（202；已有活跃运行时 409） */
  run: (wid: number | string, workflowId: number | string) =>
    api.post<PipelineRun>(`${base(wid)}/${workflowId}/run`).then(r => r.data),
  /** 运行历史 */
  listRuns: (wid: number | string, workflowId: number | string, params?: { limit?: number; offset?: number }) =>
    api.get<PipelineRunPage>(`${base(wid)}/${workflowId}/runs`, { params }).then(r => r.data),
  /** 运行详情 */
  getRun: (wid: number | string, runId: number | string) =>
    api.get<PipelineRun>(`${runsBase(wid)}/${runId}`).then(r => r.data),
  /** 发现物分页（severity / target_type / check 过滤） */
  listFindings: (wid: number | string, runId: number | string, params?: PipelineFindingQuery) =>
    api.get<PipelineFindingPage>(`${runsBase(wid)}/${runId}/findings`, { params }).then(r => r.data),
}
