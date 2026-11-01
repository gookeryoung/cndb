/** PipelinesPage 测试 —— 列表展示 / 编辑抽屉实时校验 / 启用开关 / 运行跳转 / 删除. */

import { describe, expect, it } from 'vitest'
import { http, HttpResponse } from 'msw'
import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { Routes, Route } from 'react-router-dom'
import PipelinesPage from './PipelinesPage'
import { renderProviders } from '@/test/render-providers'
import { mockUser, server } from '@/test/msw'
import type { PipelineCheckSpec, PipelineRun, PipelineWorkflow } from '@/api'

const AUTH = { initialAuth: { user: mockUser, token: 'fake' } }

const CONTENT = [
  'name: 空值巡检',
  'on:',
  '  manual: true',
  '  events: [record.updated]',
  'jobs:',
  '  体检:',
  '    steps:',
  '      - uses: table/null-rate',
  '        with:',
  '          table: 人员',
  '          fields: [城市]',
].join('\n')

const WORKFLOW: PipelineWorkflow = {
  id: 7,
  workspace_id: 10,
  name: '空值巡检',
  content: CONTENT,
  compiled: {
    name: '空值巡检',
    on: { manual: true, events: ['record.updated'] },
    jobs: [{ steps: [{ uses: 'table/null-rate' }] }],
  },
  enabled: true,
  created_by_id: 1,
  created_at: '2026-10-01T08:00:00Z',
  updated_at: '2026-10-01T08:00:00Z',
  last_run: {
    id: 70,
    status: 'success',
    trigger: 'manual',
    stats: {},
    created_at: '2026-10-01T09:00:00Z',
  },
}

const CHECKS: PipelineCheckSpec[] = [
  {
    uses: 'table/null-rate',
    title: '空值比例',
    category: 'table',
    severity: 'warn',
    target_types: ['table'],
    inputs: [
      { name: 'table', type: 'string', description: '', required: true, default: null },
      { name: 'fields', type: 'array', description: '', required: true, default: null },
    ],
  },
]

const RUN: PipelineRun = {
  id: 71,
  workflow_id: 7,
  workspace_id: 10,
  trigger: 'manual',
  trigger_payload: {},
  status: 'pending',
  stats: {},
  error_message: '',
  created_at: '2026-10-01T09:00:00Z',
  updated_at: '2026-10-01T09:00:00Z',
  workflow_name: '空值巡检',
}

function renderPage() {
  return renderProviders(
    <Routes>
      <Route path="/w/:wid/pipelines" element={<PipelinesPage />} />
      <Route path="/w/:wid/pipelines/:rid" element={<div data-testid="run-detail-stub">运行详情</div>} />
    </Routes>,
    { route: '/w/10/pipelines', ...AUTH },
  )
}

function defaultHandlers() {
  server.use(
    http.get('/api/v1/workspaces/10/pipelines', () => HttpResponse.json([WORKFLOW])),
    http.get('/api/v1/workspaces/10/pipelines/checks', () => HttpResponse.json(CHECKS)),
    http.get('/api/v1/workspaces/10/pipeline-runs', () =>
      HttpResponse.json({ total: 1, items: [RUN] })),
  )
}

describe('PipelinesPage 列表与编辑', () => {
  it('展示定义名、触发摘要与最近运行状态', async () => {
    defaultHandlers()
    renderPage()

    // 左栏规则清单与右栏运行行都有「空值巡检」与状态标签，限定在规则方盒内断言
    await screen.findByTestId('pipeline-item-7')
    const rulesBox = screen.getByTestId('qc-rules-box')
    expect(within(rulesBox).getByText('空值巡检')).toBeInTheDocument()
    expect(screen.getByText(/事件 record.updated/)).toBeInTheDocument()
    expect(within(rulesBox).getByText('通过')).toBeInTheDocument()
    expect(screen.getByText(/最近运行 2026/)).toBeInTheDocument()
  })

  it('编辑抽屉展示 YAML 并实时校验通过', async () => {
    defaultHandlers()
    server.use(http.post('/api/v1/workspaces/10/pipelines/validate', () => HttpResponse.json({
      ok: true, error: '', name: '空值巡检', job_count: 1, step_count: 1,
    })))
    renderPage()

    fireEvent.click(await screen.findByRole('button', { name: /编\s*辑/ }))
    const editor = await screen.findByLabelText('流水线 YAML')
    expect((editor as HTMLTextAreaElement).value).toContain('name: 空值巡检')
    expect(await screen.findByText(/校验通过/)).toBeInTheDocument()
    expect(screen.getByText(/检查动作目录（1）/)).toBeInTheDocument()
  })

  it('DSL 非法时展示错误并禁用保存', async () => {
    defaultHandlers()
    server.use(http.post('/api/v1/workspaces/10/pipelines/validate', () => HttpResponse.json({
      ok: false, error: '缺少 name', name: '', job_count: 0, step_count: 0,
    })))
    renderPage()

    fireEvent.click(await screen.findByRole('button', { name: /编\s*辑/ }))
    expect(await screen.findByText('DSL 校验未通过')).toBeInTheDocument()
    expect(screen.getByText('缺少 name')).toBeInTheDocument()
    const save = screen.getByRole('button', { name: /保\s*存/ })
    expect(save).toBeDisabled()
  })

  it('启用开关调用更新接口', async () => {
    defaultHandlers()
    let enabled: boolean | undefined
    server.use(http.put('/api/v1/workspaces/10/pipelines/7', async ({ request }) => {
      const body = await request.json() as { enabled?: boolean }
      enabled = body.enabled
      return HttpResponse.json({ ...WORKFLOW, enabled: body.enabled ?? WORKFLOW.enabled })
    }))
    renderPage()

    fireEvent.click(await screen.findByLabelText('空值巡检 启用'))
    await waitFor(() => expect(enabled).toBe(false))
  })

  it('运行成功后跳转运行详情', async () => {
    defaultHandlers()
    server.use(http.post('/api/v1/workspaces/10/pipelines/7/run', () => HttpResponse.json(RUN, { status: 202 })))
    renderPage()

    fireEvent.click((await screen.findAllByRole('button', { name: /运行 空值巡检/ }))[0]!)
    expect(await screen.findByTestId('run-detail-stub')).toBeInTheDocument()
  })

  it('删除需二次确认并调用删除接口', async () => {
    defaultHandlers()
    let deleted = false
    server.use(http.delete('/api/v1/workspaces/10/pipelines/7', () => {
      deleted = true
      return new HttpResponse(null, { status: 204 })
    }))
    renderPage()

    fireEvent.click(await screen.findByRole('button', { name: /删\s*除/ }))
    // Popconfirm 为 portal 渲染，等待确认按钮出现后再点击
    const confirmButtons = await screen.findAllByRole('button', { name: /删\s*除/ })
    fireEvent.click(confirmButtons[confirmButtons.length - 1]!)
    await waitFor(() => expect(deleted).toBe(true))
  })
})

// ─────────────── GitHub 风格双栏（ADR 0080 D4）：左规则清单 / 右运行历史 ───────────────

describe('PipelinesPage 双栏布局', () => {
  /** 全部历史两条（空值巡检 / 文档巡检），按 workflow_id 过滤后只剩空值巡检 */
  const OTHER_RUN: PipelineRun = { ...RUN, id: 72, status: 'success', workflow_name: '文档巡检' }

  function historyHandlers() {
    defaultHandlers()
    const requested: Array<string | null> = []
    server.use(
      http.get('/api/v1/workspaces/10/pipeline-runs', ({ request }) => {
        const workflowId = new URL(request.url).searchParams.get('workflow_id')
        requested.push(workflowId)
        return workflowId
          ? HttpResponse.json({ total: 1, items: [RUN] })
          : HttpResponse.json({ total: 2, items: [RUN, OTHER_RUN] })
      }),
    )
    return requested
  }

  it('默认展示全部规则的运行历史，选中规则后过滤，再点一次回到全部', async () => {
    const requested = historyHandlers()
    renderPage()

    // 默认未选中：右栏直接拉取全部历史，行内带规则名
    expect(await screen.findByTestId('run-item-71')).toBeInTheDocument()
    expect(screen.getByTestId('run-item-72')).toBeInTheDocument()
    expect(screen.getByText('文档巡检')).toBeInTheDocument()
    expect(screen.getByText('排队中')).toBeInTheDocument()
    await waitFor(() => expect(requested[0]).toBeNull())

    // 点击规则 → 只展示该规则的运行
    fireEvent.click(screen.getByTestId('pipeline-item-7'))
    await waitFor(() => expect(requested.at(-1)).toBe('7'))
    expect(screen.getByText(/运行历史：空值巡检/)).toBeInTheDocument()
    expect(await screen.findByTestId('run-item-71')).toBeInTheDocument()
    expect(screen.queryByTestId('run-item-72')).not.toBeInTheDocument()

    // 再次点击同一规则 → 取消过滤回到全部
    fireEvent.click(screen.getByTestId('pipeline-item-7'))
    await waitFor(() => expect(requested.at(-1)).toBeNull())
    expect(await screen.findByTestId('run-item-72')).toBeInTheDocument()

    // 点击运行记录跳转运行详情
    fireEvent.click(screen.getByTestId('run-item-71'))
    expect(await screen.findByTestId('run-detail-stub')).toBeInTheDocument()
  })

  it('「查看全部」按钮清除规则过滤', async () => {
    const requested = historyHandlers()
    renderPage()

    fireEvent.click(await screen.findByTestId('pipeline-item-7'))
    await waitFor(() => expect(requested.at(-1)).toBe('7'))
    fireEvent.click(await screen.findByRole('button', { name: /查看全部/ }))
    await waitFor(() => expect(requested.at(-1)).toBeNull())
  })

  it('选中规则的运行历史为空时给空态提示', async () => {
    defaultHandlers()
    server.use(
      http.get('/api/v1/workspaces/10/pipeline-runs', ({ request }) => {
        const workflowId = new URL(request.url).searchParams.get('workflow_id')
        return workflowId
          ? HttpResponse.json({ total: 0, items: [] })
          : HttpResponse.json({ total: 1, items: [RUN] })
      }),
    )
    renderPage()

    // 全部历史非空，选中后转空态
    expect(await screen.findByTestId('run-item-71')).toBeInTheDocument()
    fireEvent.click(screen.getByTestId('pipeline-item-7'))
    expect(await screen.findByText(/还没有运行记录/)).toBeInTheDocument()
  })

  it('工作区没有任何运行记录时右栏给空态提示', async () => {
    server.use(
      http.get('/api/v1/workspaces/10/pipelines', () => HttpResponse.json([WORKFLOW])),
      http.get('/api/v1/workspaces/10/pipelines/checks', () => HttpResponse.json(CHECKS)),
      http.get('/api/v1/workspaces/10/pipeline-runs', () => HttpResponse.json({ total: 0, items: [] })),
    )
    renderPage()

    expect(await screen.findByText(/运行任一流水线后这里会展示历史/)).toBeInTheDocument()
  })

  it('检查动作目录为空（仅勾「设计」的工作区）时页面给出提示', async () => {
    server.use(
      http.get('/api/v1/workspaces/10/pipelines', () => HttpResponse.json([])),
      http.get('/api/v1/workspaces/10/pipelines/checks', () => HttpResponse.json([])),
    )
    renderPage()

    expect(await screen.findByTestId('empty-checks-alert')).toBeInTheDocument()
    expect(screen.getByText('暂无可用检查动作')).toBeInTheDocument()
  })
})
