/**
 * ViewConfigDialog 组件测试 —— 视图配置对话框.
 *
 * 覆盖：open 状态 / Tab 结构（grid 无专属 Tab、kanban 有）/ 规则回显与计数 /
 * AND-OR 切换 / 保存回调（空规则过滤、options 清洗）/ 至少保留一条规则。
 */

import { describe, expect, it, vi } from 'vitest'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import ViewConfigDialog from './ViewConfigDialog'
import type { FilterRule, SortRule } from './ViewConfigDialog'
import { renderProviders } from '@/test/render-providers'
import { makeField } from '@/test/fixtures'
import type { Field } from '@/api'

const FIELDS: Field[] = [
  makeField({ id: 1, name: '姓名', field_type: 'text' }),
  makeField({ id: 2, name: '状态', field_type: 'select', config: { options: ['高', '中'] } }),
]

function renderDialog(props?: {
  viewType?: string
  filters?: FilterRule[]
  sortings?: SortRule[]
  viewOptions?: Record<string, unknown> | null
}) {
  const spies = {
    onSaveFilterLogic: vi.fn(),
    onSaveFilters: vi.fn(),
    onSaveSortings: vi.fn(),
    onSaveOptions: vi.fn(),
    onClose: vi.fn(),
  }
  renderProviders(
    <ViewConfigDialog
      open
      viewType={props?.viewType ?? 'grid'}
      filters={props?.filters ?? []}
      sortings={props?.sortings ?? []}
      viewOptions={props?.viewOptions ?? null}
      fields={FIELDS}
      filterLogic="AND"
      {...spies}
    />,
  )
  return spies
}

describe('ViewConfigDialog 视图配置', () => {
  it('open=false 时不渲染', () => {
    renderProviders(
      <ViewConfigDialog
        open={false} viewType="grid" filters={[]} sortings={[]} viewOptions={null}
        fields={FIELDS} filterLogic="AND"
        onSaveFilterLogic={() => {}} onSaveFilters={() => {}} onSaveSortings={() => {}}
        onSaveOptions={() => {}} onClose={() => {}}
      />,
    )

    expect(screen.queryByText('视图配置')).not.toBeInTheDocument()
  })

  it('grid 类型只有筛选/排序两个 Tab（无专属设置）', () => {
    renderDialog()

    expect(screen.getByText('视图配置')).toBeInTheDocument()
    expect(screen.getByText('筛选')).toBeInTheDocument()
    expect(screen.getByText('排序')).toBeInTheDocument()
    expect(screen.queryByText('grid 专属设置')).not.toBeInTheDocument()
  })

  it('kanban 类型追加专属设置 Tab', () => {
    renderDialog({ viewType: 'kanban' })

    expect(screen.getByText('kanban 专属设置')).toBeInTheDocument()
    expect(screen.getByText('视图配置 — kanban 专属设置')).toBeInTheDocument()
  })

  it('传入已有筛选规则时 Tab label 显示计数并回显操作符', () => {
    renderDialog({ filters: [{ field_name: '姓名', op: 'contains', value: '张' }] })

    expect(screen.getByText('筛选 (1)')).toBeInTheDocument()
    expect(screen.getByText('包含')).toBeInTheDocument()
  })

  it('切换 OR 后保存回调携带 OR 逻辑与空规则过滤', () => {
    // 一条有效规则 + 默认补位的空规则 → 保存时空规则应被过滤
    const spies = renderDialog({ filters: [{ field_name: '姓名', op: 'contains', value: '张' }] })

    fireEvent.click(screen.getByText('任一满足（OR）'))
    fireEvent.click(screen.getByRole('button', { name: /^保\s*存$/ }))

    expect(spies.onSaveFilterLogic).toHaveBeenCalledWith('OR')
    expect(spies.onSaveFilters).toHaveBeenCalledWith([{ field_name: '姓名', op: 'contains', value: '张' }])
    expect(spies.onSaveSortings).toHaveBeenCalledWith([])
    expect(spies.onSaveOptions).toHaveBeenCalledWith(null)
    expect(spies.onClose).toHaveBeenCalledTimes(1)
  })

  it('编辑筛选值后保存携带新值', async () => {
    const spies = renderDialog({ filters: [{ field_name: '姓名', op: 'contains', value: '' }] })

    const valueInput = screen.getByPlaceholderText('值')
    fireEvent.change(valueInput, { target: { value: '张' } })
    fireEvent.click(screen.getByRole('button', { name: /^保\s*存$/ }))

    await waitFor(() =>
      expect(spies.onSaveFilters).toHaveBeenCalledWith([{ field_name: '姓名', op: 'contains', value: '张' }]),
    )
  })

  it('排序 Tab 渲染规则行且方向可选', () => {
    renderDialog({ sortings: [{ field_name: '姓名', direction: 'desc' }] })

    fireEvent.click(screen.getByText('排序 (1)'))

    // 规则行字段与方向回显（antd Select 的选中值渲染为文本）
    expect(screen.getByText('姓名')).toBeInTheDocument()
    expect(screen.getByText('降序 ↓')).toBeInTheDocument()
  })

  it('仅一条筛选规则时删除按钮禁用（至少保留一条）', () => {
    renderDialog({ filters: [{ field_name: '姓名', op: 'contains', value: '张' }] })

    // 规则行的删除按钮为图标按钮（danger text），只有一条时 disabled
    const delBtn = screen.getByRole('button', { name: /delete/ })
    expect(delBtn).toBeDisabled()
  })
})
