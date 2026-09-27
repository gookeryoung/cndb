/**
 * MatrixView 组件测试 —— 矩阵视图.
 *
 * 覆盖：未配置轴字段空态 / 空数据空态 / 纵轴行头与横轴列头渲染（彩色竖条+加粗标题+计数）/
 * 左上角标注格轴徽章 / 单元格高度自适应 / 单元格卡片归属与点击回调 / 日期轴分桶粒度。
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

  it('左上角标注格展示纵轴/横轴徽章与字段名', () => {
    renderMatrix()

    const corner = screen.getByTestId('matrix-corner')
    expect(screen.getByText('纵轴')).toBeInTheDocument()
    expect(screen.getByText('横轴')).toBeInTheDocument()
    expect(corner.textContent).toContain('团队')
    expect(corner.textContent).toContain('排期日期')
  })

  it('轴区纵横双色淡染与分轴分界线', () => {
    renderMatrix()

    // 纵轴行头复用品牌色 4% 淡染，横轴列头用独立轴色 4% 淡染，角格上下双色分段 7%
    for (const h of screen.getAllByTestId('matrix-row-header')) {
      expect(h.style.background).toContain('4%')
      expect(h.style.background).toContain('var(--cn-brand-color)')
    }
    for (const h of screen.getAllByTestId('matrix-col-header')) {
      expect(h.style.background).toContain('4%')
      expect(h.style.background).toContain('var(--cn-axis-col-color)')
    }
    const corner = screen.getByTestId('matrix-corner')
    expect(corner.style.backgroundImage).toContain('linear-gradient')
    expect(corner.style.backgroundImage).toContain('7%')
    expect(corner.style.borderBottom).toContain('var(--cn-axis-col-color)')
    expect(corner.style.borderRight).toContain('var(--cn-brand-color)')

    // 轴区内侧分界线随所在轴着色
    for (const h of screen.getAllByTestId('matrix-col-header')) {
      expect(h.style.borderBottom).toContain('var(--cn-axis-col-color)')
    }
    for (const h of screen.getAllByTestId('matrix-row-header')) {
      expect(h.style.borderRight).toContain('var(--cn-brand-color)')
    }

    // 数据单元格显式 container 白底与轴区对比；空单元格保持中性弱底
    const cells = screen.getAllByTestId('matrix-cell')
    const filled = cells.filter((c) => c.textContent !== '')
    const empty = cells.filter((c) => c.textContent === '')
    expect(filled.length).toBeGreaterThan(0)
    expect(empty.length).toBeGreaterThan(0)
    for (const c of filled) expect(c.style.background).toBe('var(--cn-bg-container)')
    for (const c of empty) expect(c.style.background).toBe('var(--cn-bg-page)')
  })

  it('未分组虚线边界与数据列间淡竖线', () => {
    renderMatrix({
      rows: [
        ...ROWS,
        { id: 4, 任务名称: '无团队任务', 团队: null, 排期日期: '2026-07-10' },
        { id: 5, 任务名称: '无日期任务', 团队: '研发组', 排期日期: null },
      ] as unknown as RowResponse[],
    })

    // 3 列（2026-07 / 2026-08 / 未分组）× 4 行（含未分组行）= 12 格，行内按列序排列
    const cells = screen.getAllByTestId('matrix-cell')
    expect(cells).toHaveLength(12)

    // 「未分组」列：列头与各格左缘虚线（横轴色）
    const udgColHeader = screen.getAllByTestId('matrix-col-header')
      .find((h) => h.textContent!.includes('未分组'))
    expect(udgColHeader).toBeDefined()
    expect(udgColHeader!.style.borderLeft).toContain('dashed')
    for (let i = 2; i < cells.length; i += 3) {
      expect(cells[i].style.borderLeft).toContain('dashed')
    }

    // 「未分组」行：行头与各格上缘虚线（纵轴色）
    const udgRowHeader = screen.getAllByTestId('matrix-row-header')
      .find((h) => h.textContent!.includes('未分组'))
    expect(udgRowHeader).toBeDefined()
    expect(udgRowHeader!.style.borderTop).toContain('dashed')
    for (let i = 9; i < cells.length; i += 1) {
      expect(cells[i].style.borderTop).toContain('dashed')
    }

    // 数据列间淡竖线：首列无 borderLeft（行头右缘分界线覆盖），其余列 1px solid
    for (let i = 0; i < cells.length; i += 3) {
      expect(cells[i].style.borderLeft).toBe('')
    }
    for (let i = 1; i < cells.length; i += 3) {
      expect(cells[i].style.borderLeft).toContain('1px solid')
    }
  })

  it('单元格高度自适应（无 maxHeight 硬上限）', () => {
    renderMatrix()

    const cells = screen.getAllByTestId('matrix-cell')
    expect(cells.length).toBeGreaterThan(0)
    for (const cell of cells) {
      expect(cell.style.maxHeight).toBe('')
      expect(cell.style.overflowY).toBe('')
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
