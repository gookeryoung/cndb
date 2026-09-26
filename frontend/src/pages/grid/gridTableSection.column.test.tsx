/**
 * gridTableSection 列宽拖拽 + 列序拖放测试。
 *
 * 覆盖：
 *   1. buildColumns 类型化估算宽度 / 视图级覆盖 / applyFieldOrder 列序
 *   2. 表头右缘热区拖宽 → onColumnResize 回调，且不误触排序
 *   3. 表头 HTML5 拖放 → onColumnOrderMove 回调
 */

import { describe, expect, it, vi, beforeAll, afterAll } from 'vitest'
import { fireEvent, screen } from '@testing-library/react'
import GridTableSection from './gridTableSection'
import { buildColumns, estimateColumnWidth, applyFieldOrder, MIN_COLUMN_WIDTH, MAX_COLUMN_WIDTH } from './cells/buildColumns'
import { renderProviders } from '@/test/render-providers'
import { makeField } from '@/test/fixtures'
import type { Field, RowResponse } from '@/api'

const FIELDS: Field[] = [
  makeField({ id: 1, name: '姓名', field_type: 'text', order: 0 }),
  makeField({ id: 2, name: '年龄', field_type: 'number', order: 1 }),
  makeField({ id: 3, name: '备注说明信息', field_type: 'longtext', order: 2 }),
]

const ROWS: RowResponse[] = [
  { id: 1, 姓名: '张三', 年龄: 20 },
  { id: 2, 姓名: '李四', 年龄: 25 },
]

describe('estimateColumnWidth 类型化估算', () => {
  it('不同类型取不同基础宽度；长字段名有加宽修正', () => {
    expect(estimateColumnWidth({ name: '备注说明信息', field_type: 'longtext' }))
      .toBeGreaterThan(estimateColumnWidth({ name: '年龄', field_type: 'number' }))
    // boolean 更窄
    expect(estimateColumnWidth({ name: '是否', field_type: 'boolean' })).toBeLessThan(160)
    // 未命中类型回退 160
    expect(estimateColumnWidth({ name: '其他', field_type: 'no_such_type' as Field['field_type'] })).toBe(160)
    // 表头超 4 字每字 +14，封顶 +60
    expect(estimateColumnWidth({ name: '一个特别特别长的字段名称', field_type: 'number' }))
      .toBe(130 + 60)
  })
})

describe('buildColumns 视图级宽度覆盖与列序', () => {
  it('columnWidths 覆盖默认宽度；非法值回退估算', () => {
    const cols = buildColumns(FIELDS, 10, [], [], () => { }, () => { }, undefined, undefined, {
      columnWidths: { '1': 300, '2': 'not-a-number' } as unknown as Record<string, number>,
    })
    expect(cols[0].width).toBe(300)
    expect(cols[1].width).toBe(estimateColumnWidth(FIELDS[1]))
  })

  it('宽度夹取到 [MIN, MAX]', () => {
    const cols = buildColumns(FIELDS, 10, [], [], () => { }, () => { }, undefined, undefined, {
      columnWidths: { '1': 5, '2': 99999 },
    })
    expect(cols[0].width).toBe(MIN_COLUMN_WIDTH)
    expect(cols[1].width).toBe(MAX_COLUMN_WIDTH)
  })

  it('fieldOrder 重排列顺序；缺项字段按 order 追加；未知 id 忽略', () => {
    const ordered = applyFieldOrder(FIELDS, ['3', '999', '1'])
    expect(ordered.map(f => f.id)).toEqual([3, 1, 2])
    // 缺省时保持原顺序
    expect(applyFieldOrder(FIELDS, undefined).map(f => f.id)).toEqual([1, 2, 3])
    // 端到端：buildColumns 列 key 顺序与 fieldOrder 一致
    const cols = buildColumns(FIELDS, 10, [], [], () => { }, () => { }, undefined, undefined, {
      fieldOrder: ['3', '2', '1'],
    })
    expect(cols.map(c => c.key)).toEqual(['3', '2', '1'])
  })
})

/** jsdom 无布局 —— 固定 th 宽度 200，使右缘热区判定可预测 */
const fixedRect = {
  width: 200, height: 40, top: 0, left: 0, bottom: 40, right: 200, x: 0, y: 0, toJSON: () => ({}),
}

describe('gridTableSection 表头交互：调宽 / 列序', () => {
  let originalRect: typeof Element.prototype.getBoundingClientRect
  beforeAll(() => {
    originalRect = Element.prototype.getBoundingClientRect
    Element.prototype.getBoundingClientRect = () => ({ ...fixedRect })
  })
  afterAll(() => {
    Element.prototype.getBoundingClientRect = originalRect
  })

  function Harness({ onResize, onOrderMove }: {
    onResize?: (fieldId: string, width: number) => void
    onOrderMove?: (src: string, target: string) => void
  }) {
    const columns = buildColumns(FIELDS, 10, [], [], () => { }, () => { })
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
        onSort={() => { }}
        onColumnResize={onResize}
        onColumnOrderMove={onOrderMove}
        gridAreaSize={{ width: 1200, height: 600 }}
        offset={0}
        limit={50}
        onPageChange={() => { }}
        prefetchNext={() => { }}
      />
    )
  }

  it('右缘热区拖宽：mouseup 后回调夹取后的宽度，且不触发排序', () => {
    const onResize = vi.fn()
    const onSort = vi.fn()
    const columns = buildColumns(FIELDS, 10, [], [], () => { }, () => { })
    renderProviders(
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
        onSort={onSort}
        onColumnResize={onResize}
        gridAreaSize={{ width: 1200, height: 600 }}
        offset={0}
        limit={50}
        onPageChange={() => { }}
        prefetchNext={() => { }}
      />,
    )
    const header = screen.getByText('年龄').closest('th') as HTMLElement
    // 年龄列（number）宽度 130；rect.right=200 —— clientX=196 在热区内
    fireEvent.mouseDown(header, { clientX: 196 })
    // 拖到 250 → 宽度 130 + (250-196) = 184
    fireEvent.mouseMove(document, { clientX: 250 })
    fireEvent.mouseUp(document, { clientX: 250 })
    expect(onResize).toHaveBeenCalledWith('2', 184)
    // 拖宽后的 click 被吞掉，不触发排序
    fireEvent.click(header)
    expect(onSort).not.toHaveBeenCalled()
  })

  it('热区外 mousedown 不启动 resize（点击排序正常）', () => {
    const onResize = vi.fn()
    const onSort = vi.fn()
    const columns = buildColumns(FIELDS, 10, [], [], () => { }, () => { })
    renderProviders(
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
        onSort={onSort}
        onColumnResize={onResize}
        gridAreaSize={{ width: 1200, height: 600 }}
        offset={0}
        limit={50}
        onPageChange={() => { }}
        prefetchNext={() => { }}
      />,
    )
    const header = screen.getByText('年龄').closest('th') as HTMLElement
    fireEvent.mouseDown(header, { clientX: 50 })
    fireEvent.mouseMove(document, { clientX: 150 })
    fireEvent.mouseUp(document, { clientX: 150 })
    expect(onResize).not.toHaveBeenCalled()
    // 非热区点击正常触发排序三态循环的第一步
    fireEvent.click(header)
    expect(onSort).toHaveBeenCalledWith('年龄', 'asc')
  })

  it('双击右缘热区：回调 onColumnResetWidth；双击热区外不回调', () => {
    const onResetWidth = vi.fn()
    const columns = buildColumns(FIELDS, 10, [], [], () => { }, () => { })
    renderProviders(
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
        onSort={() => { }}
        onColumnResetWidth={onResetWidth}
        gridAreaSize={{ width: 1200, height: 600 }}
        offset={0}
        limit={50}
        onPageChange={() => { }}
        prefetchNext={() => { }}
      />,
    )
    const header = screen.getByText('年龄').closest('th') as HTMLElement
    // 双击热区内（clientX=196，rect.right=200）
    fireEvent.doubleClick(header, { clientX: 196 })
    expect(onResetWidth).toHaveBeenCalledWith('2')
    // 双击热区外（clientX=50）
    fireEvent.doubleClick(header, { clientX: 50 })
    expect(onResetWidth).toHaveBeenCalledTimes(1)
  })

  it('列拖放：dragStart 姓名 → drop 年龄 → onColumnOrderMove("1","2")', () => {
    const onOrderMove = vi.fn()
    const dataTransfer = { setData: vi.fn(), effectAllowed: '', dropEffect: '' }
    renderProviders(<Harness onOrderMove={onOrderMove} />)
    const src = screen.getByText('姓名').closest('th') as HTMLElement
    const target = screen.getByText('年龄').closest('th') as HTMLElement
    fireEvent.dragStart(src, { dataTransfer })
    fireEvent.dragOver(target, { dataTransfer })
    fireEvent.drop(target, { dataTransfer })
    expect(onOrderMove).toHaveBeenCalledWith('1', '2')
  })

  it('拖到自身不触发回调', () => {
    const onOrderMove = vi.fn()
    const dataTransfer = { setData: vi.fn(), effectAllowed: '', dropEffect: '' }
    renderProviders(<Harness onOrderMove={onOrderMove} />)
    const src = screen.getByText('姓名').closest('th') as HTMLElement
    fireEvent.dragStart(src, { dataTransfer })
    fireEvent.drop(src, { dataTransfer })
    expect(onOrderMove).not.toHaveBeenCalled()
  })
})
