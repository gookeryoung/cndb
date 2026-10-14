/** rows → GanttTask 列表构建（日期字段解析 / 进度 / 负责人 / 分组）. */

import type { Field, RowResponse } from '@/api'
import { groupColor } from '@/utils/paletteColor'
import { findOptionSchema, resolveAutoField } from '../../view-config/viewOptionSchema'
import { formatFieldDisplayValue, getLinkFirstLabel, getMultiSelectFirstLabel, getSelectLabel } from '../../cells/fieldValueFormat'
import { parseDate } from '../../cells/dateUtils'
import type { GanttTask } from '../ganttTimeline'

/** 将 rows 转成 GanttTask 列表 */
export function buildGanttTasks(
  rows: RowResponse[],
  fields: Field[],
  opts: Record<string, unknown>,
  sortings?: Array<{ field_name: string; direction: 'asc' | 'desc' }>,
): GanttTask[] {
  const startField = opts.start_date_field as string
  const endField = opts.end_date_field as string
  const actualEndField = opts.actual_end_field as string | undefined
  const groupField = opts.group_field as string | undefined
  const progressField = opts.progress_field as string | undefined
  const assigneeField = opts.assignee_field as string | undefined

  if (!startField || !endField) return []

  // title_field 自动推断
  let titleField = opts.title_field as string | undefined
  if (!titleField) {
    titleField = resolveAutoField(fields, findOptionSchema('gantt', 'title_field'))
  }
  if (!titleField) titleField = fields[0]?.name || 'id'

  const fieldMap = new Map<string, Field>(fields.map(f => [f.name, f]))

  const fmtGroup = (name: string, raw: unknown): string | undefined => {
    const fd = fieldMap.get(name)
    if (!fd) return raw != null && raw !== '' ? String(raw) : undefined
    if (fd.field_type === 'link') return getLinkFirstLabel(raw) || undefined
    if (fd.field_type === 'multi_select' || fd.field_type === 'multiselect') return getMultiSelectFirstLabel(raw) || undefined
    if (fd.field_type === 'select') return getSelectLabel(fd, raw) || undefined
    return formatFieldDisplayValue(fd, raw) || undefined
  }

  const tasks: GanttTask[] = []
  for (const row of rows) {
    const start = parseDate(row[startField])
    const end = parseDate(row[endField])
    if (!start || !end) continue
    if (end < start) continue // 跳过非法区间

    // 标题
    const titleFd = fieldMap.get(titleField)
    const title = titleFd
      ? formatFieldDisplayValue(titleFd, row[titleField]) || String(row.id)
      : String(row[titleField] ?? row.id)

    // 分组/颜色
    let groupValue: string | undefined
    let color: string | undefined
    if (groupField) {
      groupValue = fmtGroup(groupField, row[groupField])
      if (groupValue) color = groupColor(groupValue)
    }

    // 进度
    let progress = 0
    if (progressField) {
      const v = Number(row[progressField])
      if (Number.isFinite(v)) progress = Math.max(0, Math.min(100, v))
    }

    // 负责人
    let assignee: string | undefined
    if (assigneeField) {
      const afd = fieldMap.get(assigneeField)
      assignee = afd
        ? formatFieldDisplayValue(afd, row[assigneeField]) || undefined
        : row[assigneeField] ? String(row[assigneeField]) : undefined
    }

    // 实际完成日期
    const actualEnd = actualEndField ? parseDate(row[actualEndField]) : null

    tasks.push({ row, start, end, actualEnd, title, groupValue, color, progress, assignee })
  }

  // 排序：先按分组（如果有），再按开始日期
  tasks.sort((a, b) => {
    // 应用用户的 sortings
    if (sortings && sortings.length > 0) {
      for (const s of sortings) {
        const field = fieldMap.get(s.field_name)
        if (!field) continue
        const va = a.row[s.field_name]
        const vb = b.row[s.field_name]
        if (va == null && vb == null) continue
        if (va == null) return s.direction === 'asc' ? 1 : -1
        if (vb == null) return s.direction === 'asc' ? -1 : 1
        let cmp = 0
        if (['date', 'datetime'].includes(field.field_type)) {
          cmp = parseDate(va)!.getTime() - parseDate(vb)!.getTime()
        } else if (['number', 'decimal', 'float', 'percentage'].includes(field.field_type)) {
          cmp = Number(va) - Number(vb)
        } else {
          cmp = String(va).localeCompare(String(vb), 'zh-CN')
        }
        if (cmp !== 0) return s.direction === 'asc' ? cmp : -cmp
      }
    }

    // 默认排序：按分组 → 开始日期
    const ga = a.groupValue || ''
    const gb = b.groupValue || ''
    if (ga !== gb) return ga.localeCompare(gb, 'zh-CN')
    return a.start.getTime() - b.start.getTime()
  })

  return tasks
}
