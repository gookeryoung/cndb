import { describe, expect, it, vi } from 'vitest'
import { fireEvent, screen } from '@testing-library/react'
import { renderProviders } from '@/test/render-providers'
import GlobalFilterBar from './GlobalFilterBar'
import type { DashboardGlobalFilter } from './dashboardModel'

const FILTERS: DashboardGlobalFilter[] = [
  { id: 'range', kind: 'date_range', field: '日期', label: '时间范围' },
  { id: 'cat', kind: 'select', field: '商品类别', label: '类目' },
  { id: 'kw', kind: 'search', field: '订单号', label: '单号搜索' },
]

function renderBar(values: Record<string, unknown> = {}) {
  const onChange = vi.fn()
  renderProviders(<GlobalFilterBar filters={FILTERS} values={values} onChange={onChange} />)
  return onChange
}

describe('GlobalFilterBar', () => {
  it('无全局筛选时不渲染容器', () => {
    renderProviders(<GlobalFilterBar filters={[]} values={{}} onChange={vi.fn()} />)
    expect(screen.queryByTestId('dashboard-globals')).not.toBeInTheDocument()
  })

  it('渲染三类控件', () => {
    renderBar()
    // RangePicker 会把 data-testid 透传到起止两个输入框
    expect(screen.getAllByTestId('dashboard-global-range').length).toBeGreaterThan(0)
    expect(screen.getByTestId('dashboard-global-cat')).toBeInTheDocument()
    expect(screen.getByTestId('dashboard-global-kw')).toBeInTheDocument()
  })

  it('搜索输入写回值，清空即删除该键', () => {
    const onChange = renderBar({ kw: 'A00' })
    const input = screen.getByTestId('dashboard-global-kw').querySelector('input') as HTMLInputElement
    fireEvent.change(input, { target: { value: 'A001' } })
    expect(onChange).toHaveBeenLastCalledWith({ kw: 'A001' })
    fireEvent.change(input, { target: { value: '' } })
    expect(onChange).toHaveBeenLastCalledWith({})
  })

  it('清除筛选按钮清空全部值', () => {
    const onChange = renderBar({ kw: 'A00', cat: ['数码'] })
    fireEvent.click(screen.getByTestId('dashboard-globals-reset'))
    expect(onChange).toHaveBeenLastCalledWith({})
  })

  it('无值时隐藏清除按钮', () => {
    renderBar()
    expect(screen.queryByTestId('dashboard-globals-reset')).not.toBeInTheDocument()
  })
})
