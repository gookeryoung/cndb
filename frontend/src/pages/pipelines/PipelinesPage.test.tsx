/** PipelinesPage 测试 —— 列表展示 / 编辑抽屉实时校验 / 启用开关 / 运行跳转 / 删除. */

import { describe, expect, it } from 'vitest'
import { http, HttpResponse } from 'msw'
import { fireEvent, screen, waitFor } from '@testing-library/react'
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
  )
}

describe('PipelinesPage 列表与编辑', () => {
  it('展示定义名、触发摘要与最近运行状态', async () => {
    defaultHandlers()
    renderPage()

    expect(await screen.findByText('空值巡检')).toBeInTheDocument()
    expect(screen.getByText(/事件 record.updated/)).toBeInTheDocument()
    expect(screen.getByText('通过')).toBeInTheDocument()
    expect(screen.getByText('最近运行')).toBeInTheDocument()
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

    fireEvent.click((await screen.findAllByText('运行'))[0]!.closest('button')!)
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
