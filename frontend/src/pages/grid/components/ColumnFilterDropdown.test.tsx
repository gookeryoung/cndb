/**
 * ColumnFilterDropdown 组件测试 —— 列级筛选面板：
 * getOpsForField 联动（按字段类型给操作符）、needValue 操作符（为空/不为空）无值直通、
 * 应用回调（onApply）、重置回调（onReset）、currentFilter 初值回显。
 *
 * 注：fieldOps 中 needValue: true 标记的是"为空/不为空"类无需输入值的操作符，
 * 组件内 noValue = !!needValue，即 needValue=true → 不渲染值输入框。
 */

import { describe, expect, it, vi } from 'vitest'
import { fireEvent, screen } from '@testing-library/react'
import ColumnFilterDropdown from './ColumnFilterDropdown'
import { renderProviders } from '@/test/render-providers'
import { makeField } from '@/test/fixtures'

/** 打开第 idx 个 antd Select 下拉（0 = 操作符选择器） */
function openSelect(idx: number) {
  const selector = document.querySelectorAll('.ant-select .ant-select-selector')[idx]
  fireEvent.mouseDown(selector)
}

/** 点击按钮（antd 两字中文按钮内插空格，如 "确 定"） */
function clickButton(nameRe: RegExp) {
  fireEvent.click(screen.getByRole('button', { name: nameRe }))
}

describe('ColumnFilterDropdown 列级筛选面板', () => {
  it('text 字段默认态：默认操作符为第一个（包含），空值时确定禁用', () => {
    const field = makeField({ id: 1, name: '姓名', field_type: 'text' })
    const onApply = vi.fn()
    renderProviders(
      <ColumnFilterDropdown field={field} onApply={onApply} onReset={vi.fn()} />,
    )

    expect(screen.getByText('筛选「姓名」')).toBeInTheDocument()
    // 默认 op = getOpsForField('text')[0] = contains
    expect(document.querySelector('.ant-select-selection-item')?.textContent).toBe('包含')
    expect(screen.getByPlaceholderText('输入值')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /确\s*定/ })).toBeDisabled()

    clickButton(/确\s*定/)
    expect(onApply).not.toHaveBeenCalled()
  })

  it('输入值后点击确定：onApply 收到当前操作符与值', () => {
    const field = makeField({ id: 1, name: '姓名', field_type: 'text' })
    const onApply = vi.fn()
    renderProviders(
      <ColumnFilterDropdown field={field} onApply={onApply} onReset={vi.fn()} />,
    )

    fireEvent.change(screen.getByPlaceholderText('输入值'), { target: { value: '张' } })
    clickButton(/确\s*定/)
    expect(onApply).toHaveBeenCalledWith('contains', '张')
  })

  it('切换操作符时草稿值被清空，需重新输入才能确定', async () => {
    const field = makeField({ id: 1, name: '姓名', field_type: 'text' })
    const onApply = vi.fn()
    renderProviders(
      <ColumnFilterDropdown field={field} onApply={onApply} onReset={vi.fn()} />,
    )

    fireEvent.change(screen.getByPlaceholderText('输入值'), { target: { value: '张' } })
    openSelect(0)
    fireEvent.click(await screen.findByText('开头为'))

    // 值被清空，确定回到禁用态
    expect(screen.getByPlaceholderText('输入值')).toHaveValue('')
    expect(screen.getByRole('button', { name: /确\s*定/ })).toBeDisabled()
    expect(onApply).not.toHaveBeenCalled()
  })

  it('为空类操作符（needValue）隐藏值输入框，确定直接以 null 应用', async () => {
    const field = makeField({ id: 1, name: '姓名', field_type: 'text' })
    const onApply = vi.fn()
    renderProviders(
      <ColumnFilterDropdown field={field} onApply={onApply} onReset={vi.fn()} />,
    )

    openSelect(0)
    fireEvent.click(await screen.findByText('为空'))

    // 值输入框消失，出现"此条件无需输入值"提示
    expect(screen.queryByPlaceholderText('输入值')).not.toBeInTheDocument()
    expect(screen.getByText('此条件无需输入值')).toBeInTheDocument()

    clickButton(/确\s*定/)
    expect(onApply).toHaveBeenCalledWith('is_empty', null)
  })

  it('点击清除按钮触发 onReset', () => {
    const field = makeField({ id: 1, name: '姓名', field_type: 'text' })
    const onReset = vi.fn()
    renderProviders(
      <ColumnFilterDropdown field={field} onApply={vi.fn()} onReset={onReset} />,
    )

    clickButton(/清\s*除/)
    expect(onReset).toHaveBeenCalledTimes(1)
  })

  it('currentFilter 初值回显：操作符与值就位且确定可用', () => {
    const field = makeField({ id: 1, name: '姓名', field_type: 'text' })
    const onApply = vi.fn()
    renderProviders(
      <ColumnFilterDropdown
        field={field}
        currentFilter={{ op: 'starts_with', value: '张' }}
        onApply={onApply}
        onReset={vi.fn()}
      />,
    )

    expect(document.querySelector('.ant-select-selection-item')?.textContent).toBe('开头为')
    expect(screen.getByPlaceholderText('输入值')).toHaveValue('张')
    expect(screen.getByRole('button', { name: /确\s*定/ })).toBeEnabled()
  })

  it('select 字段：值控件为下拉选择，选项来自字段 config.options', async () => {
    const field = makeField({
      id: 1, name: '优先级', field_type: 'select',
      config: { options: ['高', '中', '低'] },
    })
    const onApply = vi.fn()
    renderProviders(
      <ColumnFilterDropdown field={field} onApply={onApply} onReset={vi.fn()} />,
    )

    // 值控件是 Select（第 2 个）；初始草稿值为空串，antd 视为已选故不渲染 placeholder span
    expect(document.querySelectorAll('.ant-select')).toHaveLength(2)
    openSelect(1)
    // 点击选项 content 元素（冒泡到选项根触发选中），role=option 直击不生效
    fireEvent.click(await screen.findByText('高', { selector: '.ant-select-item-option-content' }))

    clickButton(/确\s*定/)
    // select 字段默认操作符为 '='
    expect(onApply).toHaveBeenCalledWith('=', '高')
  })

  it('number 字段：值控件为数字输入框', () => {
    const field = makeField({ id: 1, name: '年龄', field_type: 'number' })
    const onApply = vi.fn()
    renderProviders(
      <ColumnFilterDropdown field={field} onApply={onApply} onReset={vi.fn()} />,
    )

    const input = screen.getByPlaceholderText('输入数值')
    fireEvent.change(input, { target: { value: '42' } })
    clickButton(/确\s*定/)
    expect(onApply).toHaveBeenCalledWith('=', '42')
  })

  it('boolean 字段：值控件为 是/否 下拉', async () => {
    const field = makeField({ id: 1, name: '启用', field_type: 'boolean' })
    const onApply = vi.fn()
    renderProviders(
      <ColumnFilterDropdown field={field} onApply={onApply} onReset={vi.fn()} />,
    )

    // 值控件是第 2 个 Select（第 1 个为操作符）；初始草稿空串不渲染 placeholder
    expect(document.querySelectorAll('.ant-select')).toHaveLength(2)
    openSelect(1)
    fireEvent.click(await screen.findByText('是', { selector: '.ant-select-item-option-content' }))

    clickButton(/确\s*定/)
    expect(onApply).toHaveBeenCalledWith(expect.any(String), true)
  })
})
