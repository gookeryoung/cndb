/** PipelineRunDetail 测试 —— job/step 结论树 / 发现物过滤 / 失败信息 / 分页 offset. */

import { describe, expect, it } from 'vitest'
import { http, HttpResponse } from 'msw'
import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { Route, Routes, useLocation } from 'react-router-dom'
import PipelineRunDetail from './PipelineRunDetail'
import { renderProviders } from '@/test/render-providers'
import { mockUser, server } from '@/test/msw'
import type { PipelineFinding, PipelineFindingPage, PipelineRun } from '@/api'

const AUTH = { initialAuth: { user: mockUser, token: 'fake' } }

const RUN: PipelineRun = {
  id: 71,
  workflow_id: 7,
  workspace_id: 10,
  trigger: 'event',
  trigger_payload: { event: 'record.updated' },
  status: 'partial',
  stats: {
    jobs_total: 1,
    jobs_done: 1,
    steps_total: 2,
    findings: { error: 0, warn: 1, info: 0 },
    duration_ms: 120,
    jobs: [
      {
        id: '体检',
        conclusion: 'success',
        steps: [
          { uses: 'table/null-rate', severity: 'warn', conclusion: 'success', findings: { error: 0, warn: 1, info: 0 } },
          { uses: 'document/links', severity: 'info', conclusion: 'skipped', findings: { error: 0, warn: 0, info: 0 } },
        ],
      },
    ],
    warnings: ['条件求值失败按 false 处理'],
  },
  error_message: '',
  created_at: '2026-10-01T09:00:00Z',
  updated_at: '2026-10-01T09:00:00Z',
  workflow_name: '空值巡检',
}

function finding(id: number, severity: PipelineFinding['severity']): PipelineFinding {
  return {
    id,
    run_id: 71,
    check: severity === 'error' ? 'table/duplicates' : 'table/null-rate',
    severity,
    target_type: 'table',
    target_id: 20,
    locator: { field: '城市' },
    message: severity === 'error' ? '存在重复行' : '城市存在空值',
    detail: {},
    created_at: '2026-10-01T09:00:01Z',
  }
}

const FINDINGS: PipelineFinding[] = [finding(1, 'error'), finding(2, 'warn')]

/** 列表页路由档 —— 展示当前 pathname（验证返回路径留在本域） */
function ListStub() {
  const loc = useLocation()
  return <div data-testid="list-stub">{loc.pathname}</div>
}

/** 按域渲染：数据表运行详情 /pipelines/:rid，文档运行详情 /documents/pipelines/:rid */
function renderPage(domain: 'table' | 'document' = 'table') {
  const base = domain === 'document' ? '/w/10/documents/pipelines' : '/w/10/pipelines'
  const routePath = domain === 'document' ? '/w/:wid/documents/pipelines' : '/w/:wid/pipelines'
  return renderProviders(
    <Routes>
      <Route path={`${routePath}/:rid`} element={<PipelineRunDetail domain={domain} />} />
      <Route path={routePath} element={<ListStub />} />
    </Routes>,
    { route: `${base}/71`, ...AUTH },
  )
}

function defaultHandlers() {
  server.use(
    http.get('/api/v1/workspaces/10/pipeline-runs/71', () => HttpResponse.json(RUN)),
    http.get('/api/v1/workspaces/10/pipeline-runs/71/findings', ({ request }) => {
      const severity = new URL(request.url).searchParams.get('severity')
      const items = severity ? FINDINGS.filter(item => item.severity === severity) : FINDINGS
      const page: PipelineFindingPage = { total: items.length, items }
      return HttpResponse.json(page)
    }),
  )
}

describe('PipelineRunDetail 运行详情', () => {
  it('展示 job / step 结论树与发现物', async () => {
    defaultHandlers()
    renderPage()

    expect(await screen.findByText('空值巡检')).toBeInTheDocument()
    expect(screen.getByText('有告警')).toBeInTheDocument()
    expect(screen.getByText('条件求值失败按 false 处理')).toBeInTheDocument()
    // Collapse 面板首次展开才挂载 children，先点 job 标题
    fireEvent.click(await screen.findByText('体检'))
    expect(await screen.findByText('table/null-rate')).toBeInTheDocument()
    expect(screen.getByText('严重度 告警')).toBeInTheDocument()
    // step.findings 是按严重度计数的对象，展示时汇总为条数而非 [object Object]
    expect(screen.getByText('发现 1 项')).toBeInTheDocument()
    expect(screen.getByText('发现 0 项')).toBeInTheDocument()
    expect(await screen.findByText('城市存在空值')).toBeInTheDocument()
  })

  it('按严重度过滤时携带 severity 参数', async () => {
    defaultHandlers()
    const { container } = renderPage()

    await screen.findByText('空值巡检')
    const segmented = container.querySelector('.ant-segmented')
    expect(segmented).not.toBeNull()
    fireEvent.click(within(segmented as HTMLElement).getByText('错误'))
    await waitFor(() => expect(screen.queryByText('城市存在空值')).toBeNull())
    expect(await screen.findByText('存在重复行')).toBeInTheDocument()
  })

  it('失败运行展示错误信息', async () => {
    server.use(
      http.get('/api/v1/workspaces/10/pipeline-runs/71', () => HttpResponse.json({
        ...RUN,
        status: 'failed',
        error_message: '执行器异常：表不存在',
        stats: { ...RUN.stats, warnings: [] },
      })),
      http.get('/api/v1/workspaces/10/pipeline-runs/71/findings', () =>
        HttpResponse.json({ total: 0, items: [] })),
    )
    renderPage()

    expect(await screen.findByText('执行器异常：表不存在')).toBeInTheDocument()
    expect(screen.getByText('没有匹配的发现物')).toBeInTheDocument()
  })

  it('表目标发现物可一键转问题', async () => {
    let posted = false
    server.use(
      http.get('/api/v1/workspaces/10/pipeline-runs/71', () => HttpResponse.json(RUN)),
      http.get('/api/v1/workspaces/10/pipeline-runs/71/findings', () =>
        HttpResponse.json({ total: 1, items: [finding(1, 'warn')] })),
      http.post('/api/v1/workspaces/10/pipeline-runs/71/findings/1/issue', () => {
        posted = true
        return HttpResponse.json({
          id: 55,
          workspace_id: 10,
          table_id: 20,
          title: '[warn] 城市存在空值',
          description: '',
          category: 'data_error',
          status: 'open',
          created_by_id: 1,
          comments: [],
          events: [],
        })
      }),
    )
    renderPage()

    const button = await screen.findByRole('button', { name: /转问题/ })
    fireEvent.click(button)
    await waitFor(() => expect(posted).toBe(true))
    expect(await screen.findByText('已创建问题 #55')).toBeInTheDocument()
  })

  it('非表目标发现物不展示转问题入口', async () => {
    server.use(
      http.get('/api/v1/workspaces/10/pipeline-runs/71', () => HttpResponse.json(RUN)),
      http.get('/api/v1/workspaces/10/pipeline-runs/71/findings', () =>
        HttpResponse.json({
          total: 1,
          items: [{ ...finding(3, 'warn'), target_type: 'document', target_id: 9, check: 'document/links' }],
        })),
    )
    renderPage()

    expect(await screen.findByText('城市存在空值')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /转问题/ })).toBeNull()
  })

  it('多页发现物翻页时请求新的 offset', async () => {
    let capturedOffset = ''
    server.use(
      http.get('/api/v1/workspaces/10/pipeline-runs/71', () => HttpResponse.json({ ...RUN, status: 'success' })),
      http.get('/api/v1/workspaces/10/pipeline-runs/71/findings', ({ request }) => {
        capturedOffset = new URL(request.url).searchParams.get('offset') ?? ''
        return HttpResponse.json({ total: 120, items: [finding(1, 'warn')] })
      }),
    )
    renderPage()

    fireEvent.click(await screen.findByTitle('2'))
    await waitFor(() => expect(capturedOffset).toBe('50'))
  })

  it('文档域运行详情「返回质量检查」回到文档质量检查页', async () => {
    defaultHandlers()
    renderPage('document')

    await screen.findByText('空值巡检')
    fireEvent.click(screen.getByRole('button', { name: /返回质量检查/ }))
    // 不跳回工作区级 /pipelines（数据表域）
    expect(await screen.findByTestId('list-stub')).toHaveTextContent('/w/10/documents/pipelines')
  })

  it('采用规则页同款页头与「概要条 + 双栏方盒」布局', async () => {
    defaultHandlers()
    const { container } = renderPage()

    await screen.findByText('空值巡检')
    expect(screen.getByTestId('pipeline-run-detail')).toBeInTheDocument()
    expect(container.querySelector('.cn-page-head')).not.toBeNull()
    expect(screen.getByTestId('qc-jobs-box')).toBeInTheDocument()
    expect(screen.getByTestId('qc-findings-box')).toBeInTheDocument()
    // 概要条：Job / Step / 严重度 / 耗时单元格
    expect(container.querySelector('.cn-qc-run-summary')).not.toBeNull()
    expect(screen.getByText('Job')).toBeInTheDocument()
    expect(screen.getByText('1/1')).toBeInTheDocument()
    expect(screen.getByText('120 ms')).toBeInTheDocument()
  })

  it('没有 job 记录时展示执行结果空态', async () => {
    server.use(
      http.get('/api/v1/workspaces/10/pipeline-runs/71', () => HttpResponse.json({
        ...RUN,
        stats: { ...RUN.stats, jobs: [], jobs_total: 0, jobs_done: 0, steps_total: 0 },
      })),
      http.get('/api/v1/workspaces/10/pipeline-runs/71/findings', () =>
        HttpResponse.json({ total: 0, items: [] })),
    )
    renderPage()

    expect(await screen.findByText('暂无 job 执行记录')).toBeInTheDocument()
  })
})
