/** 大模型服务商预设（个人设置 → 大模型，ADR 0019 C2）.
 *
 * 只解决「填什么」：选中服务商自动带出 OpenAI 兼容 `base_url` 与该服务商常用模型，
 * 减少手查地址 / 拼模型名的成本。选中「自定义」则清空地址，回到纯手填。
 *
 * 约定：
 * - `baseUrl` 必须是 OpenAI 兼容端点（项目只支持 `/chat/completions` 协议）；
 * - `models[0]` 是该服务商的默认模型（选中服务商时填入）；
 * - 后端仍以用户保存值为准（`DEFAULT_BASE_URL` / `DEFAULT_MODEL` 见
 *   `src/cndb/plugins/llm/services/connection.py`），本列表不参与后端校验，
 *   新增服务商只需在这里加一条，不改后端。
 */

export interface LlmProviderPreset {
  /** 前端内部标识，不落库 */
  id: string
  label: string
  /** OpenAI 兼容 base_url（不带 /chat/completions） */
  baseUrl: string
  /** 常用模型，首个为默认模型 */
  models: string[]
}

/** 「自定义」选项标识：不预设地址与模型 */
export const CUSTOM_PROVIDER_ID = 'custom'

export const LLM_PROVIDERS: LlmProviderPreset[] = [
  {
    id: 'deepseek',
    label: 'DeepSeek 深度求索',
    baseUrl: 'https://api.deepseek.com',
    models: ['deepseek-chat', 'deepseek-reasoner'],
  },
  {
    id: 'dashscope',
    label: '阿里云百炼（通义千问）',
    baseUrl: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
    models: ['qwen-plus', 'qwen-max', 'qwen-turbo', 'qwen-long'],
  },
  {
    id: 'zhipu',
    label: '智谱 GLM',
    baseUrl: 'https://open.bigmodel.cn/api/paas/v4',
    models: ['glm-4-plus', 'glm-4-air', 'glm-4-flash'],
  },
  {
    id: 'moonshot',
    label: '月之暗面 Kimi',
    baseUrl: 'https://api.moonshot.cn/v1',
    models: ['moonshot-v1-8k', 'moonshot-v1-32k', 'moonshot-v1-128k'],
  },
  {
    id: 'ark',
    label: '火山方舟（豆包）',
    baseUrl: 'https://ark.cn-beijing.volces.com/api/v3',
    models: ['doubao-pro-32k', 'doubao-lite-32k'],
  },
  {
    id: 'siliconflow',
    label: '硅基流动 SiliconFlow',
    baseUrl: 'https://api.siliconflow.cn/v1',
    models: ['deepseek-ai/DeepSeek-V3', 'Qwen/Qwen2.5-72B-Instruct'],
  },
  {
    id: 'openrouter',
    label: 'OpenRouter（聚合）',
    baseUrl: 'https://openrouter.ai/api/v1',
    models: ['deepseek/deepseek-chat', 'openai/gpt-4o-mini', 'anthropic/claude-3.5-sonnet'],
  },
  {
    id: 'openai',
    label: 'OpenAI',
    baseUrl: 'https://api.openai.com/v1',
    models: ['gpt-4o-mini', 'gpt-4o', 'gpt-4.1-mini'],
  },
]

/** 地址归一化：忽略大小写、末尾斜杠与空白，用于反查服务商 */
function normalizeBaseUrl(baseUrl: string): string {
  return (baseUrl ?? '').trim().toLowerCase().replace(/\/+$/, '')
}

/** 按已保存的 base_url 反查服务商；不匹配返回 null（前端展示为「自定义」） */
export function findProviderByBaseUrl(baseUrl: string): LlmProviderPreset | null {
  const target = normalizeBaseUrl(baseUrl)
  if (!target) return null
  return LLM_PROVIDERS.find(provider => normalizeBaseUrl(provider.baseUrl) === target) ?? null
}
