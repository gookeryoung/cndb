/** StrategiesPage 集成测试 —— 列表渲染 / 空态 / 启停 / 运行后打开运行详情. */

import { describe, expect, it } from 'vitest'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { Route, Routes } from 'react-router-dom'
import StrategiesPage from './StrategiesPage'
import { renderProviders } from '@/test/render-providers'
import { server } from '@/test/msw'
import type { AcquisitionStrategy } from '@/api/acquisition'

const WID = 1
const BASE = `/api/v1/workspaces/${WID}`

function makeStrategy(overrides: Partial<AcquisitionStrategy> = {}): AcquisitionStrategy {
  return {
    id: 5,
    workspace_id: WID,
    name: '固态电池政策日报',
    enabled: true,
    scope: { channels: ['job:2'], query: '{today} 固态电池', max_results_per_channel: 50 },
    filter_rule: { must_have_keywords: ['电解质'] },
    targets: [{ kind: 'table', table_id: 9, match_keys: ['city', 'day'] }],
    iteration: { max_rounds: 2, expand: { review: 'manual' }, budget: { max_requests: 100 } },
    llm: {},
    schedule: { mode: 'daily', at: '08:00' },
    rule_version: 3,
    last_run_at: '2026-11-02T00:00:00Z',
    last_status: 'success',
    created_at: '2026-11-01T00:00:00Z',
    updated_at: '2026-11-02T00:00:00Z',
    ...overrides,
  }
}

const RUN = {
  id: 11,
  strategy_id: 5,
  trigger: 'manual',
  status: 'success',
  round_count: 1,
  progress: 100,
  progress_message: '采集完成',
  fetched: 4,
  inserted: 2,
  updated: 0,
  skipped: 1,
  docs_created: 0,
  docs_updated: 0,
  docs_skipped: 0,
  budget_used: { requests: 2 },
  error_message: '',
  detail: {},
  started_at: '2026-11-02T00:00:00Z',
  finished_at: '2026-11-02T00:00:01Z',
  duration_ms: 900,
}

function handlers(strategies: AcquisitionStrategy[]) {
  return [
    http.get(`${BASE}/acquisition/strategies`, () =>
      HttpResponse.json({ total: strategies.length, strategies })),
    http.get(`${BASE}/acquisition/channels`, () => HttpResponse.json({
      channels: [
        { value: 'job:2', label: '政策源（http_json）', kind: 'job', provider: 'http_json', requires_key: false, hint: '' },
        { value: 'rss:', label: 'rss', kind: 'preset', provider: 'rss_atom', requires_key: false, hint: '' },
      ],
      providers: [],
      llm_actions: ['rule_draft'],
    })),
    http.get(`${BASE}/tables`, () => HttpResponse.json([
      { id: 9, name: '政策库', workspace_id: WID, row_count: 0, field_count: 3 },
    ])),
    http.get(`${BASE}/documents/tree`, () => HttpResponse.json({ items: [] })),
    http.post(`${BASE}/acquisition/strategies/5/disable`, () =>
      HttpResponse.json(makeStrategy({ enabled: false }))),
    http.post(`${BASE}/acquisition/strategies/5/run`, () => HttpResponse.json(RUN)),
    http.get(`${BASE}/acquisition/strategies/5/runs`, () => HttpResponse.json({ total: 1, runs: [RUN] })),
    http.get(`${BASE}/acquisition/runs/11`, () => HttpResponse.json({ run: RUN, rounds: [] })),
  ]
}

function renderPage() {
  return renderProviders(
    <Routes>
      <Route path="/w/:wid/acquisition" element={<StrategiesPage />} />
    </Routes>,
    { route: `/w/${WID}/acquisition` },
  )
}

describe('StrategiesPage 智能采集', () => {
  it('空态给出新建引导', async () => {
    server.use(...handlers([]))
    renderPage()
    expect(await screen.findByText(/还没有采集策略/)).toBeInTheDocument()
  })

  it('列表展示渠道 / 落点 / 调度与复核口径', async () => {
    server.use(...handlers([makeStrategy()]))
    renderPage()

    expect(await screen.findByText('固态电池政策日报')).toBeInTheDocument()
    expect(screen.getByText('job:2')).toBeInTheDocument()
    expect(screen.getByText('表：政策库')).toBeInTheDocument()
    expect(screen.getByText('每天 08:00')).toBeInTheDocument()
    expect(screen.getByText('复核：每轮确认')).toBeInTheDocument()
  })

  it('停用按钮调用后端并刷新启用态', async () => {
    server.use(...handlers([makeStrategy({ enabled: false })]))
    renderPage()

    const button = await screen.findByRole('button', { name: /启用/ })
    fireEvent.click(button)
    expect(await screen.findByText('停用')).toBeInTheDocument()
  })

  it('运行后打开运行详情抽屉', async () => {
    server.use(...handlers([makeStrategy()]))
    renderPage()

    fireEvent.click(await screen.findByRole('button', { name: /运行/ }))
    expect(await screen.findByText('运行 #11')).toBeInTheDocument()
    expect(screen.getByText(/抓取 4/)).toBeInTheDocument()
  })

  it('落点可就地新建数据表并自动选中，无需退出抽屉', async () => {
    server.use(...handlers([makeStrategy()]))
    let createdName = ''
    server.use(http.post(`${BASE}/tables`, async ({ request }) => {
      const body = await request.json() as { name: string }
      createdName = body.name
      return HttpResponse.json({ id: 42, name: body.name, workspace_id: WID })
    }))
    renderPage()

    fireEvent.click(await screen.findByRole('button', { name: /编辑/ }))
    expect(await screen.findByText('编辑策略 · 固态电池政策日报')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /新建表/ }))
    fireEvent.change(await screen.findByPlaceholderText('数据表名称'), { target: { value: '新采集表' } })
    fireEvent.click(screen.getByRole('button', { name: /创建并选中/ }))

    await waitFor(() => expect(createdName).toBe('新采集表'))
    expect(await screen.findByText(/已新建数据表「新采集表」并选中/)).toBeInTheDocument()
    expect(screen.getByText('新采集表')).toBeInTheDocument()
  })
})
