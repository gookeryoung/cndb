/** PipelinesPage 测试 —— 列表展示 / 编辑抽屉实时校验 / 启用开关 / 运行跳转 / 删除. */

import { describe, expect, it } from 'vitest'
import { http, HttpResponse } from 'msw'
import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { Routes, Route, useLocation } from 'react-router-dom'
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

/** 运行详情路由档 —— 展示当前 pathname（MemoryRouter 下不能读 window.location） */
function RunDetailStub() {
  const loc = useLocation()
  return <div data-testid="run-detail-stub">{loc.pathname}</div>
}

/** 按域渲染：数据表域落在 /pipelines，文档域落在 /documents/pipelines（ADR 0080 D4 修订） */
function renderPage(domain: 'table' | 'document' = 'table') {
  const base = domain === 'document' ? '/w/10/documents/pipelines' : '/w/10/pipelines'
  const routePath = domain === 'document' ? '/w/:wid/documents/pipelines' : '/w/:wid/pipelines'
  return renderProviders(
    <Routes>
      <Route path={routePath} element={<PipelinesPage domain={domain} />} />
      <Route path={`${routePath}/:rid`} element={<RunDetailStub />} />
    </Routes>,
    { route: base, ...AUTH },
  )
}

function defaultHandlers() {
  server.use(
    http.get('/api/v1/workspaces/10', () => HttpResponse.json({ id: 10, name: '测试工作区', current_user_role: 'editor' })),
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
    // 编辑器换成 CodeMirror（需求 0111）：内容以文档文本断言
    const editor = await screen.findByTestId('pipeline-dsl-editor')
    expect(editor).toHaveTextContent('name: 空值巡检')
    expect(await screen.findByText(/校验通过/)).toBeInTheDocument()
    expect(screen.getByText(/检查动作目录（1）/)).toBeInTheDocument()
  })

  it('顶部动作条列出内置动作，点击插入到编辑器', async () => {
    defaultHandlers()
    server.use(
      http.get('/api/v1/workspaces/10/pipelines/checks', () => HttpResponse.json([
        ...CHECKS,
        {
          uses: 'table/duplicate-rows',
          title: '重复行',
          category: 'table',
          severity: 'warn',
          target_types: ['table'],
          inputs: [],
        },
      ])),
      http.post('/api/v1/workspaces/10/pipelines/validate', () => HttpResponse.json({
        ok: true, error: '', name: '空值巡检', job_count: 1, step_count: 1,
      })),
    )
    renderPage()

    fireEvent.click(await screen.findByRole('button', { name: /编\s*辑/ }))
    const bar = await screen.findByTestId('pipeline-action-bar')
    expect(within(bar).getByText('检查动作目录（2）')).toBeInTheDocument()

    // 动作目录收在「插入动作」下拉里，展开后可见标题与 uses
    fireEvent.click(within(bar).getByRole('button', { name: /插入内置动作/ }))
    expect(await screen.findByText('table/duplicate-rows')).toBeInTheDocument()
    fireEvent.click(screen.getByText('重复行'))
    const editor = screen.getByTestId('pipeline-dsl-editor')
    await waitFor(() => expect(editor).toHaveTextContent('uses: table/duplicate-rows'))
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

  it('运行成功后停留在运行历史，并以「运行中」实时展示', async () => {
    defaultHandlers()
    let runsCalls = 0
    const running: PipelineRun = {
      ...RUN,
      status: 'running',
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    }
    server.use(
      http.post('/api/v1/workspaces/10/pipelines/7/run', () => HttpResponse.json(running, { status: 202 })),
      // 首次为空历史；触发运行后接口失效重查返回运行中的记录
      http.get('/api/v1/workspaces/10/pipeline-runs', () => {
        runsCalls += 1
        return HttpResponse.json(
          runsCalls === 1 ? { total: 0, items: [] } : { total: 1, items: [running] },
        )
      }),
    )
    renderPage()

    fireEvent.click((await screen.findAllByRole('button', { name: /运行 空值巡检/ }))[0]!)
    // 不跳运行详情，停在列表并重查运行历史
    await waitFor(() => expect(runsCalls).toBeGreaterThan(1))
    expect(screen.queryByTestId('run-detail-stub')).toBeNull()

    const runsBox = await screen.findByTestId('qc-runs-box')
    const item = await within(runsBox).findByTestId('run-item-71')
    expect(within(item).getByText('运行中')).toBeInTheDocument()
    // GitHub 的 in-progress 口径：转圈图标 + 已用时
    expect(item.querySelector('.anticon-sync')).not.toBeNull()
    expect(within(item).getByText(/已用时/)).toBeInTheDocument()
  })

  it('「全部」行的一键运行只触发启用的规则，并汇总进行中 / 停用', async () => {
    defaultHandlers()
    const other: PipelineWorkflow = { ...WORKFLOW, id: 8, name: '文档体检' }
    const disabled: PipelineWorkflow = { ...WORKFLOW, id: 9, name: '已停用规则', enabled: false }
    const calls: number[] = []
    server.use(
      http.get('/api/v1/workspaces/10/pipelines', () => HttpResponse.json([WORKFLOW, other, disabled])),
      http.post('/api/v1/workspaces/10/pipelines/7/run', () => {
        calls.push(7)
        return HttpResponse.json(RUN, { status: 202 })
      }),
      http.post('/api/v1/workspaces/10/pipelines/8/run', () => {
        calls.push(8)
        return HttpResponse.json(
          { detail: '流水线「文档体检」已有进行中的运行，请稍后再试' },
          { status: 409 },
        )
      }),
    )
    renderPage()

    fireEvent.click(await screen.findByTestId('pipeline-run-all'))
    await waitFor(() => expect(calls.sort((a, b) => a - b)).toEqual([7, 8]))
    // 停用的规则不触发，且汇总里明确跳过
    expect(calls).not.toContain(9)
    expect(await screen.findByText('已触发 1 条规则运行')).toBeInTheDocument()
    expect(await screen.findByText(/1 条已有进行中的运行；1 条已停用已跳过/)).toBeInTheDocument()
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

  it('规则行可打开版本历史抽屉', async () => {
    defaultHandlers()
    server.use(
      http.get('/api/v1/workspaces/10/pipelines/7/versions', () => HttpResponse.json([{
        id: 11,
        workflow_id: 7,
        version_number: 1,
        change_type: 'manual',
        comment: '',
        created_by_id: 1,
        created_at: '2026-10-01T08:00:00Z',
      }])),
    )
    renderPage()

    fireEvent.click(await screen.findByRole('button', { name: '版本历史 空值巡检' }))
    expect(await screen.findByTestId('pipeline-version-row-1')).toBeInTheDocument()
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

  it('默认展示全部规则的运行历史，「全部」置顶且激活；选中规则后过滤，再点一次回到全部', async () => {
    const requested = historyHandlers()
    renderPage()

    // 「全部」置顶并默认激活，其下为规则清单
    const allRow = await screen.findByTestId('pipeline-item-all')
    expect(allRow).toHaveClass('cn-qc-row--active')
    expect(within(allRow).getByText('全部')).toBeInTheDocument()
    const ruleRow = screen.getByTestId('pipeline-item-7')
    expect(ruleRow).not.toHaveClass('cn-qc-row--active')

    // 默认未选中：右栏直接拉取全部历史，行内带规则名
    expect(await screen.findByTestId('run-item-71')).toBeInTheDocument()
    expect(screen.getByTestId('run-item-72')).toBeInTheDocument()
    expect(screen.getByText('文档巡检')).toBeInTheDocument()
    expect(screen.getByText('排队中')).toBeInTheDocument()
    await waitFor(() => expect(requested[0]).toBeNull())

    // 点击规则 → 只展示该规则的运行，激活态从「全部」转移到规则行
    fireEvent.click(ruleRow)
    await waitFor(() => expect(requested.at(-1)).toBe('7'))
    expect(screen.getByText(/运行历史：空值巡检/)).toBeInTheDocument()
    expect(allRow).not.toHaveClass('cn-qc-row--active')
    expect(ruleRow).toHaveClass('cn-qc-row--active')
    expect(await screen.findByTestId('run-item-71')).toBeInTheDocument()
    expect(screen.queryByTestId('run-item-72')).not.toBeInTheDocument()

    // 再次点击同一规则 → 取消过滤回到全部
    fireEvent.click(ruleRow)
    await waitFor(() => expect(requested.at(-1)).toBeNull())
    expect(await screen.findByTestId('run-item-72')).toBeInTheDocument()
    expect(allRow).toHaveClass('cn-qc-row--active')
    expect(ruleRow).not.toHaveClass('cn-qc-row--active')

    // 点击运行记录跳转运行详情
    fireEvent.click(screen.getByTestId('run-item-71'))
    expect(await screen.findByTestId('run-detail-stub')).toBeInTheDocument()
  })

  it('选中规则后点「全部」清除规则过滤', async () => {
    const requested = historyHandlers()
    renderPage()

    const allRow = await screen.findByTestId('pipeline-item-all')
    fireEvent.click(screen.getByTestId('pipeline-item-7'))
    await waitFor(() => expect(requested.at(-1)).toBe('7'))
    expect(allRow).not.toHaveClass('cn-qc-row--active')

    fireEvent.click(allRow)
    await waitFor(() => expect(requested.at(-1)).toBeNull())
    expect(allRow).toHaveClass('cn-qc-row--active')
    expect(screen.getByTestId('pipeline-item-7')).not.toHaveClass('cn-qc-row--active')
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

// ───────────── 按域复用（ADR 0080 D4 修订）：数据表 / 文档各看各的动作与规则 ─────────────

describe('PipelinesPage 文档域', () => {
  const DOC_WORKFLOW: PipelineWorkflow = {
    id: 9,
    workspace_id: 10,
    name: '文档体检',
    content: [
      'name: 文档体检',
      'on:',
      '  manual: true',
      'jobs:',
      '  体检:',
      '    steps:',
      '      - uses: document/broken-refs',
    ].join('\n'),
    compiled: {
      name: '文档体检',
      on: { manual: true },
      jobs: [{ steps: [{ uses: 'document/broken-refs' }] }],
    },
    enabled: true,
    created_by_id: 1,
    created_at: '2026-10-01T08:00:00Z',
    updated_at: '2026-10-01T08:00:00Z',
    last_run: null,
  }

  const DOC_CHECKS: PipelineCheckSpec[] = [{
    uses: 'document/broken-refs',
    title: '引用完整性',
    category: 'document',
    severity: 'warn',
    target_types: ['document'],
    inputs: [],
  }]

  /** 记录三个请求上的 domain 查询参数（undefined = 未带） */
  function docHandlers(seen: Array<string | null> = []) {
    server.use(
      http.get('/api/v1/workspaces/10/pipelines', ({ request }) => {
        seen.push(new URL(request.url).searchParams.get('domain'))
        return HttpResponse.json([DOC_WORKFLOW])
      }),
      http.get('/api/v1/workspaces/10/pipelines/checks', ({ request }) => {
        seen.push(new URL(request.url).searchParams.get('domain'))
        return HttpResponse.json(DOC_CHECKS)
      }),
      http.get('/api/v1/workspaces/10/pipeline-runs', ({ request }) => {
        seen.push(new URL(request.url).searchParams.get('domain'))
        return HttpResponse.json({ total: 0, items: [] })
      }),
    )
    return seen
  }

  it('请求三个接口都带 domain=document，页面只呈现文档规则与动作', async () => {
    const seen = docHandlers()
    renderPage('document')

    await screen.findByTestId('pipeline-item-9')
    expect(screen.getByText('文档体检')).toBeInTheDocument()
    // 副标题按域说明作用域
    expect(screen.getByText(/仅文档检查动作与规则/)).toBeInTheDocument()
    // 三个接口均按文档域过滤（检查动作目录只给 document/*）
    await waitFor(() => expect(seen.filter(v => v === 'document').length).toBe(3))

    fireEvent.click(screen.getByRole('button', { name: /编\s*辑/ }))
    expect(await screen.findByText('检查动作目录（1）')).toBeInTheDocument()
    // 动作目录在下拉菜单里，展开后才挂载菜单项
    fireEvent.click(screen.getByRole('button', { name: /插入内置动作/ }))
    expect(await screen.findByText('document/broken-refs')).toBeInTheDocument()
    expect(screen.queryByText('table/null-rate')).not.toBeInTheDocument()
  })

  it('文档域空态文案与新建模板按域给出', async () => {
    server.use(
      http.get('/api/v1/workspaces/10/pipelines', () => HttpResponse.json([])),
      http.get('/api/v1/workspaces/10/pipelines/checks', () => HttpResponse.json([])),
      http.get('/api/v1/workspaces/10/pipeline-runs', () => HttpResponse.json({ total: 0, items: [] })),
    )
    renderPage('document')

    expect(await screen.findByText(/还没有文档检查规则/)).toBeInTheDocument()
    expect(screen.getByText(/还没有文档检查动作/)).toBeInTheDocument()
    expect(screen.queryByText(/还没有数据表检查规则/)).not.toBeInTheDocument()
    // 规则清单为空时不渲染「全部」行，避免与空态示例重复
    expect(screen.queryByTestId('pipeline-item-all')).toBeNull()

    // 新建模板默认带文档动作（数据表模板不出现）
    fireEvent.click(screen.getByRole('button', { name: /新建流水线/ }))
    const editor = await screen.findByTestId('pipeline-dsl-editor')
    expect(editor).toHaveTextContent('document/broken-refs')
    expect(editor).not.toHaveTextContent('table/null-rate')
  })

  it('手动运行停留在文档运行列表，点运行记录才进详情且留在文档域', async () => {
    docHandlers()
    const running: PipelineRun = { ...RUN, status: 'running', workflow_name: '文档体检' }
    server.use(
      http.post('/api/v1/workspaces/10/pipelines/9/run', () => HttpResponse.json(running, { status: 202 })),
      http.get('/api/v1/workspaces/10/pipeline-runs', () =>
        HttpResponse.json({ total: 1, items: [running] })),
    )
    renderPage('document')

    fireEvent.click(await screen.findByRole('button', { name: /运行 文档体检/ }))
    // 运行后仍在运行列表：不跳详情
    expect(await screen.findByTestId('run-item-71')).toBeInTheDocument()
    await waitFor(() => expect(screen.queryByTestId('run-detail-stub')).toBeNull())

    // 点运行记录才进详情，且详情路由留在文档上下文
    fireEvent.click(screen.getByTestId('run-item-71'))
    expect(await screen.findByTestId('run-detail-stub')).toHaveTextContent('/w/10/documents/pipelines/71')
  })
})
