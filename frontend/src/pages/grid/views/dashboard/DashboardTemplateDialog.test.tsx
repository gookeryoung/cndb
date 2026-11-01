/** dashboard 模板对话框测试（ADR 0023 P3）.
 *
 * 覆盖：另存（默认名 / 校验 / 剥离来源表）· 应用（自动认领 / 缺失字段映射 / 删除）·
 * 空模板列表。
 */

import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import type { DashboardTemplate, Field } from '@/api'
import { renderProviders } from '@/test/render-providers'
import { makeField } from '@/test/fixtures'
import { normalizeDashboard } from './dashboardModel'
import DashboardTemplateDialog from './DashboardTemplateDialog'

const apiMock = vi.hoisted(() => ({
  listDashboardTemplates: vi.fn(),
  saveDashboardTemplate: vi.fn(),
  deleteDashboardTemplate: vi.fn(),
}))

vi.mock('@/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api')>()
  return { ...actual, preferencesApi: apiMock }
})

const FIELDS: Field[] = [
  makeField({ id: 1, name: '商品类别', field_type: 'text' }),
  makeField({ id: 2, name: '销售额', field_type: 'number' }),
]

const TARGET_FIELDS: Field[] = [
  makeField({ id: 11, name: '类别', field_type: 'text' }),
  makeField({ id: 12, name: '金额', field_type: 'number' }),
]

beforeEach(() => {
  vi.resetAllMocks()
})

const CONFIG = normalizeDashboard(
  {
    widgets: [
      {
        id: 'w_chart_1',
        type: 'chart',
        layout: { x: 0, y: 0, w: 6, h: 8 },
        chart: { type: 'bar', x: '商品类别', y: ['销售额'], agg: 'sum' },
      },
    ],
  },
  FIELDS,
)

function makeTemplate(overrides: Partial<DashboardTemplate> = {}): DashboardTemplate {
  return {
    id: 't1',
    name: '经营概览',
    updated_at: '2026-01-01T00:00:00Z',
    config: {
      schema_version: 1,
      widgets: [
        {
          id: 'w_chart_1',
          type: 'chart',
          layout: { x: 0, y: 0, w: 6, h: 8 },
          chart: { type: 'bar', x: '商品类别', y: ['销售额'], agg: 'sum' },
        },
      ],
    },
    fields: { 商品类别: 'text', 销售额: 'number' },
    ...overrides,
  }
}

function renderDialog(mode: 'save' | 'apply', options?: {
  fields?: Field[]
  defaultName?: string
}) {
  const handlers = { onClose: vi.fn(), onSaved: vi.fn(), onApply: vi.fn() }
  renderProviders(
    <DashboardTemplateDialog
      open
      mode={mode}
      config={CONFIG}
      fields={options?.fields ?? TARGET_FIELDS}
      defaultName={options?.defaultName}
      {...handlers}
    />,
  )
  return handlers
}

describe('DashboardTemplateDialog — 另存', () => {
  it('默认名称可编辑，保存时只提交结构与字段类型快照', async () => {
    apiMock.saveDashboardTemplate.mockResolvedValue(makeTemplate())
    const handlers = renderDialog('save', { fields: FIELDS, defaultName: '订单模板' })

    const nameInput = screen.getByTestId('dashboard-template-name') as HTMLInputElement
    expect(nameInput.value).toBe('订单模板')
    fireEvent.change(nameInput, { target: { value: '自定义模板' } })
    fireEvent.click(screen.getByTestId('dashboard-template-save'))

    await waitFor(() => expect(apiMock.saveDashboardTemplate).toHaveBeenCalledTimes(1))
    const payload = apiMock.saveDashboardTemplate.mock.calls[0][0]
    expect(payload.name).toBe('自定义模板')
    expect(payload.fields).toEqual({ 商品类别: 'text', 销售额: 'number' })
    expect(payload.config.widgets[0].query.table_id).toBeUndefined()
    expect(handlers.onSaved).toHaveBeenCalledWith(expect.objectContaining({ name: '经营概览' }))
    expect(handlers.onClose).toHaveBeenCalled()
  })

  it('名称为空不提交', () => {
    const handlers = renderDialog('save', { defaultName: '初始名称' })
    fireEvent.change(screen.getByTestId('dashboard-template-name'), { target: { value: '   ' } })
    fireEvent.click(screen.getByTestId('dashboard-template-save'))
    expect(apiMock.saveDashboardTemplate).not.toHaveBeenCalled()
    expect(handlers.onClose).not.toHaveBeenCalled()
  })

  it('保存失败提示错误且不关闭', async () => {
    apiMock.saveDashboardTemplate.mockRejectedValue({
      response: { data: { detail: '最多保存 20 个模板' } },
    })
    const handlers = renderDialog('save', { defaultName: '模板' })
    fireEvent.click(screen.getByTestId('dashboard-template-save'))
    expect(await screen.findByText('保存模板失败：最多保存 20 个模板')).toBeInTheDocument()
    expect(handlers.onClose).not.toHaveBeenCalled()
  })
})

describe('DashboardTemplateDialog — 应用', () => {
  it('自动认领同名同类型，无缺失字段时可直接应用', async () => {
    apiMock.listDashboardTemplates.mockResolvedValue([makeTemplate()])
    const handlers = renderDialog('apply', { fields: FIELDS })

    fireEvent.click(await screen.findByTestId('dashboard-template-item-t1'))
    await waitFor(() => expect(screen.getByTestId('dashboard-template-apply')).toBeEnabled())
    fireEvent.click(screen.getByTestId('dashboard-template-apply'))

    await waitFor(() => expect(handlers.onApply).toHaveBeenCalledTimes(1))
    const applied = handlers.onApply.mock.calls[0][0]
    expect(applied.widgets[0].chart.x).toBe('商品类别')
    expect(handlers.onClose).toHaveBeenCalled()
  })

  it('缺失字段必须逐项指定映射后才可应用', async () => {
    const template = makeTemplate()
    apiMock.listDashboardTemplates.mockResolvedValue([template])
    const handlers = renderDialog('apply', { fields: TARGET_FIELDS })

    fireEvent.click(await screen.findByTestId('dashboard-template-item-t1'))
    expect(screen.getByTestId('dashboard-template-apply')).toBeDisabled()

    // 两个缺失字段：商品类别 → 类别，销售额 → 金额
    fireEvent.mouseDown(screen.getByTestId('dashboard-template-map-商品类别'))
    fireEvent.click(await screen.findByText('类别（text）', { selector: '.ant-select-item-option-content' }))
    fireEvent.mouseDown(screen.getByTestId('dashboard-template-map-销售额'))
    fireEvent.click(await screen.findByText('金额（number）', { selector: '.ant-select-item-option-content' }))

    await waitFor(() => expect(screen.getByTestId('dashboard-template-apply')).toBeEnabled())
    fireEvent.click(screen.getByTestId('dashboard-template-apply'))
    await waitFor(() => expect(handlers.onApply).toHaveBeenCalledTimes(1))
    const applied = handlers.onApply.mock.calls[0][0]
    expect(applied.widgets[0].chart.x).toBe('类别')
    expect(applied.widgets[0].chart.y).toEqual(['金额'])
  })

  it('删除模板后列表刷新', async () => {
    let templates = [makeTemplate()]
    apiMock.listDashboardTemplates.mockImplementation(() => Promise.resolve(templates))
    apiMock.deleteDashboardTemplate.mockImplementation(async (id: string) => {
      templates = templates.filter((item) => item.id !== id)
    })
    renderDialog('apply')

    const item = await screen.findByTestId('dashboard-template-item-t1')
    fireEvent.click(within(item).getByTestId('dashboard-template-delete-t1'))
    await waitFor(() => expect(apiMock.deleteDashboardTemplate).toHaveBeenCalledWith('t1'))
    expect(await screen.findByTestId('dashboard-template-empty')).toBeInTheDocument()
    expect(screen.queryByTestId('dashboard-template-item-t1')).not.toBeInTheDocument()
  })

  it('没有模板时展示空态且应用按钮不可用', async () => {
    apiMock.listDashboardTemplates.mockResolvedValue([])
    renderDialog('apply')
    expect(await screen.findByTestId('dashboard-template-empty')).toBeInTheDocument()
    expect(screen.getByTestId('dashboard-template-apply')).toBeDisabled()
  })
})
