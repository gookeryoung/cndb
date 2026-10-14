/** 看板视图组件 — 支持进度跟踪、紧急提醒、优先级徽章.
 *
 * view_options 扩展字段:
 * - group_field:       分组字段（select/multi_select/link）
 * - title_field:       卡片标题字段（text/主键字段/link/select 等任意可显示字段）
 * - progress_field:    进度百分比字段（number, 0-100）
 * - due_date_field:    截止日期字段（date/datetime）
 * - priority_field:    优先级字段（select）
 * - assignee_field:    负责人字段（text/link）
 * - card_fields:       卡片额外显示的字段列表（string[]）
 * - urgent_threshold_days: 临近截止多少天标记为紧急（默认 3）
 * - show_progress_bar: 是否显示进度条（默认 true，有 progress_field 时）
 * - card_sort_field:   卡片排序字段（可选）；留空则按 API 返回顺序
 * - card_sort_direction: 卡片排序方向 'asc' | 'desc'，默认 desc
 * - pin_urgent:        是否把逾期/紧急卡片置顶（默认 true，有 due_date_field 时）
 * - pin_today:         是否把截止日期恰好是今天的任务置顶并高亮（默认 true，有 due_date_field 时）
 *                      开启时：逾期 > 当天 > 紧急 > 正常；关闭时当天归入紧急
 *                      视觉上当天任务使用独立的金橙色边框 + 金黄色背景 + 金橙色日期徽章
 * - done_field:        完成标志字段（boolean/select/multiselect/text/date 等）
 * - done_value:        完成匹配值（boolean 字段为 true/false；select 为 option value；
 *                      multiselect 为 value 数组任一命中；text 为精确匹配文本）
 *                      匹配完成的卡片：标题删除线 + 标题后绿色对勾、绿色左边框 + 主题绿底，
 *                      隐藏截止日期徽章，不参与紧急置顶、不计入列头紧急计数，自动置底。
 *                      已完成卡片可再次点击勾选框取消（写回取消值，语义见 buildDoneToggleValue）。
 *
 * 交互约定:
 * - 优先级/负责人/额外字段值为空时不渲染对应 Tag（不显示 '—' 等空白占位标签）。
 * - 截止日期徽章（时钟图标 + X天，逾期为 -X天）与标题同一行、紧贴标题右侧显示。
 * - 配置了 done_field 且当前用户可编辑时，卡片 hover 后在删除按钮左侧显示完成勾选框（可勾选/取消）。
 *
 * 子模块：kanban/ 下按「密度样式 / 视觉元素 / 卡片 / 列」拆分；排序与分组聚合在
 * ../kanbanBoard.ts（纯函数，可独立单测）。
 */

import { memo, useMemo } from 'react'
import { Empty } from 'antd'

import type { Field, RowResponse, RowValues, View } from '@/api'
import type { Density } from '@/theme/tableSettings'
import { KANBAN_OPTIONS, resolveOpts } from '../view-config/viewOptionSchema'
import { groupKanbanColumns, resolveGroupField } from './kanbanBoard'
import { KanbanColumn } from './kanban/KanbanColumn'
import { densityColumnStyle } from './kanban/kanbanDensity'

export default memo(function KanbanView({
  rows,
  fields,
  view,
  density,
  sortings,
  onRowClick,
  onDeleteCard,
  canDelete,
  onAddCard,
  canAdd,
  onToggleDone,
  canEdit,
  pdfExporting,
}: {
  rows: RowResponse[]
  fields: Field[]
  view?: View | null
  density: Density
  sortings?: Array<{ field_name: string; direction: 'asc' | 'desc' }>
  onRowClick?: (r: RowResponse) => void
  onDeleteCard?: (r: RowResponse) => void
  canDelete?: boolean
  onAddCard?: (initialValues: RowValues) => void
  canAdd?: boolean
  /** 勾选/取消完成回调 —— 仅配置了 done_field 且 canEdit 时卡片才显示勾选框 */
  onToggleDone?: (r: RowResponse, values: RowValues) => void
  canEdit?: boolean
  /** PDF 导出模式：列内强制全量渲染卡片 */
  pdfExporting?: boolean
}) {
  const opts = useMemo(
    () => resolveOpts(view?.view_options as Record<string, unknown> | undefined, KANBAN_OPTIONS),
    [view?.view_options],
  )
  const { name: groupField, def: groupFieldDef } = resolveGroupField(fields, opts)

  const colStyle = densityColumnStyle(density)

  // 按分组字段聚合成列 — 排序/分组/紧急统计逻辑在 kanbanBoard.ts（纯函数，可独立单测）
  const columns = useMemo(
    () => groupKanbanColumns(rows, fields, opts, groupField, groupFieldDef, sortings),
    [rows, groupField, groupFieldDef, opts, fields, sortings],
  )

  if (columns.length === 0) {
    return (
      <Empty
        description={rows.length === 0 ? '这张表还没有数据：回到表格视图新增一行或导入数据' : '当前视图下没有可分组的数据，试试调整筛选条件'}
        style={{ padding: 48 }}
      />
    )
  }

  return (
    <div
      style={{
        display: 'flex',
        gap: colStyle.gap,
        overflowX: 'auto',
        paddingBottom: colStyle.padding,
        // flex:1 占满主内容区剩余高度 —— 列高度受约束后卡片列表才能在列内滚动，
        // 虚拟化视口测量才有效；无高度约束时列随内容生长，500 张卡片全量挂载导致切看板卡顿
        flex: 1,
        minHeight: 300,
      }}
    >
      {columns.map(col => (
        <KanbanColumn
          key={col.key}
          col={col}
          fields={fields}
          opts={opts}
          density={density}
          colStyle={colStyle}
          onRowClick={onRowClick}
          onDeleteCard={onDeleteCard}
          canDelete={canDelete}
          onAddCard={onAddCard}
          canAdd={canAdd}
          onToggleDone={onToggleDone}
          canEdit={canEdit}
          pdfExporting={pdfExporting}
        />
      ))}
    </div>
  )
})
