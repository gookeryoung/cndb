/** FormulaPanel 单测 —— 窗口函数快捷片段与「分区 / 排序」选择器. */

import { describe, expect, it, vi } from 'vitest'
import { fireEvent, screen, within } from '@testing-library/react'
import { useState } from 'react'
import { FormulaPanel } from './FormulaPanel'
import { renderProviders } from '@/test/render-providers'
import type { AnalyticsFormula } from '@/api/analytics'

const FIELDS = ['symbol', 'day', 'close']

/** 受控包装：把 onChange 回写到本地 state，便于断言与交互 */
function Harness({ initial }: { initial: AnalyticsFormula[] }) {
  const [formulas, setFormulas] = useState<AnalyticsFormula[]>(initial)
  return (
    <FormulaPanel
      tableFields={FIELDS}
      numericFields={['close']}
      formulas={formulas}
      errors={{}}
      onChange={setFormulas}
      onRun={vi.fn()}
      canRun
      running={false}
    />
  )
}

describe('FormulaPanel 窗口函数支持', () => {
  it('普通公式不显示分区 / 排序选择器', () => {
    renderProviders(<Harness initial={[{ key: 'a', label: '', expr: 'round([close] * 2, 1)' }]} />)
    expect(screen.queryByTestId('analytics-formula-window-0')).not.toBeInTheDocument()
  })

  it('表达式含窗口函数时显示分区 / 排序选择器', () => {
    renderProviders(<Harness initial={[{ key: 'ma', label: '', expr: 'ma([close], 3)' }]} />)
    const windowRow = within(screen.getByTestId('analytics-formula-window-0'))
    // antd Select 的 aria-label 同时落在外层与内部 input 上，按「至少一个」断言
    expect(windowRow.getAllByLabelText('公式分区字段 1').length).toBeGreaterThan(0)
    expect(windowRow.getAllByLabelText('公式排序字段 1').length).toBeGreaterThan(0)
    expect(windowRow.getAllByLabelText('公式排序方向 1').length).toBeGreaterThan(0)
  })

  it('输入窗口函数后选择器即时出现', () => {
    renderProviders(<Harness initial={[{ key: 'a', label: '', expr: '' }]} />)
    expect(screen.queryByTestId('analytics-formula-window-0')).not.toBeInTheDocument()
    fireEvent.change(screen.getByTestId('analytics-formula-expr-0'), {
      target: { value: 'pct_change([close])' },
    })
    expect(screen.getByTestId('analytics-formula-window-0')).toBeInTheDocument()
  })

  it('回填已保存的分区 / 排序字段', () => {
    renderProviders(
      <Harness
        initial={[
          {
            key: 'ma',
            label: '均线',
            expr: 'ma([close], 3)',
            partition_by: 'symbol',
            order_by: 'day',
            order_desc: true,
          },
        ]}
      />,
    )
    const windowRow = within(screen.getByTestId('analytics-formula-window-0'))
    expect(windowRow.getByText('symbol')).toBeInTheDocument()
    expect(windowRow.getByText('day')).toBeInTheDocument()
    expect(windowRow.getByText('降序')).toBeInTheDocument()
  })

  it('快捷片段可插入窗口函数骨架', () => {
    renderProviders(<Harness initial={[{ key: 'a', label: '', expr: '' }]} />)
    fireEvent.click(screen.getByText('pct_change'))
    expect(screen.getByTestId('analytics-formula-expr-0')).toHaveValue('pct_change([close])')
  })

  it('滚动函数片段带窗口长度', () => {
    renderProviders(<Harness initial={[{ key: 'a', label: '', expr: '' }]} />)
    fireEvent.click(screen.getByText('rolling_std'))
    expect(screen.getByTestId('analytics-formula-expr-0')).toHaveValue('rolling_std([close], 3)')
  })
})
