/**
 * MatrixView 组件测试 —— 矩阵视图.
 *
 * 覆盖：未配置轴字段空态 / 空数据空态 / 纵轴行头与横轴列头渲染（彩色竖条+加粗标题+计数）/
 * 单元格卡片归属与点击回调 / 日期轴分桶粒度。
 */

import { describe, expect, it, vi } from 'vitest'
import { fireEvent, screen } from '@testing-library/react'
import MatrixView from './MatrixView'
import { renderProviders } from '@/test/render-providers'
import { makeField } from '@/test/fixtures'
import type { Field, RowResponse, View } from '@/api'

const FIELDS: Field[] = [
  makeField({ id: 1, name: '任务名称', field_type: 'text' }),
  makeField({ id: 2, name: '团队', field_type: 'select', config: { options: ['研发组', '设计组', '测试组'] } }),
  makeField({ id: 3, name: '排期日期', field_type: 'date' }),
]

const ROWS: RowResponse[] = [
  { id: 1, 任务名称: '订单服务接口开发', 团队: '研发组', 排期日期: '2026-07-06' },
  { id: 2, 任务名称: '大促场景性能压测', 团队: '测试组', 排期日期: '2026-08-05' },
  { id: 3, 任务名称: '门户首页视觉改版', 团队: '设计组', 排期日期: '2026-07-07' },
] as unknown as RowResponse[]

function renderMatrix(props?: {
  rows?: RowResponse[]
  view?: View | null
  onRowClick?: (r: RowResponse) => void
}) {
  const view = props?.view !== undefined ? props.view
    : {
      id: 1, name: '资源排期矩阵', view_type: 'matrix', is_default: false,
      view_options: { row_field: '团队', column_field: '排期日期', date_granularity: 'month', title_field: '任务名称' },
    }
  return renderProviders(
    <MatrixView
      rows={props?.rows ?? ROWS}
      fields={FIELDS}
      view={view}
      density="comfortable"
      onRowClick={props?.onRowClick}
    />,
  )
}

describe('MatrixView 矩阵视图', () => {
  it('未配置轴字段显示引导空态', () => {
    renderMatrix({
      view: { id: 1, name: '矩阵', view_type: 'matrix', is_default: false, view_options: {} },
    })

    expect(screen.getByText(/矩阵视图需配置纵轴字段与横轴字段/)).toBeInTheDocument()
  })

  it('空数据显示引导空态', () => {
    renderMatrix({ rows: [] })

    expect(screen.getByText(/这张表还没有数据/)).toBeInTheDocument()
  })

  it('渲染纵轴行头与横轴列头（区域标题）', () => {
    renderMatrix()

    // 纵轴：三个团队 + 左上角纵轴字段名
    const rowHeaders = screen.getAllByTestId('matrix-row-header')
    expect(rowHeaders).toHaveLength(3)
    expect(screen.getByText('研发组')).toBeInTheDocument()
    expect(screen.getByText('测试组')).toBeInTheDocument()
    expect(screen.getByText('设计组')).toBeInTheDocument()
    // 横轴：两个月份桶 + 左上角横轴字段名
    const colHeaders = screen.getAllByTestId('matrix-col-header')
    expect(colHeaders).toHaveLength(2)
    expect(screen.getByText('2026-07')).toBeInTheDocument()
    expect(screen.getByText('2026-08')).toBeInTheDocument()
    // 区域标题加粗
    for (const h of rowHeaders) {
      expect(h.querySelector('span[style*="font-weight"]')).not.toBeNull()
    }
  })

  it('单元格按类别填入行卡片', () => {
    renderMatrix()

    const cards = screen.getAllByTestId('matrix-cell-card')
    expect(cards).toHaveLength(3)
    expect(screen.getByText('订单服务接口开发')).toBeInTheDocument()
    expect(screen.getByText('门户首页视觉改版')).toBeInTheDocument()
    expect(screen.getByText('大促场景性能压测')).toBeInTheDocument()
  })

  it('点击卡片触发行详情回调', () => {
    const onRowClick = vi.fn()
    renderMatrix({ onRowClick })

    fireEvent.click(screen.getByText('订单服务接口开发'))

    expect(onRowClick).toHaveBeenCalledTimes(1)
    expect(onRowClick.mock.calls[0][0].id).toBe(1)
  })

  it('week 粒度列头带「当周」后缀', () => {
    renderMatrix({
      view: {
        id: 1, name: '矩阵', view_type: 'matrix', is_default: false,
        view_options: { row_field: '团队', column_field: '排期日期', date_granularity: 'week', title_field: '任务名称' },
      },
    })

    // 2026-07-06 / 2026-07-07 同周桶，2026-08-05 另一周桶（dayjs 默认 locale 周起始）
    const colHeaders = screen.getAllByTestId('matrix-col-header')
    expect(colHeaders).toHaveLength(2)
    expect(screen.getAllByText(/当周/)).toHaveLength(2)
  })

  it('行列计数徽章与行总数一致', () => {
    renderMatrix()

    // 研发组 1 行、测试组 1 行、设计组 1 行；2026-07 两行、2026-08 一行
    const rowHeaders = screen.getAllByTestId('matrix-row-header')
    for (const h of rowHeaders) {
      expect(h.textContent).toContain('1')
    }
    const colTexts = screen.getAllByTestId('matrix-col-header').map((h) => h.textContent)
    expect(colTexts[0]).toContain('2')
    expect(colTexts[1]).toContain('1')
  })
})
