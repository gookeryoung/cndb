/** TableEmbed 组件测试：引用宽度宿主样式 / 宽度控件可选（ADR 0051）. */

import { describe, expect, it, vi } from 'vitest'
import { fireEvent, screen } from '@testing-library/react'
import { renderProviders } from '@/test/render-providers'
import TableEmbed from './TableEmbed'

describe('TableEmbed', () => {
  it('按 width 设置宿主宽度：缺省 75%，自定义 50%', async () => {
    const first = renderProviders(
      <TableEmbed workspaceId={10} tableRef={{ tableId: 100, limit: 5, width: 75 }} />,
    )
    const root = await screen.findByTestId('table-embed-100')
    expect(root).toHaveAttribute('data-width', '75')
    expect(root.style.width).toBe('75%')
    first.unmount()

    renderProviders(
      <TableEmbed workspaceId={10} tableRef={{ tableId: 100, limit: 5, width: 50 }} />,
    )
    const narrow = await screen.findByTestId('table-embed-100')
    expect(narrow).toHaveAttribute('data-width', '50')
    expect(narrow.style.width).toBe('50%')
  })

  it('不传 onWidthChange 时不渲染控件；传入后预设选择透传百分比', async () => {
    const first = renderProviders(
      <TableEmbed workspaceId={10} tableRef={{ tableId: 100, limit: 5, width: 75 }} />,
    )
    await screen.findByTestId('table-embed-100')
    expect(screen.queryByTestId('table-embed-width-100-0')).toBeNull()
    first.unmount()

    const onWidthChange = vi.fn()
    renderProviders(
      <TableEmbed
        workspaceId={10}
        tableRef={{ tableId: 100, limit: 5, width: 75 }}
        refOrdinal={1}
        onWidthChange={onWidthChange}
      />,
    )
    await screen.findByTestId('table-embed-100')
    fireEvent.click(screen.getByTestId('table-embed-width-100-1'))
    fireEvent.click(await screen.findByTestId('table-embed-width-100-1-preset-50'))
    expect(onWidthChange).toHaveBeenCalledWith(50)
  })
})
