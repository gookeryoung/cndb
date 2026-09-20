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
