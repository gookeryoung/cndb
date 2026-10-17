/** AnalyticsPage 集成测试 —— 模板深链 / 运行结果 / 保存与重命名 / 未保存守卫 / 公式快捷编辑. */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { Route, Routes } from 'react-router-dom'
import AnalyticsPage from './AnalyticsPage'
import { renderProviders } from '@/test/render-providers'
import { server } from '@/test/msw'
import type { AnalyticsTemplate } from '@/api/analytics'

const WID = 1
const TID = 20

const FIELDS = [
  { id: 1, name: '产品', field_type: 'text' },
  { id: 2, name: '产量', field_type: 'number' },
  { id: 3, name: '合格数', field_type: 'number' },
]

const TABLE_DETAIL = {
  id: TID,
  workspace_id: WID,
  name: '产品批次',
  description: '',
  db_table_name: 'table_x',
  order: 0,
  trashed: false,
  created_at: '2026-10-01T00:00:00Z',
  updated_at: '2026-10-01T00:00:00Z',
  fields: FIELDS,
  views: [],
  record_count: 2,
  field_count: FIELDS.length,
}

const MAIN_FORMULA = { key: 'pass_rate', label: '合格率(%)', expr: 'round([合格数] / [产量] * 100, 2)' }

function makeTemplate(overrides: Partial<AnalyticsTemplate> & Pick<AnalyticsTemplate, 'id' | 'name'>): AnalyticsTemplate {
  return {
    workspace_id: WID,
    table_id: TID,
    description: '',
    config: {
      formulas: [MAIN_FORMULA],
      chart: { type: 'bar', x: '产品', y: 'pass_rate', aggregation: 'avg', title: '合格率分布' },
      summary: {
        group_by: '产品',
        metrics: [{ field: 'pass_rate', agg: 'avg', label: '平均合格率' }],
        sort_by: 'avg(pass_rate)',
        sort_order: 'desc',
        top_n: 5,
      },
      fields: [],
      limit: 1000,
    },
    updated_at: '2026-10-17T10:00:00Z',
    ...overrides,
  }
}

const TPL_MAIN = makeTemplate({ id: 7, name: '批次合格率分布', description: '按产品看合格率' })
const TPL_OTHER = makeTemplate({
  id: 8,
  name: '其他模板',
  description: '',
  config: {
    formulas: [{ key: 'total', label: '产量合计', expr: 'sum([产量])' }],
    chart: { type: 'bar', x: '产品', y: 'total', aggregation: 'sum', title: '其他' },
    summary: null,
    fields: [],
    limit: 1000,
  },
})
const TPL_BROKEN = makeTemplate({ id: 9, name: '已失效模板', table_id: null, config: { formulas: [MAIN_FORMULA], chart: null, summary: null, fields: [], limit: 1000 } })

const COMPUTE_RESPONSE = {
  rows: [
    { id: 1, 产品: 'A', 产量: 100, 合格数: 96, pass_rate: 96 },
    { id: 2, 产品: 'B', 产量: 200, 合格数: 178, pass_rate: 89 },
  ],
  total: 2,
  truncated: false,
  table_fields: ['产品', '产量', '合格数'],
  columns: [
    {
      key: 'pass_rate', label: '合格率(%)', kind: 'formula', count: 2, missing: 0,
      mean: 92.5, stdev: 4.9, variance: 24.5, min: 89, max: 96, range: 7, q1: 89, median: 92.5, q3: 96, sum: 185,
    },
    {
      key: '产量', label: '产量', kind: 'field', count: 2, missing: 0,
      mean: 150, stdev: 70.7, variance: 5000, min: 100, max: 200, range: 100, q1: 100, median: 150, q3: 200, sum: 300,
    },
  ],
  summary: {
    group_by: '产品',
    group_label: '产品',
    columns: [{ key: 'avg(pass_rate)', label: '平均合格率', agg: 'avg', source: 'pass_rate' }],
    rows: [{ group: 'A', 'avg(pass_rate)': 96 }, { group: 'B', 'avg(pass_rate)': 89 }],
    group_count: 2,
    truncated: false,
  },
}

let computeBodies: Array<Record<string, unknown>> = []
let createBodies: Array<Record<string, unknown>> = []
let updateBodies: Array<Record<string, unknown>> = []

function setupHandlers() {
  computeBodies = []
  createBodies = []
  updateBodies = []
  server.use(
    http.get('/api/v1/workspaces/1/tables', () =>
      HttpResponse.json([{ id: TID, name: '产品批次' }, { id: 21, name: '其他表' }])),
    http.get('/api/v1/workspaces/1/tables/20', () => HttpResponse.json(TABLE_DETAIL)),
    http.get('/api/v1/workspaces/1/analytics/templates', () =>
      HttpResponse.json([TPL_MAIN, TPL_OTHER, TPL_BROKEN])),
    http.post('/api/v1/workspaces/1/analytics/validate', async ({ request }) => {
      const body = (await request.json()) as { formulas: Array<{ key: string; expr: string }> }
      return HttpResponse.json({
        ok: true,
        results: body.formulas.map(f => ({ key: f.key, expr: f.expr, ok: true, fields: [] })),
        table_fields: FIELDS.map(f => f.name),
      })
    }),
    http.post('/api/v1/workspaces/1/analytics/compute', async ({ request }) => {
      computeBodies.push((await request.json()) as Record<string, unknown>)
      return HttpResponse.json(COMPUTE_RESPONSE)
    }),
    http.post('/api/v1/workspaces/1/analytics/templates', async ({ request }) => {
      const body = (await request.json()) as Record<string, unknown>
      createBodies.push(body)
      return HttpResponse.json({ ...TPL_MAIN, id: 99, name: body.name, description: body.description, config: body.config }, { status: 201 })
    }),
    http.put('/api/v1/workspaces/1/analytics/templates/:id', async ({ request, params }) => {
      const body = (await request.json()) as Record<string, unknown>
      updateBodies.push(body)
      return HttpResponse.json({ ...TPL_MAIN, id: Number(params.id), name: body.name ?? TPL_MAIN.name, description: body.description ?? '' })
    }),
  )
}

function renderPage(route = '/w/1/analytics') {
  return renderProviders(
    <Routes>
      <Route path="/w/:wid/analytics" element={<AnalyticsPage />} />
    </Routes>,
    { route },
  )
}

/** 等待深链模板载入（公式回填是异步的） */
async function waitTemplateLoaded(name = TPL_MAIN.name) {
  await waitFor(() => expect(screen.getByTestId('analytics-template-meta')).toHaveTextContent(name))
}

beforeEach(() => {
  setupHandlers()
  Object.defineProperty(URL, 'createObjectURL', { value: vi.fn(() => 'blob:mock'), writable: true, configurable: true })
  Object.defineProperty(URL, 'revokeObjectURL', { value: vi.fn(), writable: true, configurable: true })
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('AnalyticsPage', () => {
  it('深链 ?template=7：自动载入模板并回填公式 / 图表 / 分组汇总', async () => {
    renderPage('/w/1/analytics?template=7')
    await waitTemplateLoaded()

    expect(screen.getByTestId('analytics-formula-expr-0')).toHaveValue(MAIN_FORMULA.expr)
    expect(screen.getByTestId('analytics-chart-title')).toHaveValue('合格率分布')
    expect(screen.getByTestId('analytics-summary-group')).toHaveTextContent('产品')
    // 模板已保存 → 不应显示未保存标记
    expect(screen.queryByTestId('analytics-dirty')).not.toBeInTheDocument()
  })

  it('运行分析：图表 + 分组汇总 + 描述统计（方差/极差/非空率）+ 派生数据预览', async () => {
    renderPage('/w/1/analytics?template=7')
    await waitTemplateLoaded()

    const runBtn = screen.getByTestId('analytics-run-btn')
    await waitFor(() => expect(runBtn).toBeEnabled())
    fireEvent.click(runBtn)

    const summary = await screen.findByTestId('analytics-summary-table')
    expect(summary).toHaveTextContent('平均合格率')
    expect(summary).toHaveTextContent('96')

    const stats = screen.getByTestId('analytics-stats-table')
    expect(stats).toHaveTextContent('合格率(%)')
    expect(stats).toHaveTextContent('方差')
    expect(stats).toHaveTextContent('极差')
    expect(stats).toHaveTextContent('非空率')

    const rows = screen.getByTestId('analytics-rows-table')
    expect(rows).toHaveTextContent('产品')
    expect(rows).toHaveTextContent('合格率(%)（公式）')

    // 请求体带分组汇总配置（模板回填后的 summary）
    expect(computeBodies).toHaveLength(1)
    expect(computeBodies[0].summary).toMatchObject({ group_by: '产品' })

    // 三类导出入口可用
    expect(screen.getByTestId('analytics-export-stats')).toBeInTheDocument()
    expect(screen.getByTestId('analytics-export-rows')).toBeInTheDocument()
    expect(screen.getByTestId('analytics-export-summary')).toBeInTheDocument()
  })

  it('Ctrl/Cmd+Enter 在公式输入中直接运行分析', async () => {
    renderPage('/w/1/analytics?template=7')
    await waitTemplateLoaded()
    await waitFor(() => expect(screen.getByTestId('analytics-run-btn')).toBeEnabled())

    fireEvent.keyDown(screen.getByTestId('analytics-formula-expr-0'), { key: 'Enter', ctrlKey: true })
    await waitFor(() => expect(computeBodies).toHaveLength(1))
  })

  it('另存为副本：弹窗预填「模板名 副本」，提交后创建新模板', async () => {
    renderPage('/w/1/analytics?template=7')
    await waitTemplateLoaded()

    fireEvent.click(screen.getByTestId('analytics-saveas-btn'))
    const dialog = await screen.findByRole('dialog')
    const nameInput = within(dialog).getByTestId('analytics-template-name')
    expect(nameInput).toHaveValue('批次合格率分布 副本')

    fireEvent.change(nameInput, { target: { value: '分析副本' } })
    fireEvent.click(within(dialog).getByRole('button', { name: /保\s*存$/ }))

    await waitFor(() => expect(createBodies).toHaveLength(1))
    expect(createBodies[0].name).toBe('分析副本')
    expect(createBodies[0].config).toMatchObject({ summary: { group_by: '产品' } })
    await waitFor(() => expect(screen.getByTestId('analytics-template-meta')).toHaveTextContent('分析副本'))
    expect(await screen.findByText('已另存为模板「分析副本」')).toBeInTheDocument()
  })

  it('重命名当前模板：只提交名称/说明，保留公式配置', async () => {
    renderPage('/w/1/analytics?template=7')
    await waitTemplateLoaded()

    fireEvent.click(screen.getByTestId('analytics-rename-btn'))
    const dialog = await screen.findByRole('dialog')
    const nameInput = within(dialog).getByTestId('analytics-template-name')
    expect(nameInput).toHaveValue(TPL_MAIN.name)

    fireEvent.change(nameInput, { target: { value: '重命名后的模板' } })
    fireEvent.click(within(dialog).getByRole('button', { name: '重命名' }))

    await waitFor(() => expect(updateBodies).toHaveLength(1))
    expect(updateBodies[0]).toEqual({ name: '重命名后的模板', description: '按产品看合格率' })
    await waitFor(() => expect(screen.getByTestId('analytics-template-meta')).toHaveTextContent('重命名后的模板'))
  })

  it('有未保存修改时切换模板先确认；确认后载入新模板', async () => {
    renderPage('/w/1/analytics?template=7')
    await waitTemplateLoaded()

    fireEvent.change(screen.getByTestId('analytics-formula-expr-0'), { target: { value: '[产量] * 2' } })
    expect(await screen.findByTestId('analytics-dirty')).toBeInTheDocument()

    fireEvent.mouseDown(screen.getByTestId('analytics-template-select').querySelector('.ant-select-selector')!)
    fireEvent.click(await screen.findByText('其他模板', { selector: '.ant-select-item-option-content' }))

    const confirm = await screen.findByRole('dialog')
    expect(confirm.querySelector('.ant-modal-confirm-title')).toHaveTextContent('放弃未保存的修改？')
    fireEvent.click(within(confirm).getByRole('button', { name: '放弃并切换' }))

    expect(await screen.findByDisplayValue('sum([产量])')).toBeInTheDocument()
    await waitFor(() => expect(screen.getByTestId('analytics-template-meta')).toHaveTextContent('其他模板'))
  })

  it('模板的数据源表已删除：提示重新选择分析表', async () => {
    renderPage('/w/1/analytics?template=9')
    await waitTemplateLoaded(TPL_BROKEN.name)
    expect(screen.getByTestId('analytics-table-missing')).toHaveTextContent('数据源表已被删除')
  })

  it('字段快捷插入 + 本地公式校验（空键名即时提示）', async () => {
    renderPage('/w/1/analytics?template=7')
    await waitTemplateLoaded()

    // 点击字段 chip 插入到公式光标处（默认末尾）
    fireEvent.click(await screen.findByText('产量', { selector: '[data-testid="analytics-field-chips"] .ant-tag' }))
    expect(screen.getByTestId('analytics-formula-expr-0')).toHaveValue(`${MAIN_FORMULA.expr}[产量]`)

    // 清空键名 → 本地即时校验（不等后端）
    fireEvent.change(screen.getByLabelText('公式键名 1'), { target: { value: '' } })
    expect(screen.getByTestId('analytics-formula-error')).toHaveTextContent('键名不能为空')
    expect(screen.getByTestId('analytics-run-btn')).toBeDisabled()
  })

  it('导出描述统计 CSV：触发浏览器下载并提示成功', async () => {
    renderPage('/w/1/analytics?template=7')
    await waitTemplateLoaded()
    await waitFor(() => expect(screen.getByTestId('analytics-run-btn')).toBeEnabled())
    fireEvent.click(screen.getByTestId('analytics-run-btn'))
    await screen.findByTestId('analytics-stats-table')

    fireEvent.click(screen.getByTestId('analytics-export-stats'))
    expect(URL.createObjectURL).toHaveBeenCalledTimes(1)
    expect(await screen.findByText('描述统计已导出 CSV')).toBeInTheDocument()
  })
})
