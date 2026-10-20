/** DatasourcePage 集成测试 —— 列表渲染 / 空态 / 新建抽屉 / 立即运行 / 运行历史. */

import { describe, expect, it } from 'vitest'
import { fireEvent, screen, waitFor } from '@testing-library/react'
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

function setupHandlers(jobs: SyncJob[], options: { runStatus?: 'success' | 'failed' } = {}) {
  const calls: string[] = []
  server.use(
    http.get(`/api/v1/workspaces/${WID}/datasource/providers`, () => HttpResponse.json({ providers: PROVIDERS })),
    http.get(`/api/v1/workspaces/${WID}/datasource/sync-jobs`, () =>
      HttpResponse.json({ total: jobs.length, jobs }),
    ),
    http.get(`/api/v1/workspaces/${WID}/tables`, () => HttpResponse.json(TABLES)),
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
