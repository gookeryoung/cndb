/**
 * buildColumns 单元测试 —— Grid 列构建.
 *
 * 覆盖：hidden 字段过滤 / order 排序 / 排序指示（sortOrder 受控）/
 * 过滤图标提示 / 单元格渲染 GridCell / 行内编辑操作列（编辑/保存/取消）。
 */

import { describe, expect, it, vi } from 'vitest'
import { fireEvent, screen } from '@testing-library/react'
import { Table } from 'antd'
import { buildColumns, type RowInlineOps } from './buildColumns'
import { renderProviders } from '@/test/render-providers'
import { makeField } from '@/test/fixtures'
import type { Field, RowResponse } from '@/api'

const FIELDS: Field[] = [
  makeField({ id: 2, name: '年龄', field_type: 'number', order: 1 }),
  makeField({ id: 1, name: '姓名', field_type: 'text', order: 0, required: true }),
  makeField({ id: 3, name: '隐藏列', field_type: 'text', order: 2, hidden: true }),
]

const ROWS: RowResponse[] = [
  { id: 1, 姓名: '张三', 年龄: 20 },
  { id: 2, 姓名: '李四', 年龄: 25 },
]

/** 在真实 antd Table 中渲染 buildColumns 产物，贴近生产行为 */
function renderGrid(fields: Field[], opts?: {
  sortings?: Array<{ field_name: string; direction: 'asc' | 'desc' }>
  filters?: Array<{ field_name: string; op: string; value?: unknown }>
  inlineOps?: RowInlineOps
}) {
  const columns = buildColumns(
    fields, 10,
    opts?.sortings ?? [], opts?.filters ?? [],
    () => { }, () => { },
    undefined,
    opts?.inlineOps,
  )
  return renderProviders(<Table rowKey="id" columns={columns} dataSource={ROWS} pagination={false} />)
}

describe('buildColumns 列构建', () => {
  it('hidden 字段被过滤，其余按 order 升序排列', () => {
    const columns = buildColumns(FIELDS, 10, [], [], () => { }, () => { })
    expect(columns.map(c => c.key)).toEqual(['1', '2'])
  })

  it('渲染表头：字段名 + 必填星号，且按 order 输出列顺序', () => {
    renderGrid(FIELDS)
    const headers = screen.getAllByRole('columnheader')
    expect(headers[0]).toHaveTextContent('姓名')
    expect(headers[1]).toHaveTextContent('年龄')
    expect(screen.getByText('*')).toBeInTheDocument()
  })

  it('排序规则受控 sortOrder：asc → 升序箭头渲染', () => {
    renderGrid(FIELDS, { sortings: [{ field_name: '年龄', direction: 'asc' }] })
    const headers = screen.getAllByRole('columnheader')
    expect(headers[1]).toHaveTextContent('年龄')
    // buildColumns 为有排序规则的列渲染受控箭头图标（SortAscendingOutlined）
    expect(headers[1].querySelector('.anticon-sort-ascending')).not.toBeNull()
  })

  it('视图过滤规则使表头出现过滤图标', () => {
    renderGrid(FIELDS, { filters: [{ field_name: '姓名', op: 'contains', value: '张' }] })
    // 字段名内层 span 的父级（inline-flex 外层 span）才承载过滤图标
    const header = screen.getByText('姓名').parentElement as HTMLElement
    expect(header.querySelector('.anticon-filter')).not.toBeNull()
  })

  it('单元格经 GridCell 渲染行数据', () => {
    renderGrid(FIELDS)
    expect(screen.getByText('张三')).toBeInTheDocument()
    expect(screen.getByText('20')).toBeInTheDocument()
  })

  it('提供 inlineOps 时追加操作列：普通行显示编辑按钮并回调 onEdit', () => {
    const onEdit = vi.fn()
    const inlineOps: RowInlineOps = {
      getInlineEdit: () => null,
      onEdit, onSave: vi.fn(), onCancel: vi.fn(),
    }
    renderGrid(FIELDS, { inlineOps })

    const editButtons = screen.getAllByTestId('row-edit-btn')
    expect(editButtons).toHaveLength(2)
    fireEvent.click(editButtons[0])
    expect(onEdit).toHaveBeenCalledWith(1)
  })

  it('编辑中的行显示保存/取消按钮并回调对应方法', () => {
    const onSave = vi.fn()
    const onCancel = vi.fn()
    const inlineOps: RowInlineOps = {
      getInlineEdit: (record) => record.id === 1
        ? {
          editing: true,
          values: { 姓名: '张三草稿' },
          onFieldChange: () => { }, onFieldCommit: () => { }, onFieldCancel: () => { },
        }
        : null,
      onEdit: vi.fn(), onSave, onCancel,
    }
    renderGrid(FIELDS, { inlineOps })

    // 受控行内编辑：草稿值渲染进 Input（值在 input.value 而非文本节点）
    expect(screen.getByDisplayValue('张三草稿')).toBeInTheDocument()
    fireEvent.click(screen.getByTestId('row-save-btn'))
    expect(onSave).toHaveBeenCalledWith(1)
    fireEvent.click(screen.getByTestId('row-cancel-btn'))
    expect(onCancel).toHaveBeenCalledWith(1)
    // 未编辑行仍是编辑按钮
    expect(screen.getAllByTestId('row-edit-btn')).toHaveLength(1)
  })

  describe('表头状态标识（必填/唯一/关联/引用）', () => {
    it('必填字段表头显示红星号', () => {
      const requiredFields: Field[] = [makeField({ id: 1, name: '必填字段', field_type: 'text', required: true })]
      renderGrid(requiredFields)
      expect(screen.getByTestId('header-flag-required')).toBeInTheDocument()
    })

    it('唯一字段表头显示金橙 KeyOutlined 图标', () => {
      const uniqueFields: Field[] = [makeField({ id: 1, name: '唯一字段', field_type: 'text', is_unique: true })]
      renderGrid(uniqueFields)
      expect(screen.getByTestId('header-flag-唯一')).toBeInTheDocument()
      const icon = document.querySelector('.anticon-key')
      expect(icon).not.toBeNull()
    })

    it('关联字段表头显示品红 LinkOutlined 图标', () => {
      const linkFields: Field[] = [makeField({ id: 1, name: '客户', field_type: 'link' })]
      renderGrid(linkFields)
      expect(screen.getByTestId('header-flag-关联')).toBeInTheDocument()
      const icon = document.querySelector('.anticon-link')
      expect(icon).not.toBeNull()
    })

    it('引用字段表头显示紫 BulbOutlined 图标', () => {
      const lookupFields: Field[] = [makeField({ id: 1, name: '客户名称', field_type: 'lookup' })]
      renderGrid(lookupFields)
      expect(screen.getByTestId('header-flag-引用')).toBeInTheDocument()
      const icon = document.querySelector('.anticon-bulb')
      expect(icon).not.toBeNull()
    })

    it('普通字段（非必填/唯一/关联/引用）不渲染任何标识', () => {
      const plainFields: Field[] = [makeField({ id: 1, name: '普通字段', field_type: 'number' })]
      renderGrid(plainFields)
      expect(screen.queryByTestId('header-flag-required')).toBeNull()
      expect(screen.queryByTestId('header-flag-唯一')).toBeNull()
      expect(screen.queryByTestId('header-flag-关联')).toBeNull()
      expect(screen.queryByTestId('header-flag-引用')).toBeNull()
    })
  })
})
