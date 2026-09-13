/** Grid 列构建函数 — 根据 fields 和 view 状态生成 AntD Table ColumnsType. */

import type { ColumnsType } from 'antd/es/table'
import { FilterOutlined, SortAscendingOutlined, SortDescendingOutlined } from '@ant-design/icons'
import type { RowResponse, Field } from '@/api'
import GridCell from './GridCell'
import ColumnFilterDropdown from './ColumnFilterDropdown'

/** 构建 Grid 列定义 */
export function buildColumns(
  fields: Field[],
  wid: number | string | undefined,
  viewSortings: Array<{ field_name: string; direction: 'asc' | 'desc' }>,
  viewFilters: Array<{ field_name: string; op: string; value?: unknown }>,
  onFilterApply: (fieldName: string, op: string, value: unknown) => void,
  onFilterReset: (fieldName: string) => void,
  onCellSave?: (rowId: number | string, fieldName: string, value: unknown) => Promise<unknown>,
): ColumnsType<RowResponse> {
  return fields.filter(f => !f.hidden).sort((a, b) => (a.order ?? 0) - (b.order ?? 0))
    .map<NonNullable<ColumnsType<RowResponse>>[number]>(f => {
      const sortRule = viewSortings.find(s => s.field_name === f.name)
      // 所有有排序规则的列都受控 sortOrder，保证 AntD 内部状态与 viewSortings 同步
      // 这样任何排序列都能正确经历 ascend→descend→null 循环
      const sortOrder: 'ascend' | 'descend' | null | undefined = sortRule
        ? (sortRule.direction === 'asc' ? 'ascend' : 'descend')
        : undefined
      // 表头图标：任何有排序规则的列都显示箭头（视觉提示）
      const hasSortIndicator = !!sortRule
      const filterRule = viewFilters.find(fr => fr.field_name === f.name)
      const currentFilter = filterRule
        ? { op: filterRule.op, value: filterRule.value }
        : undefined
      return {
        key: String(f.id),
        title: (
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
            <span>{f.name}{f.required && <span style={{ color: '#ff4d4f' }}>*</span>}</span>
            {hasSortIndicator && (
              sortRule!.direction === 'asc'
                ? <SortAscendingOutlined style={{ fontSize: 12, color: '#1677ff' }} />
                : <SortDescendingOutlined style={{ fontSize: 12, color: '#1677ff' }} />
            )}
            {currentFilter && (
              <FilterOutlined style={{ fontSize: 11, color: '#1677ff' }} />
            )}
          </span>
        ),
        dataIndex: f.name,
        ellipsis: true,
        width: 160,
        sorter: true,
        sortOrder,
        filterDropdown: ({ confirm, clearFilters }) => (
          <ColumnFilterDropdown
            field={f}
            currentFilter={currentFilter}
            onApply={(op, value) => { onFilterApply(f.name, op, value); confirm?.() }}
            onReset={() => { onFilterReset(f.name); clearFilters?.(); confirm?.() }}
          />
        ),
        filterIcon: (filtered) => (
          <FilterOutlined style={{ color: filtered || currentFilter ? '#1677ff' : undefined }} />
        ),
        render: (v: unknown, record: RowResponse) => (
          <GridCell
            value={v}
            field={f}
            rowId={record.id}
            wid={wid}
            onSave={onCellSave ? (fieldName, value) => onCellSave(record.id, fieldName, value) : undefined}
          />
        ),
      }
    })
}
