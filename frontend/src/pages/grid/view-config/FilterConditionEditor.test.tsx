/**
 * FilterConditionEditor 组件测试 —— 共享筛选条件编辑器（视图筛选 / 行级权限条件共用）.
 *
 * 覆盖：空态与自定义文案 / 逻辑栏开关 / 规则的增删改（字段切换重置操作符与值）/
 * 各值编辑器分派（boolean / number / select / date / text / 无需值）。
 */

import { describe, expect, it, vi } from 'vitest'
import { fireEvent, screen } from '@testing-library/react'
import FilterConditionEditor from './FilterConditionEditor'
import type { FilterRule } from './FilterConditionEditor'
import { renderProviders } from '@/test/render-providers'
import { makeField } from '@/test/fixtures'
import type { Field } from '@/api'

const FIELDS: Field[] = [
  makeField({ id: 1, name: '姓名', field_type: 'text' }),
  makeField({ id: 2, name: '年龄', field_type: 'number' }),
  makeField({ id: 3, name: '状态', field_type: 'select', config: { options: ['高', '中'] } }),
  makeField({ id: 4, name: '完成', field_type: 'boolean' }),
  makeField({ id: 5, name: '日期', field_type: 'date' }),
]

function renderEditor(props?: {
  rules?: FilterRule[]
  logic?: 'AND' | 'OR'
  showLogic?: boolean
  emptyText?: string
  addText?: string
}) {
  const onChange = vi.fn()
  const onLogicChange = vi.fn()
  renderProviders(
    <FilterConditionEditor
      fields={FIELDS}
      rules={props?.rules ?? []}
      onChange={onChange}
      logic={props?.logic ?? 'AND'}
      onLogicChange={onLogicChange}
      showLogic={props?.showLogic}
      emptyText={props?.emptyText}
      addText={props?.addText}
    />,
  )
  return { onChange, onLogicChange }
}

describe('FilterConditionEditor 共享筛选条件编辑器', () => {
  it('空态：渲染默认文案与添加按钮', () => {
    renderEditor()
    expect(screen.getByText('暂无筛选条件')).toHaveClass('vcvd-empty')
    expect(screen.getByRole('button', { name: /添加筛选条件/ })).toBeInTheDocument()
  })

  it('空态：支持自定义 emptyText / addText', () => {
    renderEditor({ emptyText: '无命中条件', addText: '新增条件' })
    expect(screen.getByText('无命中条件')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /新增条件/ })).toBeInTheDocument()
  })

  it('逻辑栏：点击 AND / OR 触发 onLogicChange', () => {
    const { onLogicChange } = renderEditor()
    fireEvent.click(screen.getByText('任一满足（OR）'))
    expect(onLogicChange).toHaveBeenCalledWith('OR')
    expect(screen.getByText('所有筛选条件同时生效')).toBeInTheDocument()
  })

  it('showLogic=false 时不渲染逻辑栏', () => {
    renderEditor({ showLogic: false })
    expect(screen.queryByText('条件组合：')).not.toBeInTheDocument()
  })

  it('添加规则：以默认操作符补齐空规则行', () => {
    const { onChange } = renderEditor()
    fireEvent.click(screen.getByRole('button', { name: /添加筛选条件/ }))
    expect(onChange).toHaveBeenCalledWith([{ field_name: '', op: 'contains' }])
  })

  it('删除规则：回传剔除该条后的数组', () => {
    const { onChange } = renderEditor({
      rules: [
        { field_name: '姓名', op: 'contains', value: '张' },
        { field_name: '年龄', op: '>', value: 18 },
      ],
    })
    // 删除第二条（序号 #2 所在行）
    const rows = document.querySelectorAll('.vcvd-rule')
    expect(rows).toHaveLength(2)
    fireEvent.click(rows[1]!.querySelector('.vcvd-rule-del') as HTMLElement)
    expect(onChange).toHaveBeenCalledWith([{ field_name: '姓名', op: 'contains', value: '张' }])
  })

  it('切换字段：重置为该字段类型的首个操作符并清空值', () => {
    const { onChange } = renderEditor({ rules: [{ field_name: '姓名', op: 'contains', value: '张' }] })
    // 打开字段下拉 → 选择「年龄」
    fireEvent.mouseDown(document.querySelectorAll('.ant-select')[0]!)
    fireEvent.click(screen.getByText('年龄', { selector: '.ant-select-item-option-content' }))
    expect(onChange).toHaveBeenCalledWith([{ field_name: '年龄', op: '=', value: undefined }])
  })

  it('无需值操作符：渲染「（无需值）」提示', () => {
    renderEditor({ rules: [{ field_name: '姓名', op: 'is_empty' }] })
    expect(screen.getByText('（无需值）')).toBeInTheDocument()
  })

  it('布尔值编辑器：开关变更回传 value', () => {
    const { onChange } = renderEditor({ rules: [{ field_name: '完成', op: '=', value: false }] })
    fireEvent.click(screen.getByRole('switch'))
    expect(onChange).toHaveBeenCalledWith([{ field_name: '完成', op: '=', value: true }])
  })

  it('数值编辑器：InputNumber 变更回传数字', () => {
    const { onChange } = renderEditor({ rules: [{ field_name: '年龄', op: '>', value: 18 }] })
    const input = screen.getByPlaceholderText('数值')
    fireEvent.change(input, { target: { value: '21' } })
    expect(onChange).toHaveBeenCalledWith([{ field_name: '年龄', op: '>', value: 21 }])
  })

  it('文本编辑器：输入回传字符串', () => {
    const { onChange } = renderEditor({ rules: [{ field_name: '姓名', op: 'contains', value: '' }] })
    fireEvent.change(screen.getByPlaceholderText('值'), { target: { value: '李' } })
    expect(onChange).toHaveBeenCalledWith([{ field_name: '姓名', op: 'contains', value: '李' }])
  })

  it('日期编辑器：占位提示为日期格式', () => {
    renderEditor({ rules: [{ field_name: '日期', op: '>=', value: '2026-01-01' }] })
    expect(screen.getByPlaceholderText('YYYY-MM-DD')).toBeInTheDocument()
  })

  it('select 编辑器：渲染可选值下拉', () => {
    renderEditor({ rules: [{ field_name: '状态', op: '=', value: '高' }] })
    // 存在值编辑器（宽度 130 的 Select），且回显当前值
    expect(screen.getByText('高')).toBeInTheDocument()
  })
})
