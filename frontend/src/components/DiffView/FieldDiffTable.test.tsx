/** FieldDiffTable 组件测试：新增 / 修改 / 删除三种变更与基准漂移可视化. */

import { describe, expect, it } from 'vitest'
import { screen } from '@testing-library/react'

import type { ChangeItemDetail } from '@/api'
import { renderProviders } from '@/test/render-providers'
import FieldDiffTable from './FieldDiffTable'

function makeItem(overrides: Partial<ChangeItemDetail>): ChangeItemDetail {
  return {
    id: 1,
    op: 'update',
    row_id: 9,
    base_values: {},
    values: {},
    current_values: {},
    field_conflicts: [],
    ...overrides,
  }
}

describe('FieldDiffTable', () => {
  it('update：渲染「字段 / 修改前 / 修改后」三列，前后值各成单元格', () => {
    const { container } = renderProviders(
      <FieldDiffTable item={makeItem({ base_values: { 分级: 'A', 备注: '老客户' }, values: { 分级: 'B' } })} />,
    )

    expect(screen.getByText('字段')).toBeInTheDocument()
    expect(screen.getByText('修改前')).toBeInTheDocument()
    expect(screen.getByText('修改后')).toBeInTheDocument()
    expect(screen.getByText('A')).toBeInTheDocument()
    expect(screen.getByText('B')).toBeInTheDocument()
    // 新值缺失 → 统一显示「空」
    expect(screen.getByText('空')).toBeInTheDocument()
    // 无冲突时不出现「当前值」列与漂移标记
    expect(screen.queryByText('当前值（行内已变更）')).toBeNull()
    expect(screen.queryByText('基准已漂移')).toBeNull()
    expect(container.querySelector('.cn-fielddiff-current')).toBeNull()
  })

  it('update：基准漂移字段追加「当前值」列并给出 Tooltip 标记', () => {
    const { container } = renderProviders(
      <FieldDiffTable
        item={makeItem({
          base_values: { 分级: 'A', 备注: '老客户' },
          values: { 分级: 'B' },
          current_values: { 分级: 'C', 备注: '老客户' },
          field_conflicts: ['分级'],
        })}
      />,
    )

    expect(screen.getByText('当前值（行内已变更）')).toBeInTheDocument()
    expect(screen.getByText('基准已漂移')).toBeInTheDocument()
    // 冲突字段展示行内当前值；无冲突字段用占位符
    expect(container.querySelector('.cn-fielddiff-current')?.textContent).toBe('C')
    expect(screen.getByText('—')).toBeInTheDocument()
  })

  it('create：仅渲染新增值列并带 + 号', () => {
    const { container } = renderProviders(
      <FieldDiffTable item={makeItem({ op: 'create', values: { 姓名: '张三', 分级: 'B' } })} />,
    )

    expect(screen.getByText('新增值')).toBeInTheDocument()
    expect(screen.queryByText('修改前')).toBeNull()
    expect(screen.getByText('张三')).toBeInTheDocument()
    expect(container.querySelectorAll('.cn-fielddiff-sign-add')).toHaveLength(2)
  })

  it('delete：展示整行快照，值加删除线并提示整行删除', () => {
    const { container } = renderProviders(
      <FieldDiffTable item={makeItem({ op: 'delete', base_values: { 姓名: '王五', 分级: 'C' } })} />,
    )

    expect(screen.getByText('原值')).toBeInTheDocument()
    expect(screen.getByText(/整行删除/)).toBeInTheDocument()
    expect(screen.getByText('王五')).toBeInTheDocument()
    expect(container.querySelectorAll('.cn-fielddiff-strike')).toHaveLength(2)
    expect(container.querySelectorAll('.cn-fielddiff-sign-del')).toHaveLength(2)
  })

  it('对象值以 JSON 串展示，字段名保持可见', () => {
    renderProviders(
      <FieldDiffTable item={makeItem({ base_values: { 配置: { a: 1 } }, values: { 配置: { a: 2 } } })} />,
    )

    expect(screen.getByText('配置')).toBeInTheDocument()
    expect(screen.getByText('{"a":1}')).toBeInTheDocument()
    expect(screen.getByText('{"a":2}')).toBeInTheDocument()
  })

  it('无字段变更时给出空态文案', () => {
    renderProviders(<FieldDiffTable item={makeItem({ base_values: {}, values: {} })} />)

    expect(screen.getByText('（无字段变更）')).toBeInTheDocument()
  })

  it('空串与 null 统一显示为「空」，不出现空白单元格', () => {
    renderProviders(
      <FieldDiffTable item={makeItem({ base_values: { 备注: '', 电话: null }, values: { 备注: '已填写', 电话: null } })} />,
    )

    // 备注：空串 → 空；电话：null → 空（前后各一处）
    expect(screen.getAllByText('空').length).toBe(3)
  })
})
