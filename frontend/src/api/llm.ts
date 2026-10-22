/** 大模型能力平台 API — `/api/v1/llm/*`（ADR 0020 P0）.
 *
 * - 个人配置按当前登录用户隔离，不依赖工作区、不需要工作区权限；
 * - GET 永不返回 api_key 明文，只回 `has_api_key`；
 * - 连通测试支持携带未保存的 base_url / model / api_key，仅本次请求、不落库；
 * - `actions` / `runs` 是能力目录与本人调用留痕的只读入口，前端暂无 UI。
 *
 * UI 入口：个人设置 → 大模型（`frontend/src/pages/settings/LlmConfigPanel.tsx`）。
 */

import api from './client'

/** 当前登录用户的个人大模型配置（api_key 只写不回显） */
export interface LlmConfig {
  /** 是否已完成配置（API 地址 + 模型 + API Key 都可用） */
  configured: boolean
  base_url: string
  model: string
  /** 是否已保存 API Key（值不回显） */
  has_api_key: boolean
  /** 用户自定义系统提示词；留空表示使用内置默认 */
  system_prompt: string
  /** 后端内置默认系统提示词全文（前端只读展示） */
  default_system_prompt: string
}

/** 更新个人大模型配置：字段均可选，api_key 留空表示保持不变 */
export interface LlmConfigPayload {
  base_url?: string
  model?: string
  api_key?: string
  /** 显式清除已保存的 API Key */
  clear_api_key?: boolean
  /** 传空串表示清掉覆盖、回到内置默认系统提示词 */
  system_prompt?: string
}

/** 连通测试请求：字段均可选，未传的字段回退已保存配置 / 内置默认 */
export interface LlmConnectionTestPayload {
  base_url?: string
  model?: string
  /** 未保存的 API Key：仅用于本次连通测试、不落库 */
  api_key?: string
  system_prompt?: string
}

/** 连通测试结果：失败也返回 200，前端按 `ok` 展示 */
export interface LlmConnectionTestResult {
  ok: boolean
  latency_ms: number
  model: string
  message: string
}

/** AI 动作注册表项（只读能力目录项，供前端按能力显隐入口） */
export interface LlmAction {
  /** 动作名，如 `document.polish` / `datasource.llm_prompt` */
  name: string
  /** 前端展示名 */
  label: string
  /** 能力域：document / table / import / analytics / personal */
  scope: string
}

/** 一次 AI 调用记录（用量 / 失败留痕，不存提示词与输出全文） */
export interface LlmRun {
  id: number
  /** 动作名，如 `document.polish` / `datasource.llm_prompt` */
  action: string
  /** 关联工作区；无工作区语义的动作（如平台级测试）为 null */
  workspace_id: number | null
  /** 实际使用的模型 */
  model: string
  status: 'success' | 'failed'
  /** 端到端耗时 */
  latency_ms: number
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
  /** 失败摘要（不含提示词 / 输出全文）；成功时为空串 */
  error: string
  created_at: string
}

/** 本人调用记录分页结果 */
export interface LlmRunPage {
  items: LlmRun[]
  total: number
}

/** 调用记录查询参数（不传时后端按默认分页） */
export interface LlmRunQuery {
  limit?: number
  offset?: number
  /** 按动作名过滤 */
  action?: string
  /** 按状态过滤 */
  status?: 'success' | 'failed'
}

const base = '/v1/llm/config'

export const llmApi = {
  /** 读取当前登录用户的个人大模型配置 */
  get: () => api.get<LlmConfig>(base).then(r => r.data),
  /** 保存个人大模型配置（api_key 非空才更新；clear_api_key 清除） */
  update: (data: LlmConfigPayload) => api.put<LlmConfig>(base, data).then(r => r.data),
  /** 连通测试：可用未保存的配置直接测，不落库 */
  testConnection: (data: LlmConnectionTestPayload = {}) =>
    api.post<LlmConnectionTestResult>(`${base}/test`, data).then(r => r.data),
  /** 列出已注册 AI 动作（只读能力目录，前端暂无 UI） */
  listActions: () => api.get<{ items: LlmAction[] }>('/v1/llm/actions').then(r => r.data),
  /** 查询本人的 AI 调用记录（用量 / 失败留痕） */
  listRuns: (params?: LlmRunQuery) =>
    api.get<LlmRunPage>('/v1/llm/runs', { params }).then(r => r.data),
}
