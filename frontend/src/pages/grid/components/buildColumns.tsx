/** Grid 列构建函数 — 根据 fields 和 view 状态生成 AntD Table ColumnsType. */

import { Space, Tooltip } from 'antd'
import { Button } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { FilterOutlined, SortAscendingOutlined, SortDescendingOutlined, SaveOutlined, CloseOutlined, EditOutlined } from '@ant-design/icons'
import type { RowResponse, Field, RowValues, ID } from '@/api'
import GridCell from './GridCell'
import ColumnFilterDropdown from './ColumnFilterDropdown'

/** 行内编辑（新增行/整行编辑）注入单元格所需的能力 */
export interface InlineEditCellProps {
  editing: boolean
  /** 当前行各字段的草稿值（key 为字段名） */
  values: RowValues
  onFieldChange: (fieldName: string, value: unknown) => void
  /** 单元格回车提交（行级编辑通常为 noop，由行操作列统一保存） */
  onFieldCommit: (fieldName: string) => void
  onFieldCancel: () => void
}

/** 行内编辑操作列回调 —— 新增行 / 整行编辑共用的操作挂载点 */
export interface RowInlineOps {
  /** 为指定行返回行内编辑能力；null 表示该行普通展示 */
  getInlineEdit: (record: RowResponse) => InlineEditCellProps | null
  /** 进入该行的整行编辑态 */
  onEdit: (recordId: ID) => void
  /** 保存该行（新增行建立 / 整行编辑提交） */
  onSave: (recordId: ID) => void
  /** 取消该行编辑 / 放弃新增 */
  onCancel: (recordId: ID) => void
}

/** 构建 Grid 列定义 */
export function buildColumns(
  fields: Field[],
  wid: number | string | undefined,
  viewSortings: Array<{ field_name: string; direction: 'asc' | 'desc' }>,
  viewFilters: Array<{ field_name: string; op: string; value?: unknown }>,
  onFilterApply: (fieldName: string, op: string, value: unknown) => void,
  onFilterReset: (fieldName: string) => void,
  onCellSave?: (rowId: number | string, fieldName: string, value: unknown) => Promise<unknown>,
  /** 可选：行内编辑能力（新增行/整行编辑）。提供后追加一个固定右侧的操作列 */
  inlineOps?: RowInlineOps,
): ColumnsType<RowResponse> {
  const cols: NonNullable<ColumnsType<RowResponse>>[number][] = fields.filter(f => !f.hidden).sort((a, b) => (a.order ?? 0) - (b.order ?? 0))
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
        render: (v: unknown, record: RowResponse) => {
          // 行内编辑 override：优先渲染受控编辑态，非编辑行回退到普通 GridCell
          const inline = inlineOps?.getInlineEdit(record)
          if (inline) {
            return (
              <GridCell
                value={inline.values[f.name]}
                field={f}
                rowId={record.id}
                wid={wid}
                editing={inline.editing}
                onDraftChange={(val) => inline.onFieldChange(f.name, val)}
                onDraftCommit={inline.onFieldCommit}
                onDraftCancel={inline.onFieldCancel}
                showActionButtons={false}
              />
            )
          }
          return (
            <GridCell
              value={v}
              field={f}
              rowId={record.id}
              wid={wid}
              onSave={onCellSave ? (fieldName, value) => onCellSave(record.id, fieldName, value) : undefined}
            />
          )
        },
      }
    })

  // 行内编辑能力存在时追加操作列（编辑 / 保存 / 取消）
  if (inlineOps) {
    cols.push({
      key: '__row_ops__',
      width: 112,
      align: 'center',
      title: '',
      render: (_v: unknown, record: RowResponse) => {
        const inline = inlineOps.getInlineEdit(record)
        if (inline) {
          return (
            <Space size={4}>
              <Button size="small" type="primary" icon={<SaveOutlined />} data-testid="row-save-btn" onClick={() => inlineOps.onSave(record.id)}>保存</Button>
              <Tooltip title="取消编辑：恢复为修改前的内容（不会丢失其他行）">
                <Button size="small" icon={<CloseOutlined />} data-testid="row-cancel-btn" onClick={() => inlineOps.onCancel(record.id)} />
              </Tooltip>
            </Space>
          )
        }
        return (
          <Button size="small" icon={<EditOutlined />} data-testid="row-edit-btn" onClick={() => inlineOps.onEdit(record.id)}>编辑</Button>
        )
      },
    })
  }

  return cols
}