/** TableEmbed 组件测试：引用宽度宿主样式 / 宽度控件可选（ADR 0051）. */

import { describe, expect, it, vi } from 'vitest'
import { http, HttpResponse } from 'msw'
import { fireEvent, screen } from '@testing-library/react'
import { renderProviders } from '@/test/render-providers'
import { server } from '@/test/msw'
import { useDocSettingsStore } from '@/store'
import { DEFAULT_DOC_SETTINGS } from '@/theme/docSettings'
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

  it('未指定 width 参数时按个人设置的表格默认宽度与对齐渲染', async () => {
    // 默认：75% 居中
    const first = renderProviders(
      <TableEmbed workspaceId={10} tableRef={{ tableId: 100, limit: 5 }} />,
    )
    const root = await screen.findByTestId('table-embed-100')
    expect(root).toHaveAttribute('data-width', '75')
    expect(root).toHaveAttribute('data-align', 'center')
    expect(root.style.marginLeft).toBe('auto')
    first.unmount()

    // 个人设置：50% 靠左
    const { updateSettings, resetSettings, ...rest } = useDocSettingsStore.getState()
    void updateSettings
    void resetSettings
    useDocSettingsStore.setState({ ...rest, tableDefaultWidth: 50, tableAlign: 'left' })
    renderProviders(
      <TableEmbed workspaceId={10} tableRef={{ tableId: 100, limit: 5 }} />,
    )
    const left = await screen.findByTestId('table-embed-100')
    expect(left).toHaveAttribute('data-width', '50')
    expect(left).toHaveAttribute('data-align', 'left')
    expect(left.style.marginLeft).toBe('')
    // 复位，避免污染其他用例
    useDocSettingsStore.setState({ ...useDocSettingsStore.getState(), ...DEFAULT_DOC_SETTINGS })
  })

  it('link 字段显示摘要值而非原始 JSON', async () => {
    server.use(
      http.get('/api/v1/workspaces/10/tables/100', () =>
        HttpResponse.json({
          id: 100,
          workspace_id: 10,
          name: '合同表',
          fields: [
            { id: 1000, name: '合同编号', field_type: 'text', order: 0 },
            { id: 1001, name: '关联客户', field_type: 'link', order: 1 },
          ],
          views: [],
        }),
      ),
      http.get('/api/v1/workspaces/10/tables/100/records', () =>
        HttpResponse.json({
          items: [
            {
              id: 1,
              合同编号: 'KT2026002',
              关联客户: [{ id: 36, value: 'KT2026002', match: 'KT2026002' }],
            },
          ],
          total: 1,
          offset: 0,
          limit: 5,
        }),
      ),
    )
    renderProviders(<TableEmbed workspaceId={10} tableRef={{ tableId: 100, limit: 5, width: 75 }} />)
    const cells = await screen.findAllByText(
      (_content, el) => el?.tagName === 'TD' && el.textContent === 'KT2026002',
    )
    expect(cells.length).toBe(2)
    expect(screen.queryByText(/\[\{/)).toBeNull()
  })
})
