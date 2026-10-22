/** 个人级「大模型」配置 API — `/api/v1/accounts/llm-config`
 *
 * - 配置按当前登录用户隔离，不依赖工作区、不需要工作区权限；
 * - GET 永不返回 api_key 明文，只回 `has_api_key`；
 * - 连通测试支持携带未保存的 base_url / model / api_key，仅本次请求、不落库。
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

const base = '/v1/accounts/llm-config'

export const llmConfigApi = {
  /** 读取当前登录用户的个人大模型配置 */
  get: () => api.get<LlmConfig>(base).then(r => r.data),
  /** 保存个人大模型配置（api_key 非空才更新；clear_api_key 清除） */
  update: (data: LlmConfigPayload) => api.put<LlmConfig>(base, data).then(r => r.data),
  /** 连通测试：可用未保存的配置直接测，不落库 */
  testConnection: (data: LlmConnectionTestPayload = {}) =>
    api.post<LlmConnectionTestResult>(`${base}/test`, data).then(r => r.data),
}
