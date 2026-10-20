/** DatasourcePage 集成测试 —— 列表渲染 / 空态 / 新建抽屉 / 立即运行 / 运行历史. */

import { describe, expect, it } from 'vitest'
import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { Route, Routes } from 'react-router-dom'
import DatasourcePage from './DatasourcePage'
import { renderProviders } from '@/test/render-providers'
import { server } from '@/test/msw'
import type { SyncJob } from '@/api'

const WID = 1

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

function setupHandlers(jobs: SyncJob[], options: { runStatus?: 'success' | 'failed' } = {}) {
  const calls: string[] = []
  sessionBodies = []
  server.use(
    http.get(`/api/v1/workspaces/${WID}/datasource/providers`, () => HttpResponse.json({ providers: PROVIDERS })),
    http.get(`/api/v1/workspaces/${WID}/datasource/sync-jobs`, () =>
      HttpResponse.json({ total: jobs.length, jobs }),
    ),
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
            formulas: [],
            chart: { type: 'line', x: 'day', y: 'close', series: null, title: '趋势', aggregation: 'avg' },
            summary: null,
          },
        ],
      }),
    ),
    http.post(`/api/v1/workspaces/${WID}/analytics/templates`, async ({ request }) => {
      calls.push('create-template')
      const body = (await request.json()) as { name: string }
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
})
