/** Grid 表格主体 — grid 模式下的 Table + 独立分页（从 GridPage 抽出）. */

import { useMemo } from 'react'
import { Table, Button, Empty, Pagination, type TableProps } from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import type { RowResponse } from '@/api'
import type { TableScrollTarget } from './cells/useNewRowAutoScroll'
import { densityToSize, type Density } from '@/theme/tableSettings'

/** 新增行固定 rowKey */
export const NEW_ROW_KEY = '__new__'

export interface GridDisplaySettings {
  density: Density
  bordered: boolean
  showHeader: boolean
  striped: boolean
}

interface GridTableSectionProps {
  tableRef: React.RefObject<TableScrollTarget | null>
  columns: TableProps<RowResponse>['columns']
  settings: GridDisplaySettings
  isLoading: boolean
  rows: RowResponse[]
  total: number
  newRowActive: boolean
  newRowPosition: 'top' | 'tail' | 'page'
  canEditRecords: boolean
  selectedRowKeys: React.Key[]
  onSelectionChange: (keys: React.Key[]) => void
  onAddRow: () => void
  onRowDoubleClick: (record: RowResponse) => void
  /** 列头排序变化：field + direction（null 表示清除该字段排序） */
  onSort: (field: string, direction: 'asc' | 'desc' | null) => void
  gridAreaSize: { width: number; height: number }
  offset: number
  limit: number
  onPageChange: (page: number, pageSize: number) => void
  prefetchNext: (nextOffset: number, l: number) => void
}

const isNewRow = (recordId: unknown) => String(recordId) === NEW_ROW_KEY

export default function GridTableSection({
  tableRef, columns, settings, isLoading, rows, total,
  newRowActive, newRowPosition, canEditRecords,
  selectedRowKeys, onSelectionChange, onAddRow, onRowDoubleClick, onSort,
  gridAreaSize, offset, limit, onPageChange, prefetchNext,
}: GridTableSectionProps) {
  // 排序列点击三态循环：asc → desc → null（取消），由受控 sortOrder 计算下一状态。
  // 不走 antd Table onChange 的 sorter 参数 —— antd 取消排序时因 legacy 兼容逻辑
  // 会把 sorter.field 清成 undefined，事件无法定位字段（详见 gridTableSection.sort.test.tsx）。
  const sortableColumns = useMemo(
    () => columns?.map(col => {
      if ('children' in col) return col
      if (!col.sorter || Array.isArray(col.dataIndex) || typeof col.dataIndex !== 'string') return col
      const field = col.dataIndex
      const next = col.sortOrder === 'ascend' ? 'desc' : col.sortOrder === 'descend' ? null : 'asc'
      return {
        ...col,
        onHeaderCell: () => ({
          onClick: () => onSort(field, next),
          // 键盘可达性：Enter 触发与点击一致的三态循环
          onKeyDown: (e: React.KeyboardEvent) => {
            if (e.keyCode === 13) onSort(field, next)
          },
        }),
      }
    }),
    [columns, onSort],
  )

  return (
    <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column' }}>
      <Table
        ref={tableRef as any}
        rowKey="id" className={`cn-table cn-table-${settings.density}`} size={densityToSize(settings.density)} loading={isLoading} columns={sortableColumns}
        locale={{
          emptyText: (
            <div style={{ padding: '32px 0' }} data-testid="grid-empty-state">
              <Empty description="这张表还没有数据，点击下方按钮录入第一行，或通过「更新/导出」批量导入" />
              <Button
                type="primary"
                icon={<PlusOutlined />}
                style={{ marginTop: 12 }}
                disabled={!canEditRecords}
                onClick={onAddRow}
              >新增一行</Button>
            </div>
          ),
        }}
        dataSource={(() => {
          if (!newRowActive) return rows
          const newRow = { id: NEW_ROW_KEY } as unknown as RowResponse
          return newRowPosition === 'top' ? [newRow, ...rows] : [...rows, newRow]
        })()}
        bordered={settings.bordered}
        showHeader={settings.showHeader}
        style={{ flex: 1, minHeight: 0 }}
        rowClassName={(record, i) => {
          const classes: string[] = []
          if (isNewRow(record.id)) classes.push('cn-table-row-new')
          if (settings.striped && i % 2 === 1) classes.push('table-row-striped')
          return classes.join(' ')
        }}
        rowSelection={{ selectedRowKeys, onChange: onSelectionChange, columnWidth: 40 }}
        pagination={false}
        scroll={{ x: Math.max(gridAreaSize.width, 1200), y: Math.max(gridAreaSize.height - 140, 200) }}
        virtual
        onChange={(_pag, _fil, _sorter, extra) => {
          // 排序已由 onHeaderCell 受控三态循环处理（见 sortableColumns），
          // 这里忽略 sort 动作；仅防分页/筛选变化触发无效处理
          if (extra?.action === 'sort') {
            return
          }
        }}
        onRow={(record) => (
          isNewRow(record.id) ? {} : ({ onDoubleClick: () => onRowDoubleClick(record) })
        )}
      />
      <Pagination
        style={{ marginTop: 12, display: 'flex', justifyContent: 'flex-end' }}
        current={Math.floor(offset / limit) + 1}
        pageSize={limit}
        total={total}
        showSizeChanger
        pageSizeOptions={[25, 50, 100, 200]}
        showTotal={(t) => `共 ${t} 条`}
        onChange={(p, l) => {
          onPageChange(p, l)
          // 预取下一页 —— 只有存在下一页且当前是 grid 模式（非全量拉取）时才预取
          const nextOffset = p * l
          if (nextOffset < total) {
            prefetchNext(nextOffset, l)
          }
        }}
      />
    </div>
  )
}
