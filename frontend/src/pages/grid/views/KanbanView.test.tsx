/**
 * KanbanView 组件测试 —— 看板视图.
 *
 * 覆盖：空数据 / 分组列头与计数 / 卡片标题 / 进度条 / 逾期与紧急徽章 /
 * 优先级与负责人 Tag / 额外字段 / 点击回调 / 缺分组字段空态。
 */

import { describe, expect, it, vi } from 'vitest'
import dayjs from 'dayjs'
import { fireEvent, screen } from '@testing-library/react'
import KanbanView from './KanbanView'
import { renderProviders } from '@/test/render-providers'
import { makeField } from '@/test/fixtures'
import type { Field, RowResponse, View } from '@/api'

const FIELDS: Field[] = [
  makeField({ id: 1, name: '名称', field_type: 'text' }),
  makeField({ id: 2, name: '状态', field_type: 'select', config: { options: ['待办', '进行中', '已完成'] } }),
  makeField({ id: 3, name: '进度', field_type: 'number' }),
  makeField({ id: 4, name: '截止', field_type: 'date' }),
  makeField({ id: 5, name: '优先级', field_type: 'select', config: { options: ['高', '中', '低'] } }),
  makeField({ id: 6, name: '负责人', field_type: 'text' }),
  makeField({ id: 7, name: '描述', field_type: 'long_text' }),
]

const VIEW_OPTIONS = {
  group_field: '状态',
  title_field: '名称',
  progress_field: '进度',
  due_date_field: '截止',
  priority_field: '优先级',
  assignee_field: '负责人',
  card_fields: ['描述'],
}

/** 今天往前/往后偏移 N 天的日期串 */
const offsetDate = (days: number) => dayjs().add(days, 'day').format('YYYY-MM-DD')

const ROWS: RowResponse[] = [
  { id: 1, 名称: '任务A', 状态: '进行中', 进度: 50, 截止: offsetDate(-5), 优先级: '高', 负责人: 'alice', 描述: '要点A' },
  { id: 2, 名称: '任务B', 状态: '进行中', 进度: 20, 截止: offsetDate(1), 优先级: '中', 负责人: 'bob', 描述: '要点B' },
  { id: 3, 名称: '任务C', 状态: '待办', 进度: null, 截止: offsetDate(10), 优先级: '低', 负责人: 'carol', 描述: '要点C' },
]

function renderKanban(props?: {
  rows?: RowResponse[]
  view?: View | null
  onRowClick?: (r: RowResponse) => void
  canEdit?: boolean
  onToggleDone?: (r: RowResponse, values: Record<string, unknown>) => void
}) {
  const view = props?.view !== undefined ? props.view
    : { id: 1, name: '看板', view_type: 'kanban', is_default: false, view_options: VIEW_OPTIONS }
  return renderProviders(
    <KanbanView
      rows={props?.rows ?? ROWS}
      fields={FIELDS}
      view={view}
      density="comfortable"
      onRowClick={props?.onRowClick}
      canEdit={props?.canEdit}
      onToggleDone={props?.onToggleDone}
    />,
  )
}

describe('KanbanView 看板视图', () => {
  it('空数据显示引导空态', () => {
    renderKanban({ rows: [] })

    expect(screen.getByText(/这张表还没有数据/)).toBeInTheDocument()
  })

  it('按分组字段聚合列并显示行数', () => {
    renderKanban()

    expect(screen.getByText('进行中')).toBeInTheDocument()
    expect(screen.getByText('待办')).toBeInTheDocument()
    // 列头行数徽章：进行中 2 行、待办 1 行
    expect(screen.getByText('2')).toBeInTheDocument()
    expect(screen.getByText('1')).toBeInTheDocument()
  })

  it('卡片渲染标题与额外字段 Tag', () => {
    renderKanban()

    expect(screen.getByText('任务A')).toBeInTheDocument()
    expect(screen.getByText('任务B')).toBeInTheDocument()
    // card_fields 额外字段显示为 "字段名: 值"
    expect(screen.getByText('描述: 要点A')).toBeInTheDocument()
  })

  it('进度条渲染（有 progress_field 且值有效）', () => {
    renderKanban()

    // 进度为 null 的行 Number(null)=0 也渲染 0% 进度条，三行全部渲染
    expect(document.querySelectorAll('.ant-progress')).toHaveLength(3)
  })

  it('逾期卡片显示红色逾期徽章并计入紧急计数', () => {
    renderKanban()

    // 任务A 截止为 5 天前 → "逾期 5天"
    expect(screen.getByText(/逾期 5天/)).toBeInTheDocument()
    // 列头紧急计数：逾期（-5天）与临近（+1天）各计 1 → 2
    expect(screen.getByText(/2 紧急/)).toBeInTheDocument()
  })

  it('临近截止（阈值内）显示"还剩 X天"徽章', () => {
    renderKanban()

    // 任务B 截止为明天 → "还剩 1天"
    expect(screen.getByText(/还剩 1天/)).toBeInTheDocument()
  })

  it('截止日期徽章与标题同一行（渲染在标题元素内，紧贴标题右侧）', () => {
    renderKanban()

    const titleEl = screen.getByText('任务A')
    // 徽章作为标题元素的子节点 → 同一行显示，不再单独占一行
    expect(titleEl.querySelector('.ant-tag')).not.toBeNull()
    expect(titleEl.textContent).toContain('逾期 5天')
  })

  it('优先级与负责人渲染为 Tag', () => {
    renderKanban()

    expect(screen.getByText('高')).toBeInTheDocument()
    expect(screen.getByText('alice')).toBeInTheDocument()
    expect(screen.getByText('carol')).toBeInTheDocument()
  })

  it('点击卡片回调对应行', () => {
    const onRowClick = vi.fn()
    renderKanban({ onRowClick })

    fireEvent.click(screen.getByText('任务A'))

    expect(onRowClick).toHaveBeenCalledTimes(1)
    expect(onRowClick.mock.calls[0][0].id).toBe(1)
  })

  it('分组字段在 fields 中不存在时全部行归入"未分组"列', () => {
    const view: View = { id: 1, name: '看板', view_type: 'kanban', is_default: false, view_options: { group_field: '不存在' } }
    renderKanban({ view })

    // groupKeyForRow 对取不到值的行回退"未分组"，不会进入空态
    expect(screen.getByText('未分组')).toBeInTheDocument()
    expect(screen.getByText('任务A')).toBeInTheDocument()
  })
})

describe('KanbanView 完成标志', () => {
  /** 任务C 状态=已完成（匹配完成标志），其余任务进行中/待办 */
  const doneRows: RowResponse[] = [
    { id: 1, 名称: '任务A', 状态: '进行中', 进度: 50, 截止: offsetDate(-5), 优先级: '高' },
    { id: 2, 名称: '任务B', 状态: '进行中', 进度: 20, 截止: offsetDate(1), 优先级: '中' },
    { id: 3, 名称: '任务C', 状态: '已完成', 进度: 100, 截止: offsetDate(-10), 优先级: '低' },
  ]
  const doneView: View = {
    id: 1, name: '看板', view_type: 'kanban', is_default: false,
    view_options: { ...VIEW_OPTIONS, done_field: '状态', done_value: '已完成' },
  }

  it('完成卡片隐藏截止日期徽章（逾期/还剩都不再显示），未完成卡片照常显示', () => {
    renderKanban({ rows: doneRows, view: doneView })

    // 任务C 已完成且逾期 10 天 → 不显示逾期徽章；任务A 未完成 → 照常显示
    expect(screen.queryByText(/逾期 10天/)).not.toBeInTheDocument()
    expect(screen.getByText(/逾期 5天/)).toBeInTheDocument()
    expect(screen.getByText(/还剩 1天/)).toBeInTheDocument()
  })

  it('完成卡片应用固定主题完成样式：绿底 + 绿色左边框 + 灰色文字 + 删除线 + 标题后绿色对勾', () => {
    renderKanban({ rows: doneRows, view: doneView })

    const titleEl = screen.getByText('任务C')
    const cardEl = titleEl.parentElement as HTMLElement
    // 固定主题样式：绿底 / 绿色左边框 / 灰色标题文字
    expect(cardEl.style.background).toContain('var(--cn-bg-success-subtle)')
    expect(cardEl.style.borderLeft).toContain('rgb(82, 196, 26)') // #52c41a
    expect(titleEl.style.color).toBe('var(--cn-text-muted)')
    expect(titleEl.style.textDecoration).toContain('line-through')
    // 标题后紧跟绿色对勾图标
    const checkIcon = titleEl.querySelector('.anticon-check-circle') || titleEl.querySelector('.anticon-check-circle-filled')
    expect(checkIcon).not.toBeNull()
    const styleCheck = (checkIcon as HTMLElement)?.style?.color
    expect(styleCheck || getComputedStyle(checkIcon!).color).toContain('82, 196, 26') // #52c41a
  })

  it('完成卡片不计入列头紧急计数', () => {
    renderKanban({ rows: doneRows, view: doneView })

    // 进行中列：任务A 逾期 + 任务B 紧急 → 2 紧急；任务C 已完成逾期不计（且在其他列）
    expect(screen.getByText(/2 紧急/)).toBeInTheDocument()
  })
})

describe('KanbanView 完成勾选框', () => {
  const doneRows: RowResponse[] = [
    { id: 1, 名称: '任务A', 状态: '进行中', 进度: 50, 截止: offsetDate(-5), 优先级: '高' },
    { id: 3, 名称: '任务C', 状态: '已完成', 进度: 100, 截止: offsetDate(-10), 优先级: '低' },
  ]
  const doneView: View = {
    id: 1, name: '看板', view_type: 'kanban', is_default: false,
    view_options: { ...VIEW_OPTIONS, done_field: '状态', done_value: '已完成' },
  }
  /** 取某张卡片容器（标题元素的父节点） */
  const cardOf = (title: string) => screen.getByText(title).parentElement as HTMLElement

  it('未配置完成标志时不显示勾选框', () => {
    renderKanban({ rows: doneRows, canEdit: true, onToggleDone: vi.fn() })

    fireEvent.mouseEnter(cardOf('任务A'))

    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument()
  })

  it('无编辑权限时不显示勾选框', () => {
    renderKanban({ rows: doneRows, view: doneView, canEdit: false, onToggleDone: vi.fn() })

    fireEvent.mouseEnter(cardOf('任务A'))

    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument()
  })

  it('未完成卡片 hover 显示勾选框，点击写回 done_value；已完成卡片 hover 不显示勾选框（单向不可逆）', () => {
    const onToggleDone = vi.fn()
    renderKanban({ rows: doneRows, view: doneView, canEdit: true, onToggleDone })

    // 任务A 未完成 → hover 显示勾选框
    fireEvent.mouseEnter(cardOf('任务A'))
    expect(screen.getByRole('checkbox')).not.toBeChecked()
    fireEvent.click(screen.getByRole('checkbox'))
    expect(onToggleDone).toHaveBeenCalledTimes(1)
    expect(onToggleDone.mock.calls[0][0].id).toBe(1)
    expect(onToggleDone.mock.calls[0][1]).toEqual({ 状态: '已完成' })

    // 任务C 已完成 → hover 不显示勾选框
    fireEvent.mouseLeave(cardOf('任务A'))
    fireEvent.mouseEnter(cardOf('任务C'))
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument()
  })
})
