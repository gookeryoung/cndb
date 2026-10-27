import { render, screen, fireEvent } from '@testing-library/react'
import { renderHook, act } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { useRowBatch, VIEW_BATCH_SIZE, ViewBatchFooter } from './rowBatch'

function makeRows(n: number) {
  return Array.from({ length: n }, (_, i) => ({ id: i + 1 }))
}

describe('useRowBatch（ADR 0046 D7）', () => {
  it('只暴露第一批行，其余按批追加', () => {
    const rows = makeRows(VIEW_BATCH_SIZE + 50)
    const { result } = renderHook(() => useRowBatch(rows))
    expect(result.current.visibleRows).toHaveLength(VIEW_BATCH_SIZE)
    expect(result.current.remaining).toBe(50)
    expect(result.current.total).toBe(VIEW_BATCH_SIZE + 50)
    act(() => result.current.loadMore())
    expect(result.current.visibleRows).toHaveLength(rows.length)
    expect(result.current.remaining).toBe(0)
  })

  it('行数不超过一批时全量可见', () => {
    const rows = makeRows(10)
    const { result } = renderHook(() => useRowBatch(rows))
    expect(result.current.visibleRows).toHaveLength(10)
    expect(result.current.remaining).toBe(0)
  })

  it('rows 变化时回到第一批（切表 / 切视图不保留旧批次）', () => {
    const rows = makeRows(VIEW_BATCH_SIZE + 5)
    const { result, rerender } = renderHook(({ data }) => useRowBatch(data), {
      initialProps: { data: rows },
    })
    act(() => result.current.loadMore())
    expect(result.current.remaining).toBe(0)
    rerender({ data: makeRows(VIEW_BATCH_SIZE * 2) })
    expect(result.current.visibleRows).toHaveLength(VIEW_BATCH_SIZE)
    expect(result.current.remaining).toBe(VIEW_BATCH_SIZE)
  })

  it('支持自定义批大小', () => {
    const rows = makeRows(10)
    const { result } = renderHook(() => useRowBatch(rows, 4))
    expect(result.current.visibleRows).toHaveLength(4)
    act(() => result.current.loadMore())
    expect(result.current.visibleRows).toHaveLength(8)
  })
})

describe('ViewBatchFooter', () => {
  it('不超过一批时不渲染', () => {
    const { container } = render(<ViewBatchFooter remaining={0} total={VIEW_BATCH_SIZE} onLoadMore={() => {}} />)
    expect(container.firstChild).toBeNull()
  })

  it('有剩余时渲染加载更多并可点击', () => {
    let clicked = 0
    render(<ViewBatchFooter remaining={120} total={VIEW_BATCH_SIZE + 120} onLoadMore={() => { clicked += 1 }} />)
    const btn = screen.getByTestId('view-load-more')
    expect(btn.textContent).toContain('120')
    fireEvent.click(btn)
    expect(clicked).toBe(1)
  })

  it('全部加载后显示已显示全部', () => {
    render(<ViewBatchFooter remaining={0} total={VIEW_BATCH_SIZE + 10} onLoadMore={() => {}} />)
    expect(screen.queryByTestId('view-load-more')).toBeNull()
    expect(screen.getByTestId('view-batch-footer').textContent).toContain('已显示全部')
  })
})
