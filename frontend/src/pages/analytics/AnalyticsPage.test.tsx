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

/** 智能推荐 fixture（公式含一条与模板重复的 pass_rate，用于验证去重） */
const RECOMMENDATIONS = {
  table_id: TID,
  row_count: 2,
  sampled_rows: 2,
  truncated: false,
  fields: [
    { name: '产品', field_type: 'text', role: 'dimension', reason: '低基数文本列，适合分组', cardinality: 2, completeness: 1 },
    { name: '产量', field_type: 'number', role: 'metric', reason: '数值列，适合求和/平均' },
    { name: '合格数', field_type: 'number', role: 'metric', reason: '数值列' },
  ],
  formulas: [
    { key: 'pass_rate', label: '合格率', expr: 'round([合格数] / [产量] * 100, 2)', reason: '两数值列比值' },
    { key: 'yield_total', label: '产量合计', expr: 'sum([产量])', reason: '整列求和' },
  ],
  chart: {
    chart: { type: 'line', x: '产品', y: 'yield_total', aggregation: 'avg', title: '推荐趋势图' },
    reason: '维度 + 指标组合适合折线图',
  },
  summary: {
    summary: {
      group_by: '产品',
      metrics: [{ field: 'yield_total', agg: 'sum', label: '总产量' }],
      sort_by: null,
      sort_order: 'desc',
      top_n: 3,
    },
    reason: '按产品分组看产量',
  },
  examples: [
    {
      id: 'trend',
      name: '产量趋势',
      description: '按产品看产量趋势',
      formulas: [{ key: 'yield_total', label: '产量合计', expr: 'sum([产量])' }],
      chart: { type: 'line', x: '产品', y: 'yield_total', aggregation: 'sum', title: '示例趋势' },
      summary: null,
      reason: '典型产能分析场景',
    },
  ],
}

let computeBodies: Array<Record<string, unknown>> = []
let createBodies: Array<Record<string, unknown>> = []
let updateBodies: Array<Record<string, unknown>> = []
let duplicateBodies: Array<Record<string, unknown>> = []
let deleteIds: number[] = []
/** AI 生成分析 / 结论解读的请求体（ADR 0020 P3） */
let aiSuggestBodies: Array<Record<string, unknown>> = []
let aiExplainBodies: Array<Record<string, unknown>> = []
/** 后端内存态模板列表：复制 / 删除后刷新能读到新状态 */
let templateList: AnalyticsTemplate[] = []

/** AI 生成的模板配置（表达式与已有模板不同，便于断言真的回填了编辑态） */
const AI_FORMULA_EXPR = 'round([合格数] / [产量] * 100, 1)'

const AI_TEMPLATE_SUGGESTION = {
  action: 'analytics.suggest_template',
  run_id: 8895,
  model: 'deepseek-chat',
  usage: { prompt_tokens: 120, completion_tokens: 90, total_tokens: 210 },
  result: {
    name: 'AI 各产品合格率对比',
    description: '按产品看平均合格率',
    config: {
      formulas: [{ key: 'pass_rate_ai', label: '合格率AI', expr: AI_FORMULA_EXPR }],
      chart: { type: 'line', x: '产品', y: 'pass_rate_ai', aggregation: 'avg', title: 'AI 合格率趋势' },
      summary: {
        group_by: '产品',
        metrics: [{ field: 'pass_rate_ai', agg: 'avg', label: 'AI 平均合格率' }],
        sort_by: null,
        sort_order: 'desc',
        top_n: 3,
      },
      fields: [],
      limit: 1000,
    },
    warnings: ['表中无 month 字段，已按日期截断月份，请确认'],
  },
}

const AI_EXPLAIN_RESPONSE = {
  action: 'analytics.explain',
  run_id: 8896,
  model: 'deepseek-chat',
  usage: { prompt_tokens: 80, completion_tokens: 60, total_tokens: 140 },
  result: {
    insight: '产品 A 的合格率最高（96%），产品 B 为 89%。',
    caveats: ['样本仅覆盖 2 个产品'],
  },
}

function setupHandlers() {
  computeBodies = []
  createBodies = []
  updateBodies = []
  duplicateBodies = []
  deleteIds = []
  aiSuggestBodies = []
  aiExplainBodies = []
  templateList = [TPL_MAIN, TPL_OTHER, TPL_BROKEN]
  server.use(
    http.get('/api/v1/workspaces/1/tables', () =>
      HttpResponse.json([{ id: TID, name: '产品批次' }, { id: 21, name: '其他表' }])),
    http.get('/api/v1/workspaces/1/tables/20', () => HttpResponse.json(TABLE_DETAIL)),
    http.get('/api/v1/workspaces/1/analytics/templates', () =>
      HttpResponse.json(templateList)),
    http.get('/api/v1/workspaces/1/analytics/recommendations', ({ request }) => {
      const tableId = Number(new URL(request.url).searchParams.get('table_id'))
      return HttpResponse.json({ ...RECOMMENDATIONS, table_id: tableId })
    }),
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
    // AI 生成分析模板 / 结论解读（ADR 0020 P3；不触真实模型）
    http.post('/api/v1/workspaces/1/analytics/ai/suggest-template', async ({ request }) => {
      aiSuggestBodies.push((await request.json()) as Record<string, unknown>)
      return HttpResponse.json(AI_TEMPLATE_SUGGESTION)
    }),
    http.post('/api/v1/workspaces/1/analytics/ai/explain', async ({ request }) => {
      aiExplainBodies.push((await request.json()) as Record<string, unknown>)
      return HttpResponse.json(AI_EXPLAIN_RESPONSE)
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
    http.post('/api/v1/workspaces/1/analytics/templates/:id/duplicate', async ({ request, params }) => {
      const body = (await request.json().catch(() => ({}))) as { name?: string }
      duplicateBodies.push(body)
      const source = templateList.find(t => t.id === Number(params.id)) ?? TPL_MAIN
      const copy: AnalyticsTemplate = { ...source, id: 100, name: body.name?.trim() || `${source.name} 副本` }
      templateList = [copy, ...templateList]
      return HttpResponse.json(copy, { status: 201 })
    }),
    http.delete('/api/v1/workspaces/1/analytics/templates/:id', ({ params }) => {
      const id = Number(params.id)
      deleteIds.push(id)
      templateList = templateList.filter(t => t.id !== id)
      return new HttpResponse(null, { status: 204 })
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

  it('分析范围：设置起止值后请求体带扫描过滤', async () => {
    renderPage('/w/1/analytics?template=7')
    await waitTemplateLoaded()
    await waitFor(() => expect(screen.getByTestId('analytics-run-btn')).toBeEnabled())

    // 未设范围时 filters 为空数组（等价不过滤）
    fireEvent.click(screen.getByTestId('analytics-run-btn'))
    await waitFor(() => expect(computeBodies).toHaveLength(1))
    expect(computeBodies[0].filters).toEqual([])

    // 选范围字段 + 起止值 → 两个比较条件
    fireEvent.mouseDown(screen.getByTestId('analytics-scope-field').querySelector('.ant-select-selector')!)
    fireEvent.click(await screen.findByText('产品', { selector: '.ant-select-item-option-content' }))
    fireEvent.change(screen.getByTestId('analytics-scope-from'), { target: { value: 'A' } })
    fireEvent.change(screen.getByTestId('analytics-scope-to'), { target: { value: 'C' } })

    fireEvent.click(screen.getByTestId('analytics-run-btn'))
    await waitFor(() => expect(computeBodies).toHaveLength(2))
    expect(computeBodies[1].filters).toEqual([
      { field_name: '产品', op: '>=', value: 'A' },
      { field_name: '产品', op: '<=', value: 'C' },
    ])
  })

  it('换表后清空分析范围（范围字段属于旧表）', async () => {
    renderPage('/w/1/analytics?template=7')
    await waitTemplateLoaded()

    fireEvent.mouseDown(screen.getByTestId('analytics-scope-field').querySelector('.ant-select-selector')!)
    fireEvent.click(await screen.findByText('产品', { selector: '.ant-select-item-option-content' }))
    fireEvent.change(screen.getByTestId('analytics-scope-from'), { target: { value: 'A' } })
    expect(screen.getByTestId('analytics-scope-from')).toHaveValue('A')

    fireEvent.mouseDown(screen.getByTestId('analytics-table-select').querySelector('.ant-select-selector')!)
    fireEvent.click(await screen.findByText('其他表', { selector: '.ant-select-item-option-content' }))

    await waitFor(() => expect(screen.getByTestId('analytics-scope-from')).toHaveValue(''))
    // 字段也被清掉：输入框在未选范围字段时禁用
    expect(screen.getByTestId('analytics-scope-from')).toBeDisabled()
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

  it('智能推荐：应用图表 / 汇总 / 追加公式（跳过重复 key）/ 典型示例', async () => {
    renderPage('/w/1/analytics?template=7')
    await waitTemplateLoaded()
    // 选表后请求推荐
    await screen.findByTestId('analytics-recommend-dimension-产品')

    // 应用推荐图表 → 图表配置回填并标记未保存
    fireEvent.click(screen.getByTestId('analytics-recommend-chart'))
    expect(screen.getByTestId('analytics-chart-title')).toHaveValue('推荐趋势图')
    expect(await screen.findByText('已应用推荐图表')).toBeInTheDocument()
    expect(await screen.findByTestId('analytics-dirty')).toBeInTheDocument()

    // 应用推荐汇总 → 指标与 Top N 回填
    fireEvent.click(screen.getByTestId('analytics-recommend-summary'))
    await waitFor(() => expect(screen.getByTestId('analytics-summary-metric-label-0')).toHaveValue('总产量'))
    expect(screen.getByTestId('analytics-summary-topn')).toHaveValue('3')
    expect(await screen.findByText('已应用推荐分组汇总')).toBeInTheDocument()

    // 追加推荐公式：pass_rate 与现有公式重复 → 只追加 yield_total
    fireEvent.click(screen.getByTestId('analytics-recommend-formulas'))
    await waitFor(() => expect(screen.getByTestId('analytics-formula-expr-1')).toHaveValue('sum([产量])'))
    expect(screen.getByTestId('analytics-formula-expr-0')).toHaveValue(MAIN_FORMULA.expr)
    expect(await screen.findByText('已追加 1 条推荐公式')).toBeInTheDocument()

    // 应用典型示例 → 公式 / 图表 / 汇总整体替换
    fireEvent.click(screen.getByTestId('analytics-recommend-examples'))
    const example = await screen.findByTestId('analytics-recommend-example-trend')
    expect(example).toHaveTextContent('产量趋势')
    fireEvent.click(example)

    await waitFor(() => expect(screen.getByTestId('analytics-chart-title')).toHaveValue('示例趋势'))
    expect(screen.getByTestId('analytics-formula-expr-0')).toHaveValue('sum([产量])')
    expect(screen.queryByTestId('analytics-formula-expr-1')).not.toBeInTheDocument()
    expect(await screen.findByText('已应用典型示例「产量趋势」')).toBeInTheDocument()
  })

  it('分析列表：新建分析清空当前配置并移除 ?template 深链', async () => {
    renderPage('/w/1/analytics?template=7')
    await waitTemplateLoaded()
    await screen.findByTestId('analytics-recommend')

    fireEvent.click(screen.getByTestId('analytics-manager-btn'))
    await screen.findByTestId('analytics-manager')
    fireEvent.click(screen.getByTestId('analytics-manager-new'))

    await waitFor(() => expect(screen.queryByTestId('analytics-template-meta')).not.toBeInTheDocument())
    expect(screen.getByTestId('analytics-formula-expr-0')).toHaveValue('')
    expect(screen.getByTestId('analytics-chart-title')).toHaveValue('')
    // 数据源清空后推荐区块隐藏 / 未保存标记消失
    expect(screen.queryByTestId('analytics-recommend')).not.toBeInTheDocument()
    expect(screen.queryByTestId('analytics-dirty')).not.toBeInTheDocument()
  })

  it('分析列表：复制模板后刷新列表并打开副本', async () => {
    renderPage('/w/1/analytics?template=7')
    await waitTemplateLoaded()

    fireEvent.click(screen.getByTestId('analytics-manager-btn'))
    await screen.findByTestId('analytics-manager')
    fireEvent.click(screen.getByTestId('analytics-manager-duplicate-7'))

    await waitFor(() => expect(duplicateBodies).toHaveLength(1))
    await waitFor(() => expect(screen.getByTestId('analytics-template-meta')).toHaveTextContent('批次合格率分布 副本'))
    expect(await screen.findByText('已复制为「批次合格率分布 副本」')).toBeInTheDocument()

    // 刷新后的模板列表包含副本
    fireEvent.click(screen.getByTestId('analytics-manager-btn'))
    expect(await screen.findByTestId('analytics-manager-item-100')).toHaveTextContent('批次合格率分布 副本')
  })

  it('分析列表：删除需确认，确认后移除模板', async () => {
    renderPage('/w/1/analytics?template=7')
    await waitTemplateLoaded()

    fireEvent.click(screen.getByTestId('analytics-manager-btn'))
    await screen.findByTestId('analytics-manager-item-8')
    fireEvent.click(screen.getByTestId('analytics-manager-delete-8'))

    const titles = await screen.findAllByText('删除分析「其他模板」？')
    const confirm = titles[0].closest('.ant-modal') as HTMLElement
    fireEvent.click(within(confirm).getByRole('button', { name: /删\s*除/ }))

    await waitFor(() => expect(deleteIds).toEqual([8]))
    expect(await screen.findByText('模板已删除')).toBeInTheDocument()
    await waitFor(() => expect(screen.queryByTestId('analytics-manager-item-8')).not.toBeInTheDocument())
  })
  // ── AI 生成分析模板 / 结论解读（ADR 0020 P3） ──

  it('AI 生成分析：成功回填公式 / 图表 / 汇总与模板名，展示 warnings 且不自动保存', async () => {
    renderPage('/w/1/analytics?template=7')
    await waitTemplateLoaded()

    fireEvent.change(screen.getByTestId('analytics-ai-question'), {
      target: { value: '按产品看平均合格率，并标出最低的三个产品' },
    })
    fireEvent.click(screen.getByTestId('analytics-ai-generate'))

    // 已填入编辑态（成功提示 + 名称）
    expect(await screen.findByTestId('analytics-ai-applied')).toHaveTextContent('AI 各产品合格率对比')
    await waitFor(() => expect(screen.getByTestId('analytics-formula-expr-0')).toHaveValue(AI_FORMULA_EXPR))
    expect(screen.getByTestId('analytics-chart-title')).toHaveValue('AI 合格率趋势')
    // 分组汇总指标标签被回填（与已有模板不同的标签）
    await waitFor(() =>
      expect(screen.getByTestId('analytics-summary-metric-label-0')).toHaveValue('AI 平均合格率'))
    // warnings 用 Alert 展示
    expect(screen.getByTestId('analytics-ai-warnings')).toHaveTextContent('表中无 month 字段')
    // 只填编辑态：不自动创建 / 更新模板，且请求体带当前表 id
    expect(createBodies).toHaveLength(0)
    expect(updateBodies).toHaveLength(0)
    expect(aiSuggestBodies).toEqual([{ table_id: TID, question: '按产品看平均合格率，并标出最低的三个产品' }])
    // 生成后进入「未保存」态
    expect(await screen.findByTestId('analytics-dirty')).toBeInTheDocument()
  })

  it('AI 生成分析：有未保存修改时先确认，确认后才覆盖编辑态', async () => {
    renderPage('/w/1/analytics?template=7')
    await waitTemplateLoaded()

    fireEvent.change(screen.getByTestId('analytics-formula-expr-0'), { target: { value: '[产量] * 2' } })
    expect(await screen.findByTestId('analytics-dirty')).toBeInTheDocument()

    fireEvent.change(screen.getByTestId('analytics-ai-question'), { target: { value: '按产品看合格率' } })
    fireEvent.click(screen.getByTestId('analytics-ai-generate'))

    const confirm = await screen.findByRole('dialog')
    expect(confirm.querySelector('.ant-modal-confirm-title')).toHaveTextContent('覆盖当前编辑中的分析配置？')
    // 确认前不覆盖
    expect(screen.getByTestId('analytics-formula-expr-0')).toHaveValue('[产量] * 2')

    fireEvent.click(within(confirm).getByRole('button', { name: '覆盖并填入' }))
    await waitFor(() =>
      expect(screen.getByTestId('analytics-formula-expr-0')).toHaveValue(AI_FORMULA_EXPR))
    expect(createBodies).toHaveLength(0)
    expect(updateBodies).toHaveLength(0)
  })

  it('AI 生成分析 422：展示后端 detail，且不改动当前配置', async () => {
    renderPage('/w/1/analytics?template=7')
    await waitTemplateLoaded()
    server.use(
      http.post('/api/v1/workspaces/1/analytics/ai/suggest-template', () =>
        HttpResponse.json({ detail: 'AI 生成的配置未通过校验：公式引用字段不存在' }, { status: 422 })),
    )

    fireEvent.change(screen.getByTestId('analytics-ai-question'), { target: { value: '按不存在的字段分析' } })
    fireEvent.click(screen.getByTestId('analytics-ai-generate'))

    expect(await screen.findByTestId('analytics-ai-error'))
      .toHaveTextContent('AI 生成的配置未通过校验：公式引用字段不存在')
    // 失败不改编辑态
    expect(screen.getByTestId('analytics-formula-expr-0')).toHaveValue(MAIN_FORMULA.expr)
    expect(screen.queryByTestId('analytics-dirty')).not.toBeInTheDocument()
  })

  it('未选择分析表时 AI 生成入口禁用', async () => {
    renderPage('/w/1/analytics')
    expect(screen.getByTestId('analytics-ai-question')).toBeDisabled()
    expect(screen.getByTestId('analytics-ai-generate')).toBeDisabled()
  })

  it('AI 解读：把汇总结果行（≤50）传给 explain，抽屉展示结论与口径提醒，且不写模板', async () => {
    renderPage('/w/1/analytics?template=7')
    await waitTemplateLoaded()
    await waitFor(() => expect(screen.getByTestId('analytics-run-btn')).toBeEnabled())
    fireEvent.click(screen.getByTestId('analytics-run-btn'))
    await screen.findByTestId('analytics-summary-table')

    fireEvent.click(screen.getByTestId('analytics-ai-explain'))

    const drawer = await screen.findByTestId('analytics-ai-explain-drawer')
    await waitFor(() => expect(drawer).toHaveTextContent('产品 A 的合格率最高（96%）'))
    expect(screen.getByTestId('analytics-ai-caveats')).toHaveTextContent('样本仅覆盖 2 个产品')

    // 请求体：当前分组汇总行 + 图表类型 + 模板 id
    expect(aiExplainBodies).toHaveLength(1)
    expect(aiExplainBodies[0]).toMatchObject({
      summary_rows: [
        { group: 'A', 'avg(pass_rate)': 96 },
        { group: 'B', 'avg(pass_rate)': 89 },
      ],
      chart_type: 'bar',
      template_id: 7,
    })
    expect((aiExplainBodies[0].summary_rows as unknown[]).length).toBeLessThanOrEqual(50)
    // 只读：不写模板、不改数据
    expect(createBodies).toHaveLength(0)
    expect(updateBodies).toHaveLength(0)
    expect(computeBodies).toHaveLength(1)
  })

  it('AI 解读失败：抽屉展示后端 detail，可重新解读', async () => {
    renderPage('/w/1/analytics?template=7')
    await waitTemplateLoaded()
    await waitFor(() => expect(screen.getByTestId('analytics-run-btn')).toBeEnabled())
    fireEvent.click(screen.getByTestId('analytics-run-btn'))
    await screen.findByTestId('analytics-summary-table')

    server.use(
      http.post('/api/v1/workspaces/1/analytics/ai/explain', () =>
        HttpResponse.json({ detail: '上游模型服务不可用（502）' }, { status: 502 })),
    )

    fireEvent.click(screen.getByTestId('analytics-ai-explain'))
    expect(await screen.findByTestId('analytics-ai-explain-error'))
      .toHaveTextContent('上游模型服务不可用（502）')
    expect(screen.getByTestId('analytics-ai-explain-regenerate')).toBeInTheDocument()
  })
})
