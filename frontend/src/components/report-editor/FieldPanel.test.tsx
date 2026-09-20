/**
 * FieldPanel 组件测试 —— 报告模板字段面板（单表 / 多表）.
 *
 * 覆盖：单表字段列表与点击插入 / 搜索过滤与空态 / 多表 Tab 与额外表 records_by_table 语法。
 * useSortable 需要 DndContext + SortableContext 包裹。
 */

import { describe, expect, it, vi } from 'vitest'
import { DndContext } from '@dnd-kit/core'
import { SortableContext, verticalListSortingStrategy } from '@dnd-kit/sortable'
import { fireEvent, screen } from '@testing-library/react'
import FieldPanel, { type TableFieldGroup } from './FieldPanel'
import { renderProviders } from '@/test/render-providers'
import { makeField } from '@/test/fixtures'
import type { Field } from '@/api'

/** FieldPanel 自身不含 DndContext，测试需手动包裹 */
function renderPanel(props: { fields?: Field[]; tableGroups?: TableFieldGroup[]; onInsert: (v: string) => void }) {
  const ids = (props.tableGroups
    ? props.tableGroups.flatMap(g => g.fields)
    : props.fields || []
  ).map(f => `field-${f.id}`)
  return renderProviders(
    <DndContext>
      <SortableContext items={ids} strategy={verticalListSortingStrategy}>
        <FieldPanel {...props} />
      </SortableContext>
    </DndContext>,
  )
}

describe('FieldPanel 字段面板', () => {
  it('单表模式：渲染字段数与字段项，点击插入纯字段名', () => {
    const onInsert = vi.fn()
    const fields = [
      makeField({ id: 1, name: '姓名', field_type: 'text' }),
      makeField({ id: 2, name: '年龄', field_type: 'number' }),
    ]
    renderPanel({ fields, onInsert })

    expect(screen.getByText('字段 (2)')).toBeInTheDocument()
    expect(screen.getByText('姓名')).toBeInTheDocument()
    expect(screen.getByText('年龄')).toBeInTheDocument()

    fireEvent.click(screen.getByText('姓名'))
    expect(onInsert).toHaveBeenCalledWith('姓名')
  })

  it('字段超过 10 个显示搜索框并可过滤', () => {
    const onInsert = vi.fn()
    const fields = Array.from({ length: 12 }, (_, i) =>
      makeField({ id: i + 1, name: `字段${i + 1}`, field_type: 'text' }))
    renderPanel({ fields, onInsert })

    const search = screen.getByPlaceholderText('搜索字段')
    fireEvent.change(search, { target: { value: '字段12' } })

    expect(screen.getByText('字段12')).toBeInTheDocument()
    expect(screen.queryByText('字段1' + '0')).not.toBeInTheDocument()
  })

  it('搜索无匹配显示空态提示', () => {
    const fields = Array.from({ length: 12 }, (_, i) =>
      makeField({ id: i + 1, name: `字段${i + 1}`, field_type: 'text' }))
    renderPanel({ fields, onInsert: () => { } })

    fireEvent.change(screen.getByPlaceholderText('搜索字段'), { target: { value: '不存在' } })
    expect(screen.getByText('未找到匹配字段')).toBeInTheDocument()
  })

  it('无字段时显示空态', () => {
    renderPanel({ fields: [], onInsert: () => { } })

    expect(screen.getByText('该表暂无字段')).toBeInTheDocument()
  })

  it('多表模式：渲染表 Tab 与主表标记，主表字段点击插入纯字段名', () => {
    const onInsert = vi.fn()
    const tableGroups: TableFieldGroup[] = [
      { tableId: 1, tableName: '客户表', isPrimary: true, fields: [makeField({ id: 1, name: '姓名', field_type: 'text' })] },
      { tableId: 2, tableName: '员工表', fields: [makeField({ id: 2, name: '员工名', field_type: 'text' })] },
    ]
    renderPanel({ tableGroups, onInsert })

    expect(screen.getByText('字段（多表）')).toBeInTheDocument()
    expect(screen.getByText('客户表')).toBeInTheDocument()
    expect(screen.getByText('主')).toBeInTheDocument()
    // 默认激活主表分组
    expect(screen.getByText('姓名')).toBeInTheDocument()

    fireEvent.click(screen.getByText('姓名'))
    expect(onInsert).toHaveBeenCalledWith('姓名')
  })

  it('多表模式：切到额外表后点击字段插入 records_by_table 完整表达式', () => {
    const onInsert = vi.fn()
    const tableGroups: TableFieldGroup[] = [
      { tableId: 1, tableName: '客户表', isPrimary: true, fields: [makeField({ id: 1, name: '姓名', field_type: 'text' })] },
      { tableId: 2, tableName: '员工表', fields: [makeField({ id: 2, name: '员工名', field_type: 'text' })] },
    ]
    renderPanel({ tableGroups, onInsert })

    fireEvent.click(screen.getByText('员工表'))
    expect(screen.getByText('员工名')).toBeInTheDocument()

    fireEvent.click(screen.getByText('员工名'))
    expect(onInsert).toHaveBeenCalledWith("{{ records_by_table['员工表'][0].员工名 }}")
  })
})
