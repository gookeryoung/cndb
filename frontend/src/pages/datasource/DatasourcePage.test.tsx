/** DatasourcePage 集成测试 —— 列表渲染 / 空态 / 新建抽屉 / 立即运行 / 运行历史. */

import { describe, expect, it } from 'vitest'
import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { Route, Routes } from 'react-router-dom'
import DatasourcePage from './DatasourcePage'
import { LLM_PROMPT_PRESETS } from './llmPromptPresets'
import { renderProviders } from '@/test/render-providers'
import { server } from '@/test/msw'
import type { LlmConfig, SyncJob } from '@/api'

const WID = 1

const DEFAULT_LLM_CONFIG: LlmConfig = {
  configured: true,
  base_url: 'https://api.deepseek.com',
  model: 'deepseek-chat',
  has_api_key: true,
  system_prompt: '',
  default_system_prompt: '你是数据抽取助手，只输出 JSON，不要输出 Markdown 代码围栏或解释文字。',
}

const PROVIDERS = [
  {
    name: 'http_json',
    label: '通用 HTTP/JSON',
    params_schema: { fields: [], placeholders: ['entrant', 'start', 'end'] },
    default_cursor: 'date',
    supports_paging: true,
  },
  {
    name: 'rss_atom',
    label: 'RSS / Atom 订阅',
    params_schema: { fields: [], placeholders: [] },
    default_cursor: 'datetime',
    supports_paging: false,
  },
  {
    name: 'llm_prompt',
    label: '大模型提示词',
    params_schema: {
      fields: [
        { name: 'url_template', type: 'text', required: true, label: 'API 地址' },
        { name: 'model', type: 'text', required: true, label: '模型' },
        { name: 'temperature', type: 'number', default: 0.2 },
        { name: 'max_tokens', type: 'number', default: 1024 },
        { name: 'json_mode', type: 'boolean', default: true },
      ],
      placeholders: ['entrant', 'start', 'end', 'today'],
    },
    default_cursor: 'none',
    supports_paging: false,
  },
]

function makeJob(overrides: Partial<SyncJob> = {}): SyncJob {
  return {
    id: 3,
    workspace_id: WID,
    name: '北京天气日报',
    provider: 'http_json',
    table_id: 20,
    request_spec: { url_template: 'https://api.example.com/w?city={city}', paging: { mode: 'none' } },
    parser: 'json',
    entrant_param: 'city',
    entrant_keys: ['北京'],
    match_keys: ['city', 'day'],
    field_mapping: {},
    cursor: { strategy: 'date', field: 'day', backfill_start: '2024-01-01' },
    schedule: { mode: 'daily', at: '07:00' },
    enabled: true,
    last_run_at: '2026-10-20T01:00:00Z',
    last_status: 'success',
    created_at: '2026-10-19T00:00:00Z',
    updated_at: '2026-10-20T01:00:00Z',
    ...overrides,
  }
}

const TABLES = [{ id: 20, name: '天气日表' }]

let sessionBodies: Array<Record<string, unknown>> = []
let templateBodies: Array<Record<string, unknown>> = []
let jobBodies: Array<Record<string, unknown>> = []
let connectionBodies: Array<Record<string, unknown>> = []
let llmConfigBodies: Array<Record<string, unknown>> = []

function setupHandlers(
  jobs: SyncJob[],
  options: {
    runStatus?: 'success' | 'failed'
    createTemplateError?: string
    connectionResult?: { ok: boolean; latency_ms: number; model: string; message: string }
    llmConfig?: Partial<LlmConfig>
    previewResult?: Record<string, unknown>
  } = {},
) {
  const calls: string[] = []
  sessionBodies = []
  templateBodies = []
  jobBodies = []
  connectionBodies = []
  llmConfigBodies = []
  const llmConfig: LlmConfig = { ...DEFAULT_LLM_CONFIG, ...options.llmConfig }
  server.use(
    http.get(`/api/v1/workspaces/${WID}/datasource/providers`, () => HttpResponse.json({ providers: PROVIDERS })),
    http.get(`/api/v1/workspaces/${WID}/datasource/sync-jobs`, () =>
      HttpResponse.json({ total: jobs.length, jobs }),
    ),
    http.get(`/api/v1/workspaces/${WID}/datasource/llm-config`, () => HttpResponse.json(llmConfig)),
    http.put(`/api/v1/workspaces/${WID}/datasource/llm-config`, async ({ request }) => {
      calls.push('update-llm-config')
      const body = (await request.json()) as Record<string, unknown>
      llmConfigBodies.push(body)
      return HttpResponse.json({
        ...llmConfig,
        configured: true,
        has_api_key: true,
        base_url: (body.base_url as string | undefined) ?? llmConfig.base_url,
        model: (body.model as string | undefined) ?? llmConfig.model,
        system_prompt: (body.system_prompt as string | undefined) ?? llmConfig.system_prompt,
      })
    }),
    http.post(`/api/v1/workspaces/${WID}/datasource/sync-jobs/:id/preview`, () => {
      calls.push('preview')
      return HttpResponse.json(
        options.previewResult ?? {
          status: 'success',
          total: 1,
          columns: ['date', 'city', 'weather'],
          plans: 1,
          succeeded: 1,
          cursor_from: '',
          cursor_to: '',
          rows: [{ date: '2026-10-22', city: '北京', weather: '晴' }],
          failures: [],
          normalize_failures: [],
          suggested_match_keys: ['date', 'city'],
        },
      )
    }),
    http.post(`/api/v1/workspaces/${WID}/datasource/sync-jobs`, async ({ request }) => {
      calls.push('create-job')
      const body = (await request.json()) as Record<string, unknown>
      jobBodies.push(body)
      return HttpResponse.json({ ...makeJob(), id: 31, ...body })
    }),
    http.put(`/api/v1/workspaces/${WID}/datasource/sync-jobs/:id`, async ({ request, params }) => {
      calls.push('update-job')
      const body = (await request.json()) as Record<string, unknown>
      jobBodies.push(body)
      return HttpResponse.json({ ...jobs[0], id: Number(params.id), ...body })
    }),
    http.post(`/api/v1/workspaces/${WID}/datasource/test-connection`, async ({ request }) => {
      calls.push('test-connection')
      connectionBodies.push((await request.json()) as Record<string, unknown>)
      return HttpResponse.json(
        options.connectionResult ?? { ok: true, latency_ms: 120, model: 'deepseek-chat', message: '连通成功' },
      )
    }),
    http.get(`/api/v1/workspaces/${WID}/tables`, () => HttpResponse.json(TABLES)),
    http.get(`/api/v1/workspaces/${WID}/datasource/sessions`, () =>
      HttpResponse.json({
        total: 1,
        sessions: [
          {
            id: 5,
            workspace_id: WID,
            name: '行情源 A',
            headers: { 'User-Agent': 'cndb' },
            secret_keys: ['api_key'],
            created_at: '2026-10-20T00:00:00Z',
            updated_at: '2026-10-20T00:00:00Z',
          },
        ],
      }),
    ),
    http.put(`/api/v1/workspaces/${WID}/datasource/sessions/:id`, async ({ request }) => {
      calls.push('update-session')
      sessionBodies.push((await request.json()) as Record<string, unknown>)
      return HttpResponse.json({
        id: 5,
        workspace_id: WID,
        name: '行情源 A（改）',
        headers: {},
        secret_keys: ['api_key'],
        created_at: '2026-10-20T00:00:00Z',
        updated_at: '2026-10-20T00:00:00Z',
      })
    }),
    http.delete(`/api/v1/workspaces/${WID}/datasource/sessions/:id`, () => {
      calls.push('delete-session')
      return new HttpResponse(null, { status: 204 })
    }),
    http.get(`/api/v1/workspaces/${WID}/datasource/domain-templates`, () =>
      HttpResponse.json({
        templates: [
          {
            id: 'kline_trend',
            provider: 'http_json',
            name: '股票日线趋势',
            description: '收盘价 + 均线',
            reason: '时序首选',
            formulas: [
              {
                key: 'ma5',
                label: '5日均线',
                expr: 'round(ma([close], 5), 2)',
                partition_by: 'symbol',
                order_by: 'trade_date',
              },
            ],
            chart: { type: 'line', x: 'trade_date', y: 'close', series: 'symbol', title: '趋势', aggregation: 'avg' },
            summary: null,
          },
        ],
      }),
    ),
    http.post(`/api/v1/workspaces/${WID}/analytics/templates`, async ({ request }) => {
      calls.push('create-template')
      const body = (await request.json()) as { name: string }
      templateBodies.push(body as Record<string, unknown>)
      if (options.createTemplateError) {
        return HttpResponse.json({ detail: options.createTemplateError }, { status: 400 })
      }
      return HttpResponse.json({
        id: 99,
        workspace_id: WID,
        table_id: 20,
        name: body.name,
        description: '',
        config: { formulas: [], chart: null, summary: null, fields: [], limit: 1000 },
        updated_at: '2026-10-20T00:00:00Z',
      })
    }),
    http.post(`/api/v1/workspaces/${WID}/datasource/sync-jobs/:id/run`, ({ params }) => {
      calls.push(`run:${params.id}`)
      const job = jobs[0]
      return HttpResponse.json({
        job,
        run: {
          id: 11,
          job_id: job.id,
          status: options.runStatus ?? 'success',
          trigger: 'manual',
          started_at: '2026-10-20T02:00:00Z',
          finished_at: '2026-10-20T02:00:01Z',
          duration_ms: 1000,
          cursor_from: '2024-01-01',
          cursor_to: '2026-10-20',
          fetched: 2,
          inserted: 2,
          updated: 0,
          skipped: 0,
          error_message: options.runStatus === 'failed' ? '源故障' : '',
          detail: {},
        },
      })
    }),
    http.get(`/api/v1/workspaces/${WID}/datasource/sync-jobs/:id/runs`, () =>
      HttpResponse.json({
        total: 1,
        runs: [
          {
            id: 11,
            job_id: 3,
            status: 'success',
            trigger: 'manual',
            started_at: '2026-10-20T02:00:00Z',
            finished_at: '2026-10-20T02:00:01Z',
            duration_ms: 1000,
            cursor_from: '2024-01-01',
            cursor_to: '2026-10-20',
            fetched: 2,
            inserted: 2,
            updated: 0,
            skipped: 0,
            error_message: '',
            detail: {},
          },
        ],
      }),
    ),
  )
  return calls
}

function renderPage() {
  return renderProviders(
    <Routes>
      <Route path="/w/:wid/datasource" element={<DatasourcePage />} />
    </Routes>,
    { route: `/w/${WID}/datasource` },
  )
}

describe('DatasourcePage', () => {
  it('渲染任务列表：名称 / 适配器 / 目标表 / 调度 / 上次状态', async () => {
    setupHandlers([makeJob()])
    renderPage()

    expect(await screen.findByText('北京天气日报')).toBeInTheDocument()
    expect(screen.getByText('通用 HTTP/JSON')).toBeInTheDocument()
    expect(screen.getByText('天气日表')).toBeInTheDocument()
    expect(screen.getByText('每天 07:00')).toBeInTheDocument()
    expect(screen.getByText('成功')).toBeInTheDocument()
  })

  it('停用任务显示「已停用」标签', async () => {
    setupHandlers([makeJob({ enabled: false, last_status: '' })])
    renderPage()
    expect(await screen.findByText('已停用')).toBeInTheDocument()
    expect(screen.getByText('未运行')).toBeInTheDocument()
  })

  it('空列表显示引导文案', async () => {
    setupHandlers([])
    renderPage()
    expect(await screen.findByText('还没有同步任务')).toBeInTheDocument()
  })

  it('点击「新建同步任务」打开抽屉', async () => {
    setupHandlers([makeJob()])
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: /新建同步任务/ }))
    expect(await screen.findByText('新建同步任务', { selector: '.ant-drawer-title' })).toBeInTheDocument()
  })

  it('点击「编辑」打开抽屉并回填名称', async () => {
    setupHandlers([makeJob()])
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: '编辑 北京天气日报' }))
    expect(await screen.findByText(/编辑同步任务 · 北京天气日报/)).toBeInTheDocument()
  })

  it('立即运行调用接口并提示结果', async () => {
    const calls = setupHandlers([makeJob()])
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: '立即运行 北京天气日报' }))
    await waitFor(() => expect(calls).toContain('run:3'))
    expect(await screen.findByText(/新增 2 \/ 更新 0/)).toBeInTheDocument()
  })

  it('运行失败时提示错误原因', async () => {
    setupHandlers([makeJob()], { runStatus: 'failed' })
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: '立即运行 北京天气日报' }))
    expect(await screen.findByText(/同步失败：源故障/)).toBeInTheDocument()
  })

  it('打开运行历史抽屉', async () => {
    setupHandlers([makeJob()])
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: '运行历史 北京天气日报' }))
    expect(await screen.findByText(/运行历史 · 北京天气日报/)).toBeInTheDocument()
  })
})

describe('DatasourcePage · 凭证会话与领域模板', () => {
  it('编辑抽屉显示凭证会话与请求间隔', async () => {
    setupHandlers([makeJob()])
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: '编辑 北京天气日报' }))
    const drawer = screen.getByText(/编辑同步任务 · 北京天气日报/).closest('.ant-drawer-content') as HTMLElement
    expect(within(drawer).getByText('凭证会话')).toBeInTheDocument()
    expect(within(drawer).getByText('请求间隔（毫秒）')).toBeInTheDocument()
  })

  it('会话管理：列表展示已有会话，可进入新建表单', async () => {
    setupHandlers([makeJob()])
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: '编辑 北京天气日报' }))
    fireEvent.click(screen.getByTestId('datasource-session-create'))

    // 列表态：已有会话 + 密钥键名（值不回显）
    const table = await screen.findByTestId('datasource-sessions-table')
    expect(within(table).getByText('行情源 A')).toBeInTheDocument()
    expect(within(table).getByText('api_key')).toBeInTheDocument()

    fireEvent.click(screen.getByTestId('datasource-session-new'))
    expect(await screen.findByTestId('datasource-session-name')).toBeInTheDocument()
  })

  it('编辑会话：密钥留空时请求体不带 secrets（不误清空）', async () => {
    const calls = setupHandlers([makeJob()])
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: '编辑 北京天气日报' }))
    fireEvent.click(screen.getByTestId('datasource-session-create'))

    fireEvent.click(await screen.findByRole('button', { name: '编辑会话 行情源 A' }))
    // 名称回填、密钥留空
    expect(await screen.findByTestId('datasource-session-name')).toHaveValue('行情源 A')
    expect(screen.getByTestId('datasource-session-secrets')).toHaveValue('')

    fireEvent.change(screen.getByTestId('datasource-session-name'), { target: { value: '行情源 A（改）' } })
    fireEvent.click(screen.getByTestId('datasource-session-save'))

    await waitFor(() => expect(calls).toContain('update-session'))
    expect(sessionBodies[0].name).toBe('行情源 A（改）')
    expect('secrets' in sessionBodies[0]).toBe(false)
  })

  it('编辑会话：填写密钥时整体替换', async () => {
    const calls = setupHandlers([makeJob()])
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: '编辑 北京天气日报' }))
    fireEvent.click(screen.getByTestId('datasource-session-create'))
    fireEvent.click(await screen.findByRole('button', { name: '编辑会话 行情源 A' }))

    fireEvent.change(await screen.findByTestId('datasource-session-secrets'), {
      target: { value: '{"api_key":"new"}' },
    })
    fireEvent.click(screen.getByTestId('datasource-session-save'))

    await waitFor(() => expect(calls).toContain('update-session'))
    expect(sessionBodies[0].secrets).toEqual({ api_key: 'new' })
  })

  it('删除会话：确认后调用删除接口并提示会解绑任务', async () => {
    const calls = setupHandlers([makeJob()])
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: '编辑 北京天气日报' }))
    fireEvent.click(screen.getByTestId('datasource-session-create'))

    fireEvent.click(await screen.findByRole('button', { name: '删除会话 行情源 A' }))
    // 页面本身已有 Modal：按文案找到 confirm 那个 dialog，再点它的确认按钮
    const confirm = await waitFor(() => {
      const found = screen.getAllByRole('dialog').find(item => item.textContent?.includes('会自动解绑'))
      expect(found).toBeTruthy()
      return found as HTMLElement
    })
    const buttons = within(confirm).getAllByRole('button')
    fireEvent.click(buttons[buttons.length - 1])

    await waitFor(() => expect(calls).toContain('delete-session'))
    expect(await screen.findByText('会话已删除')).toBeInTheDocument()
  })

  it('套用领域分析模板调用 analytics 建模板接口', async () => {
    const calls = setupHandlers([makeJob()])
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: '套用分析模板 北京天气日报' }))
    fireEvent.click(await screen.findByText('股票日线趋势'))
    await waitFor(() => expect(calls).toContain('create-template'))
    expect(await screen.findByText(/已创建分析模板/)).toBeInTheDocument()
  })

  it('套用模板时按任务字段映射翻译成目标字段名', async () => {
    const calls = setupHandlers([
      makeJob({ field_mapping: { close: { name: '收盘价' }, trade_date: '交易日', symbol: { name: '代码' } } }),
    ])
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: '套用分析模板 北京天气日报' }))
    fireEvent.click(await screen.findByText('股票日线趋势'))
    await waitFor(() => expect(calls).toContain('create-template'))

    const config = templateBodies[0].config as {
      formulas: Array<Record<string, unknown>>
      chart: Record<string, unknown>
    }
    expect(config.formulas[0]).toMatchObject({
      expr: 'round(ma([收盘价], 5), 2)',
      partition_by: '代码',
      order_by: '交易日',
    })
    expect(config.chart).toMatchObject({ x: '交易日', y: '收盘价', series: '代码' })
  })

  it('套用失败时展示后端校验原因，不猜字段映射', async () => {
    setupHandlers([makeJob()], { createTemplateError: '公式 ma5 引用了不存在的字段: close' })
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: '套用分析模板 北京天气日报' }))
    fireEvent.click(await screen.findByText('股票日线趋势'))
    expect(await screen.findByText(/套用失败：公式 ma5 引用了不存在的字段: close/)).toBeInTheDocument()
  })
})

function makeLlmJob(overrides: Partial<SyncJob> = {}): SyncJob {
  return makeJob({
    name: '模型日报',
    provider: 'llm_prompt',
    request_spec: {
      url_template: 'https://api.deepseek.com',
      prompt: { system: '你是数据抽取助手', user_template: '请生成 {today} 的天气摘要，地区：{entrant}' },
      llm: { model: 'deepseek-chat', temperature: 0.2, max_tokens: 1024, json_mode: true },
      time_window: { mode: 'none' },
    },
    entrant_param: null,
    entrant_keys: [],
    cursor: { strategy: 'none' },
    match_keys: ['day'],
    ...overrides,
  })
}

describe('DatasourcePage · 大模型提示词', () => {
  it('页头展示「大模型连接」按钮与已配置标签', async () => {
    setupHandlers([makeLlmJob()])
    renderPage()
    expect(screen.getByRole('button', { name: /大模型连接/ })).toBeInTheDocument()
    await waitFor(() => expect(screen.getByTestId('datasource-llm-config-tag')).toHaveTextContent('已配置'))
  })

  it('未配置大模型连接时页头标签为「未配置」', async () => {
    setupHandlers([makeLlmJob()], { llmConfig: { configured: false, has_api_key: false } })
    renderPage()
    await waitFor(() => expect(screen.getByTestId('datasource-llm-config-tag')).toHaveTextContent('未配置'))
  })

  it('极简表单只保留提示词相关项，系统提示词收进高级设置', async () => {
    setupHandlers([makeLlmJob()])
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: '编辑 模型日报' }))

    const userInput = await screen.findByTestId('datasource-llm-user')
    const drawer = userInput.closest('.ant-drawer-content') as HTMLElement
    expect(userInput).toHaveValue('请生成 {today} 的天气摘要，地区：{entrant}')
    expect(within(drawer).getByText('用户提示词')).toBeInTheDocument()
    expect(within(drawer).getByText('目标表（留空则按任务名自动建表）')).toBeInTheDocument()
    // API 地址 / 模型来自工作区连接，不再逐任务填写
    expect(within(drawer).queryByText('API 地址')).not.toBeInTheDocument()
    expect(within(drawer).queryByTestId('datasource-llm-model')).not.toBeInTheDocument()
    expect(within(drawer).queryByText('响应数组路径')).not.toBeInTheDocument()
    // 高级设置默认收起：系统提示词输入框未挂载
    expect(within(drawer).getByText(/高级设置/)).toBeInTheDocument()
    expect(within(drawer).queryByTestId('datasource-llm-system')).not.toBeInTheDocument()
  })

  it('高级设置展开后可覆盖系统提示词', async () => {
    setupHandlers([makeLlmJob()])
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: '编辑 模型日报' }))
    fireEvent.click(await screen.findByText(/高级设置/))
    expect(await screen.findByTestId('datasource-llm-system')).toHaveValue('你是数据抽取助手')
  })

  it('推荐提示词（8 组）可一键填入并显示建议字段 / 幂等键', async () => {
    setupHandlers([makeLlmJob()])
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: '编辑 模型日报' }))
    fireEvent.click(await screen.findByTestId('datasource-llm-presets-btn'))

    const card = await screen.findByTestId('datasource-llm-preset-daily_news')
    const modal = card.closest('.ant-modal-content') as HTMLElement
    expect(within(modal).getAllByTestId(/^datasource-llm-preset-/)).toHaveLength(LLM_PROMPT_PRESETS.length)
    for (const preset of LLM_PROMPT_PRESETS) {
      expect(within(modal).getByText(preset.name)).toBeInTheDocument()
    }

    // antd 会在两个汉字的按钮文案里插入空格（「使 用」），这里只按唯一按钮定位
    fireEvent.click(within(card).getByRole('button'))
    expect(await screen.findByTestId('datasource-llm-user')).toHaveValue(LLM_PROMPT_PRESETS[0].prompt)
    expect(await screen.findByTestId('datasource-llm-preset-hint')).toHaveTextContent(
      '建议幂等键：date、category、title',
    )
  })

  it('保存时 request_spec 不带 url_template / model，只提交提示词', async () => {
    const calls = setupHandlers([makeLlmJob()])
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: '编辑 模型日报' }))
    fireEvent.change(await screen.findByTestId('datasource-llm-user'), {
      target: { value: '请生成 {today} 的行业政策摘要，只输出 JSON 对象数组' },
    })
    fireEvent.click(screen.getByTestId('datasource-save-btn'))

    await waitFor(() => expect(calls).toContain('update-job'))
    const spec = jobBodies[0].request_spec as Record<string, unknown>
    expect(spec.prompt).toMatchObject({
      user_template: '请生成 {today} 的行业政策摘要，只输出 JSON 对象数组',
      system: '你是数据抽取助手',
    })
    expect(spec).not.toHaveProperty('url_template')
    expect(spec).not.toHaveProperty('llm')
    expect(spec).not.toHaveProperty('paging')
    expect(spec).not.toHaveProperty('data_path')
  })

  it('未配置大模型连接时保存先引导去配置，不发保存请求', async () => {
    const calls = setupHandlers([makeLlmJob()], { llmConfig: { configured: false, has_api_key: false } })
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: '编辑 模型日报' }))
    expect(await screen.findByTestId('datasource-llm-unconfigured')).toBeInTheDocument()

    fireEvent.click(screen.getByTestId('datasource-save-btn'))
    expect(
      await screen.findByText('请先配置工作区的大模型连接（API 地址 / 模型 / API Key）'),
    ).toBeInTheDocument()
    expect(calls).not.toContain('update-job')
    // 同时打开连接弹窗，方便直接配置
    expect(await screen.findByTestId('datasource-llm-config-base-url')).toBeInTheDocument()
  })

  it('保存并预览展示后端自动识别的幂等键', async () => {
    const calls = setupHandlers([makeLlmJob()])
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: '编辑 模型日报' }))
    fireEvent.click(await screen.findByTestId('datasource-save-preview-btn'))

    await waitFor(() => expect(calls).toContain('preview'))
    expect(await screen.findByText('自动识别幂等键：date, city')).toBeInTheDocument()
    // 预览时抽屉保持打开（便于对照建议幂等键）
    expect(screen.getByTestId('datasource-llm-user')).toBeInTheDocument()
  })

  it('连接弹窗预填默认值、展示内置默认系统提示词并可保存', async () => {
    const calls = setupHandlers([makeLlmJob()])
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: /大模型连接/ }))

    const baseUrl = await screen.findByTestId('datasource-llm-config-base-url')
    const modal = baseUrl.closest('.ant-modal-content') as HTMLElement
    expect(baseUrl).toHaveValue('https://api.deepseek.com')
    expect(within(modal).getByTestId('datasource-llm-config-model')).toHaveValue('deepseek-chat')
    // API Key 只写不回显
    expect(within(modal).getByTestId('datasource-llm-config-api-key')).toHaveValue('')
    expect(within(modal).getByTestId('datasource-llm-default-system')).toHaveTextContent(
      '你是数据抽取助手，只输出 JSON，不要输出 Markdown 代码围栏或解释文字。',
    )

    fireEvent.change(within(modal).getByTestId('datasource-llm-config-model'), {
      target: { value: 'deepseek-reasoner' },
    })
    fireEvent.change(within(modal).getByTestId('datasource-llm-config-api-key'), {
      target: { value: 'sk-test' },
    })
    fireEvent.click(within(modal).getByTestId('datasource-llm-config-save'))

    await waitFor(() => expect(calls).toContain('update-llm-config'))
    expect(llmConfigBodies[0]).toMatchObject({
      base_url: 'https://api.deepseek.com',
      model: 'deepseek-reasoner',
      api_key: 'sk-test',
      system_prompt: '',
    })
    expect(await screen.findByText('大模型连接已保存')).toBeInTheDocument()
  })

  it('连接弹窗的连通测试用当前 base_url / model', async () => {
    const calls = setupHandlers([makeLlmJob()])
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: /大模型连接/ }))
    fireEvent.click(await screen.findByTestId('datasource-llm-config-test'))

    await waitFor(() => expect(calls).toContain('test-connection'))
    expect(await screen.findByText('连通成功 · deepseek-chat · 120 ms')).toBeInTheDocument()
    const requestSpec = connectionBodies[0].request_spec as Record<string, unknown>
    expect(requestSpec).toMatchObject({
      url_template: 'https://api.deepseek.com',
      llm: { model: 'deepseek-chat' },
    })
    expect(connectionBodies[0]).not.toHaveProperty('session_id')
  })

  it('连通测试失败展示后端原因', async () => {
    setupHandlers([makeLlmJob()], {
      connectionResult: { ok: false, latency_ms: 80, model: '', message: '401 Unauthorized' },
    })
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: /大模型连接/ }))
    fireEvent.click(await screen.findByTestId('datasource-llm-config-test'))

    expect(await screen.findByText('连通失败')).toBeInTheDocument()
    expect(screen.getByText('401 Unauthorized')).toBeInTheDocument()
  })

  it('cron 调度时高级设置提示确认自动识别的幂等键', async () => {
    setupHandlers([makeLlmJob({ schedule: { mode: 'cron', expr: '0 7 * * *' } })])
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: '编辑 模型日报' }))
    fireEvent.click(await screen.findByText(/高级设置/))
    expect(await screen.findByText(/cron 任务建议预览后确认自动识别的幂等键/)).toBeInTheDocument()
  })

  it('非 llm_prompt 任务回归：显示 URL 模板与响应数组路径，不渲染提示词字段', async () => {
    setupHandlers([makeJob()])
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: '编辑 北京天气日报' }))
    expect(await screen.findByText('响应数组路径')).toBeInTheDocument()
    expect(screen.getByTestId('datasource-url-template')).toBeInTheDocument()
    expect(screen.queryByTestId('datasource-llm-user')).not.toBeInTheDocument()
    expect(screen.queryByTestId('datasource-llm-model')).not.toBeInTheDocument()
  })
})
