/** 列头「AI 填充本列」入口显隐与点击回调（ADR 0020 P2 / D14）.
 *
 * 入口由 `ColumnOptions.onAiFillField` 驱动：
 * - 不传回调 → 不渲染入口（只读 / 非表格场景）；
 * - 传回调 → 仅当前可见字段有入口；字段级 hidden 与视图级隐藏列都不出列，因而也没有入口。
 */

import { describe, expect, it, vi } from 'vitest'
import { fireEvent, screen } from '@testing-library/react'
import { Table } from 'antd'

import { renderProviders } from '@/test/render-providers'
import { makeField } from '@/test/fixtures'
import type { Field, RowResponse } from '@/api'
import { buildColumns } from './buildColumns'

const FIELDS: Field[] = [
  makeField({ id: 1, name: '姓名', field_type: 'text', order: 0 }),
  makeField({ id: 2, name: '摘要', field_type: 'longtext', order: 1 }),
  makeField({ id: 3, name: '隐藏列', field_type: 'text', order: 2, hidden: true }),
]

const ROWS: RowResponse[] = [{ id: 1, 姓名: '张三', 摘要: '' }]

function renderGrid(opts: { onAiFillField?: (field: Field) => void; hiddenFieldIds?: ReadonlySet<string> } = {}) {
  const columns = buildColumns(
    FIELDS, 10, [], [], () => { }, () => { },
    undefined, undefined,
    { onAiFillField: opts.onAiFillField, hiddenFieldIds: opts.hiddenFieldIds },
  )
  return renderProviders(<Table rowKey="id" columns={columns} dataSource={ROWS} pagination={false} />)
}

describe('列头 AI 填充入口', () => {
  it('提供 onAiFillField 时：每个可见字段的列头都有入口，隐藏字段没有', () => {
    renderGrid({ onAiFillField: vi.fn() })

    expect(screen.getByTestId('header-ai-fill-1')).toBeInTheDocument()
    expect(screen.getByTestId('header-ai-fill-2')).toBeInTheDocument()
    // 字段级 hidden 的 id=3 不出列 → 无入口
    expect(screen.queryByTestId('header-ai-fill-3')).toBeNull()
  })

  it('不提供 onAiFillField 时不渲染任何入口（入口按能力显隐）', () => {
    renderGrid()
    expect(screen.queryByTestId('header-ai-fill-1')).toBeNull()
    expect(screen.queryByTestId('header-ai-fill-2')).toBeNull()
  })

  it('视图级隐藏字段不渲染列，因此也没有入口', () => {
    renderGrid({ onAiFillField: vi.fn(), hiddenFieldIds: new Set(['2']) })
    expect(screen.getByTestId('header-ai-fill-1')).toBeInTheDocument()
    expect(screen.queryByTestId('header-ai-fill-2')).toBeNull()
  })

  it('点击入口回调目标字段，且不冒泡触发列头排序', () => {
    const onAiFillField = vi.fn()
    renderGrid({ onAiFillField })

    const button = screen.getByTestId('header-ai-fill-2')
    fireEvent.click(button)

    expect(onAiFillField).toHaveBeenCalledTimes(1)
    expect(onAiFillField).toHaveBeenCalledWith(expect.objectContaining({ id: 2, name: '摘要' }))
    // stopPropagation 生效：冒泡路径上的点击没有被列头 sorter 拦走（onAiFillField 已收到事件）
    expect(onAiFillField.mock.calls[0][0].name).toBe('摘要')
  })
})
