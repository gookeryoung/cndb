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

/** 空规则常量：rerender 场景需保持引用稳定，否则会触发对话框的 open effect 重置 Tab */
const NO_FILTERS: FilterRule[] = []
const NO_SORTS: SortRule[] = []

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
        onSaveFilterLogic={() => { }} onSaveFilters={() => { }} onSaveSortings={() => { }}
        onSaveOptions={() => { }} onClose={() => { }}
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

describe('ViewConfigDialog 紧凑布局', () => {
  it('Modal 带 vcvd-modal 类，Tab 内容区为独立滚动容器', () => {
    renderDialog({ viewType: 'kanban' })

    expect(document.querySelector('.vcvd-modal')).not.toBeNull()
    expect(document.querySelector('.vcvd-tab-body')).not.toBeNull()
  })

  it('kanban 专属设置按 group 渲染四个分区卡片，分区头为可折叠按钮', () => {
    renderDialog({ viewType: 'kanban' })
    fireEvent.click(screen.getByText('kanban 专属设置'))

    expect(document.querySelectorAll('.vcvd-section')).toHaveLength(4)
    for (const label of ['分组与标题', '字段映射', '排序与提醒', '完成状态']) {
      // 分区头含 chevron 图标，accessible name 带图标前缀，用正则匹配
      expect(screen.getByRole('button', { name: new RegExp(label) })).toHaveAttribute('aria-expanded')
    }
  })

  it('字段下拉占整行、短控件占单列（列宽由 optionColSpan 派生）', () => {
    renderDialog({ viewType: 'kanban' })
    fireEvent.click(screen.getByText('kanban 专属设置'))

    // group_field 是字段下拉 → 整行
    expect(screen.getByText('分组字段').closest('.vcvd-col-2')).not.toBeNull()
    // card_sort_direction 是枚举下拉 → 单列
    expect(screen.getByText('卡片排序方向').closest('.vcvd-col-1')).not.toBeNull()
  })

  it('低频分区默认收起，点击后展开并渲染其配置项', () => {
    renderDialog({ viewType: 'kanban' })
    fireEvent.click(screen.getByText('kanban 专属设置'))

    const head = screen.getByRole('button', { name: /完成状态/ })
    expect(head).toHaveAttribute('aria-expanded', 'false')
    // 收起时卸载 DOM，不参与查询
    expect(screen.queryByText('完成标志')).not.toBeInTheDocument()

    fireEvent.click(head)
    expect(head).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByText('完成标志')).toBeInTheDocument()
  })

  it('默认展开的分区可收起并卸载其配置项', () => {
    renderDialog({ viewType: 'kanban' })
    fireEvent.click(screen.getByText('kanban 专属设置'))

    const head = screen.getByRole('button', { name: /排序与提醒/ })
    expect(head).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByText('卡片排序方向')).toBeInTheDocument()

    fireEvent.click(head)
    expect(head).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByText('卡片排序方向')).not.toBeInTheDocument()
  })

  it('切换视图类型后分区与折叠态随之重置', () => {
    const baseProps = {
      open: true,
      filters: NO_FILTERS,
      sortings: NO_SORTS,
      viewOptions: null,
      fields: FIELDS,
      filterLogic: 'AND' as const,
      onSaveFilterLogic: vi.fn(),
      onSaveFilters: vi.fn(),
      onSaveSortings: vi.fn(),
      onSaveOptions: vi.fn(),
      onClose: vi.fn(),
    }
    const { rerender } = renderProviders(<ViewConfigDialog {...baseProps} viewType="kanban" />)

    fireEvent.click(screen.getByText('kanban 专属设置'))
    // 手动展开 kanban 的「完成状态」
    fireEvent.click(screen.getByRole('button', { name: /完成状态/ }))
    expect(screen.getByText('完成标志')).toBeInTheDocument()

    // 切到 wbs：分区集合不同，折叠态应回到默认（「操作」默认收起）
    rerender(<ViewConfigDialog {...baseProps} viewType="wbs" />)

    expect(document.querySelectorAll('.vcvd-section')).toHaveLength(3)
    expect(screen.getByRole('button', { name: /操作/ })).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByText('完成标志')).not.toBeInTheDocument()
  })

  it('筛选规则行使用紧凑规则行结构并带序号与条件组合栏', () => {
    renderDialog({ filters: [{ field_name: '姓名', op: 'contains', value: '张' }] })

    expect(document.querySelector('.vcvd-logic-bar')).not.toBeNull()
    // 规则行容器与序号列（此时仅筛选面板已渲染）
    expect(screen.getByText('#1').closest('.vcvd-rule')).not.toBeNull()
  })

  it('排序规则行同样使用紧凑规则行结构', () => {
    renderDialog({ sortings: [{ field_name: '姓名', direction: 'desc' }] })
    fireEvent.click(screen.getByText('排序 (1)'))

    // Tabs 保留非激活面板 DOM，故按行内元素定位而非全局计数
    const row = screen.getByText('降序 ↓').closest('.vcvd-rule')
    expect(row).not.toBeNull()
    expect(row).toHaveClass('vcvd-rule')
    expect(row?.querySelector('.vcvd-rule-index')).toHaveTextContent('#1')
  })

  it('视图专属设置项修改后保存携带新值', async () => {
    const spies = renderDialog({ viewType: 'kanban' })
    fireEvent.click(screen.getByText('kanban 专属设置'))

    // kanban 唯一开关 pin_urgent：未配置时控件为关闭态，开启后写入 true
    const sw = screen.getByRole('switch')
    expect(sw).toHaveAttribute('aria-checked', 'false')
    fireEvent.click(sw)
    expect(sw).toHaveAttribute('aria-checked', 'true')

    fireEvent.click(screen.getByRole('button', { name: /^保\s*存$/ }))
    await waitFor(() => expect(spies.onSaveOptions).toHaveBeenCalledWith({ pin_urgent: true }))
  })
})
