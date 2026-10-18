/**
 * ChartCard DOM 归属回归测试 —— 使用真实 ECharts（不 mock）.
 *
 * 背景：ECharts 的 dispose 会清空容器 innerHTML。若同一容器内还挂着 React 管理的子节点
 * （此前「必填字段缺失」是整棵子树换成 Empty，且与图表容器共用同一个 div），
 * 清空后就地再切换回图表时 React 会抛
 * `Failed to execute 'removeChild' on 'Node': The node to be removed is not a child of this node.`
 * （数据分析页调整可视化配置、清空维度/指标即触发）。
 *
 * 契约：图表容器常驻、永不承载 React 子节点；空态为同级覆盖层。
 */

import { describe, expect, it } from 'vitest'
import { act, screen } from '@testing-library/react'
import { renderProviders } from '@/test/render-providers'
import { makeField } from '@/test/fixtures'
import type { Field, RowResponse } from '@/api'
import { ChartCard } from './ChartView'
import type { ChartConfig } from './chartBoard'

const FIELDS: Field[] = [
  makeField({ id: 1, name: '月份', field_type: 'text' }),
  makeField({ id: 2, name: '销售额', field_type: 'number' }),
]

const ROWS: RowResponse[] = [
  { id: 1, 月份: '一月', 销售额: 10 },
  { id: 2, 月份: '二月', 销售额: 20 },
] as unknown as RowResponse[]

const VALID = {
  chart_type: 'bar',
  dimension_field: '月份',
  measure_field: '销售额',
  aggregation: 'sum',
} as unknown as ChartConfig

const MISSING = { ...VALID, dimension_field: '' } as unknown as ChartConfig

describe('ChartCard 容器与 ECharts 的 DOM 归属', () => {
  it('清空必填字段再恢复配置：不抛 removeChild，容器常驻', () => {
    const { rerender, unmount } = renderProviders(<ChartCard cfg={VALID} rows={ROWS} fields={FIELDS} />)

    const container = screen.getByTestId('chart-container')
    expect(container).toHaveAttribute('data-chart-ready', 'true')

    // 清空维度 → 空态覆盖层；容器本身与 ECharts 实例都还在（隐藏）
    rerender(<ChartCard cfg={MISSING} rows={ROWS} fields={FIELDS} />)
    act(() => {})
    expect(screen.getByTestId('chart-empty-config')).toBeInTheDocument()
    expect(screen.getByTestId('chart-container')).toBe(container)
    expect(container).toHaveAttribute('data-chart-ready', 'false')

    // 重新配置字段 → 复用同一容器重新 init，React 不从该容器移除任何节点
    rerender(<ChartCard cfg={VALID} rows={ROWS} fields={FIELDS} />)
    act(() => {})
    expect(screen.getByTestId('chart-container')).toBe(container)
    expect(container).toHaveAttribute('data-chart-ready', 'true')
    expect(screen.queryByTestId('chart-empty-config')).not.toBeInTheDocument()

    unmount()
  })

  it('多轮 有图 ↔ 空态 切换后卸载不抛异常', () => {
    const { rerender, unmount } = renderProviders(<ChartCard cfg={VALID} rows={ROWS} fields={FIELDS} />)
    for (let i = 0; i < 3; i++) {
      rerender(<ChartCard cfg={MISSING} rows={ROWS} fields={FIELDS} />)
      act(() => {})
      rerender(<ChartCard cfg={VALID} rows={ROWS} fields={FIELDS} />)
      act(() => {})
    }
    unmount()
  })
})
