/**
 * 个人设置「大模型」页签测试 —— 个人级连接配置（ADR 0019 个人级迁移）.
 *
 * 覆盖：从个人设置打开「大模型」页签 / 默认值预填 / 内置默认系统提示词展示 /
 * 保存调用个人配置 PUT（含未保存 Key、系统提示词覆盖、清除 Key）/
 * 测试连接使用当前输入与未保存 Key（无需先保存）。
 */

import { describe, expect, it } from 'vitest'
import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import SettingsModal from './SettingsModal'
import { renderProviders } from '@/test/render-providers'
import { server } from '@/test/msw'
import type { LlmConfig } from '@/api'

const DEFAULT_SYSTEM_PROMPT = [
  '你是数据抽取助手，只输出 JSON。',
  '1. 只输出一个 JSON 对象数组或 {"rows": [...]} 包裹；',
  '2. 字段名使用英文 snake_case；',
  '3. 不得编造无法核实的数据。',
].join('\n')

const DEFAULT_CONFIG: LlmConfig = {
  configured: true,
  base_url: 'https://api.deepseek.com',
  model: 'deepseek-chat',
  has_api_key: true,
  system_prompt: '',
  default_system_prompt: DEFAULT_SYSTEM_PROMPT,
}

let putBodies: Array<Record<string, unknown>> = []
let testBodies: Array<Record<string, unknown>> = []

/** 注册个人大模型配置的 msw handlers；PUT 会按请求体回写内存配置 */
function setupHandlers(options: {
  config?: Partial<LlmConfig>
  testResult?: { ok: boolean; latency_ms: number; model: string; message: string }
} = {}) {
  let config: LlmConfig = { ...DEFAULT_CONFIG, ...options.config }
  putBodies = []
  testBodies = []
  server.use(
    http.get('/api/v1/accounts/llm-config', () => HttpResponse.json(config)),
    http.put('/api/v1/accounts/llm-config', async ({ request }) => {
      const body = (await request.json()) as Record<string, unknown>
      putBodies.push(body)
      config = {
        ...config,
        configured: true,
        base_url: (body.base_url as string | undefined) ?? config.base_url,
        model: (body.model as string | undefined) ?? config.model,
        system_prompt: (body.system_prompt as string | undefined) ?? config.system_prompt,
        has_api_key: body.clear_api_key ? false : Boolean(body.api_key) || config.has_api_key,
      }
      return HttpResponse.json(config)
    }),
    http.post('/api/v1/accounts/llm-config/test', async ({ request }) => {
      testBodies.push((await request.json()) as Record<string, unknown>)
      return HttpResponse.json(
        options.testResult ?? { ok: true, latency_ms: 120, model: 'deepseek-chat', message: '连通成功' },
      )
    }),
  )
}

/** 打开个人设置并切到「大模型」页签，等配置加载完成（默认系统提示词出现） */
async function openLlmTab(initialTab?: 'llm') {
  renderProviders(<SettingsModal open initialTab={initialTab} onClose={() => { }} />)
  if (!initialTab) fireEvent.click(screen.getByRole('tab', { name: '大模型' }))
  await waitFor(() =>
    expect(screen.getByTestId('llm-config-default-system')).toHaveTextContent('不得编造无法核实的数据。'),
  )
  return screen.getByTestId('llm-config-panel') as HTMLElement
}

describe('个人设置 · 大模型', () => {
  it('从个人设置打开「大模型」页签：默认值预填、API Key 不回显、展示内置默认系统提示词', async () => {
    setupHandlers()
    await openLlmTab()

    expect(screen.getByTestId('llm-config-base-url')).toHaveValue('https://api.deepseek.com')
    expect(screen.getByTestId('llm-config-model')).toHaveValue('deepseek-chat')
    // API Key 只写不回显：即使已保存也始终为空
    expect(screen.getByTestId('llm-config-api-key')).toHaveValue('')
    expect(screen.getByTestId('llm-config-status')).toHaveTextContent('已配置')
    // 内置默认系统提示词全文展示（多行文本在 DOM 里会做空白归一，按关键片段断言）
    expect(screen.getByTestId('llm-config-default-system')).toHaveTextContent('只输出一个 JSON 对象数组')
    expect(screen.getByTestId('llm-config-default-system')).toHaveTextContent('不得编造无法核实的数据。')
  })

  it('initialTab="llm" 打开时直接定位大模型页签', async () => {
    setupHandlers()
    await openLlmTab('llm')

    expect(screen.getByRole('tab', { name: '大模型' })).toBeInTheDocument()
    expect(screen.getByTestId('llm-config-base-url')).toBeInTheDocument()
  })

  it('保存调用个人配置 PUT：提交当前地址 / 模型 / 未保存 Key / 系统提示词', async () => {
    setupHandlers()
    await openLlmTab()

    fireEvent.change(screen.getByTestId('llm-config-model'), { target: { value: 'deepseek-reasoner' } })
    fireEvent.change(screen.getByTestId('llm-config-api-key'), { target: { value: 'sk-unsaved' } })
    fireEvent.change(screen.getByTestId('llm-config-system'), { target: { value: '自定义系统提示词' } })
    fireEvent.click(screen.getByTestId('llm-config-save'))

    await waitFor(() => expect(putBodies).toHaveLength(1))
    expect(putBodies[0]).toMatchObject({
      base_url: 'https://api.deepseek.com',
      model: 'deepseek-reasoner',
      api_key: 'sk-unsaved',
      system_prompt: '自定义系统提示词',
    })
    expect(await screen.findByText('大模型配置已保存')).toBeInTheDocument()
  })

  it('已保存 Key 时可点「清除」，保存体带 clear_api_key', async () => {
    setupHandlers()
    await openLlmTab()

    fireEvent.click(screen.getByTestId('llm-config-clear-key'))
    fireEvent.click(screen.getByTestId('llm-config-save'))

    await waitFor(() => expect(putBodies).toHaveLength(1))
    expect(putBodies[0]).toMatchObject({ clear_api_key: true })
  })

  it('测试连接使用当前 base_url / model 与未保存的 API Key，无需先保存', async () => {
    setupHandlers()
    await openLlmTab()

    fireEvent.change(screen.getByTestId('llm-config-model'), { target: { value: 'deepseek-reasoner' } })
    fireEvent.change(screen.getByTestId('llm-config-api-key'), { target: { value: 'sk-unsaved' } })
    fireEvent.click(screen.getByTestId('llm-config-test'))

    await waitFor(() => expect(testBodies).toHaveLength(1))
    expect(testBodies[0]).toMatchObject({
      base_url: 'https://api.deepseek.com',
      model: 'deepseek-reasoner',
      api_key: 'sk-unsaved',
    })
    expect(putBodies).toHaveLength(0)
    expect(await screen.findByText('连通成功 · deepseek-chat · 120 ms')).toBeInTheDocument()
  })

  it('未填写 API Key 时测试请求不带 api_key（回退已保存 Key）', async () => {
    setupHandlers()
    await openLlmTab()

    fireEvent.click(screen.getByTestId('llm-config-test'))

    await waitFor(() => expect(testBodies).toHaveLength(1))
    expect(testBodies[0]).not.toHaveProperty('api_key')
  })

  it('连通测试失败展示后端原因', async () => {
    setupHandlers({ testResult: { ok: false, latency_ms: 80, model: '', message: '401 Unauthorized' } })
    await openLlmTab()

    fireEvent.click(screen.getByTestId('llm-config-test'))

    expect(await screen.findByText('连通失败')).toBeInTheDocument()
    expect(screen.getByText('401 Unauthorized')).toBeInTheDocument()
  })

  it('未配置时状态标签提示未配置 API Key', async () => {
    setupHandlers({ config: { configured: false, has_api_key: false } })
    const panel = await openLlmTab()

    expect(within(panel).getByTestId('llm-config-status')).toHaveTextContent('未配置 API Key')
    expect(within(panel).queryByTestId('llm-config-clear-key')).not.toBeInTheDocument()
  })
})
