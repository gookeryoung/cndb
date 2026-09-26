/**
 * gridTableSection 表头排序回归测试 —— 复现「多次点击无法取消排序」缺陷。
 *
 * 模拟生产逻辑：buildColumns 受控 sortOrder + GridPage 的 onSort 处理
 * （asc → desc → null 循环，null 时移除该字段排序规则）。
 */

import { describe, expect, it, vi } from 'vitest'
import { fireEvent, screen } from '@testing-library/react'
import { useState } from 'react'
import GridTableSection from './gridTableSection'
import { buildColumns } from './cells/buildColumns'
import { renderProviders } from '@/test/render-providers'
import { makeField } from '@/test/fixtures'
import type { Field, RowResponse } from '@/api'
import type { SortRule } from './view-config/ViewConfigDialog'

const FIELDS: Field[] = [
  makeField({ id: 1, name: '姓名', field_type: 'text', order: 0 }),
  makeField({ id: 2, name: '年龄', field_type: 'number', order: 1 }),
]

const ROWS: RowResponse[] = [
  { id: 1, 姓名: '张三', 年龄: 20 },
  { id: 2, 姓名: '李四', 年龄: 25 },
]

/** 受控排序 harness —— 与 GridPage.tsx onSort 逻辑一致 */
function Harness({ onSortChange }: { onSortChange: (field: string, direction: 'asc' | 'desc' | null) => void }) {
  const [sortings, setSortings] = useState<SortRule[]>([])
  const columns = buildColumns(FIELDS, 10, sortings, [], () => { }, () => { })
  return (
    <GridTableSection
      tableRef={{ current: null }}
      columns={columns}
      settings={{ density: 'comfortable', bordered: false, showHeader: true, striped: false }}
      isLoading={false}
      rows={ROWS}
      total={ROWS.length}
      newRowActive={false}
      newRowPosition="top"
      canEditRecords={true}
      selectedRowKeys={[]}
      onSelectionChange={() => { }}
      onAddRow={() => { }}
      onRowDoubleClick={() => { }}
      onSort={(field, direction) => {
        onSortChange(field, direction)
        if (direction === null) {
          setSortings(prev => prev.filter(sr => sr.field_name !== field))
        } else {
          setSortings(prev => {
            const without = prev.filter(sr => sr.field_name !== field)
            return [{ field_name: field, direction }, ...without]
          })
        }
      }}
      gridAreaSize={{ width: 1200, height: 600 }}
      offset={0}
      limit={50}
      onPageChange={() => { }}
      prefetchNext={() => { }}
    />
  )
}

describe('gridTableSection 表头排序三态循环', () => {
  it('连续点击表头：asc → desc → null（取消）', () => {
    const onSortChange = vi.fn()
    renderProviders(<Harness onSortChange={onSortChange} />)
    const header = screen.getByText('年龄').closest('th') as HTMLElement
    expect(header).not.toBeNull()

    // 第 1 次：升序
    fireEvent.click(header)
    expect(onSortChange).toHaveBeenLastCalledWith('年龄', 'asc')
    // 第 2 次：降序
    fireEvent.click(header)
    expect(onSortChange).toHaveBeenLastCalledWith('年龄', 'desc')
    // 第 3 次：取消
    fireEvent.click(header)
    expect(onSortChange).toHaveBeenLastCalledWith('年龄', null)
  })
})
