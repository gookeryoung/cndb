/** 评分矩阵（ADR 0136）—— 可编辑单元格 / 固定行列 / 只读边界. */

import { describe, expect, it, vi } from 'vitest'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import MatrixView from './MatrixView'
import { renderProviders } from '@/test/render-providers'
import { server } from '@/test/msw'
import { recordApi } from '@/api'
import { makeField } from '@/test/fixtures'
import type { Field, RowResponse, View } from '@/api'

const FIELDS: Field[] = [
  makeField({ id: 1, name: '部门', field_type: 'select', config: { options: ['研发部', '市场部', '财务部'] } }),
  makeField({ id: 2, name: '月份', field_type: 'date' }),
  makeField({ id: 3, name: '得分', field_type: 'number' }),
]

const VIEW = {
  id: 1, name: '部门绩效评分矩阵', view_type: 'matrix', is_default: false,
  view_options: {
    row_field: '部门', column_field: '月份', date_granularity: 'month',
    value_field: '得分', period_start: '2026-11', period_end: '2026-12',
  },
} as unknown as View

const ROWS: RowResponse[] = [
  { id: 1, 部门: '研发部', 月份: '2026-11-01', 得分: 88 },
] as unknown as RowResponse[]

function mockApi(rows: RowResponse[] = ROWS) {
  server.use(
    http.get('/api/v1/workspaces/:wid/tables/:tid/fields', () => HttpResponse.json(FIELDS)),
    http.get('/api/v1/workspaces/:wid/tables/:tid/records', () =>
      HttpResponse.json({ items: rows, total: rows.length, offset: 0, limit: 5000 })),
  )
}

function renderScore(props?: { canEditRecords?: boolean; rowRulesActive?: boolean; rows?: RowResponse[] }) {
  mockApi(props?.rows ?? ROWS)
  return renderProviders(
    <MatrixView
      rows={[]}
      fields={FIELDS}
      view={VIEW}
      density="comfortable"
      workspaceId="1"
      tableId="1"
      canEditRecords={props?.canEditRecords ?? true}
      rowRulesActive={props?.rowRulesActive ?? false}
    />,
  )
}

describe('MatrixView 评分矩阵', () => {
  it('无数据时仍按固定对象 × 月份范围渲染完整网格', async () => {
    renderScore({ rows: [] })
    expect(await screen.findByTestId('matrix-score-view')).toBeInTheDocument()
    // 3 个对象 × 2 个月
    expect(screen.getAllByTestId('matrix-score-row-header')).toHaveLength(3)
    expect(screen.getAllByTestId('matrix-score-col-header')).toHaveLength(2)
    expect(screen.getAllByTestId('matrix-score-cell')).toHaveLength(6)
    expect(screen.getByText('研发部')).toBeInTheDocument()
    expect(screen.getByText('财务部')).toBeInTheDocument()
    expect(screen.getByText('2026-12')).toBeInTheDocument()
  })

  it('已有行映射到对应单元格，其余单元格为空输入框', async () => {
    renderScore()
    expect(await screen.findByTestId('matrix-score-view')).toBeInTheDocument()
    const inputs = screen.getAllByRole('spinbutton') as HTMLInputElement[]
    expect(inputs).toHaveLength(6)
    expect(inputs.filter((i) => i.value === '88')).toHaveLength(1)
  })

  it('无编辑权限 / 行级权限表显示只读提示且不渲染输入框', async () => {
    renderScore({ canEditRecords: false })
    expect(await screen.findByTestId('matrix-score-readonly-hint')).toHaveTextContent('无编辑权限')
    expect(screen.queryAllByRole('spinbutton')).toHaveLength(0)

    screen.getByTestId('matrix-score-view')
  })

  it('行级权限表只读', async () => {
    renderScore({ rowRulesActive: true })
    expect(await screen.findByTestId('matrix-score-readonly-hint')).toHaveTextContent('行级权限')
    expect(screen.queryAllByRole('spinbutton')).toHaveLength(0)
  })

  it('修改单元格失焦后调用 matrix-upsert', async () => {
    const spy = vi.spyOn(recordApi, 'matrixUpsert').mockResolvedValue({
      action: 'updated',
      row_id: 1,
      row: { id: 1, 部门: '研发部', 月份: '2026-11-01', 得分: 90 },
    })
    renderScore()
    expect(await screen.findByTestId('matrix-score-view')).toBeInTheDocument()
    const input = screen.getAllByRole('spinbutton').find((i) => (i as HTMLInputElement).value === '88') as HTMLInputElement
    fireEvent.change(input, { target: { value: '90' } })
    fireEvent.blur(input)
    await waitFor(() => expect(spy).toHaveBeenCalled())
    expect(spy.mock.calls[0][2]).toMatchObject({
      row_field: '部门', row_value: '研发部', month_field: '月份', month: '2026-11', value_field: '得分', value: 90,
    })
  })
})
