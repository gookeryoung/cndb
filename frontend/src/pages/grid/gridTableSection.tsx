/** Grid 表格主体 — grid 模式下的 Table + 独立分页（从 GridPage 抽出）.
 *
 * 表头交互统一在 sortableColumns useMemo 注入：
 *   排序 —— onHeaderCell 点击三态循环（asc → desc → null，见 gridTableSection.sort.test.tsx）
 *   调宽 —— th 右缘 8px 热区 mousedown + document mousemove/mouseup，提交 onColumnResize
 *   列序 —— th 原生 HTML5 dragstart/drop，提交 onColumnOrderMove
 */

import { useCallback, useMemo, useRef, useState } from 'react'
import { Table, Button, Empty, Pagination, type TableProps } from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import type { RowResponse } from '@/api'
import type { TableScrollTarget } from './cells/useNewRowAutoScroll'
import { densityToSize, type Density } from '@/theme/tableSettings'
import { MIN_COLUMN_WIDTH, MAX_COLUMN_WIDTH } from './cells/buildColumns'

/** 新增行固定 rowKey */
export const NEW_ROW_KEY = '__new__'

/** resize 热区宽度（th 右缘像素数） */
const RESIZE_HOTZONE_PX = 8

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
  /** 列宽拖拽结束：fieldId（字段 id 字符串）+ 最终宽度（调用方负责持久化） */
  onColumnResize?: (fieldId: string, width: number) => void
  /** 拖拽列 srcFieldId 落到 targetFieldId 上（列序调整，调用方负责持久化） */
  onColumnOrderMove?: (srcFieldId: string, targetFieldId: string) => void
  gridAreaSize: { width: number; height: number }
  offset: number
  limit: number
  onPageChange: (page: number, pageSize: number) => void
  prefetchNext: (nextOffset: number, l: number) => void
}

const isNewRow = (recordId: unknown) => String(recordId) === NEW_ROW_KEY

/** 夹取列宽到 [MIN, MAX] */
const clampWidth = (w: number) => Math.min(Math.max(w, MIN_COLUMN_WIDTH), MAX_COLUMN_WIDTH)

export default function GridTableSection({
  tableRef, columns, settings, isLoading, rows, total,
  newRowActive, newRowPosition, canEditRecords,
  selectedRowKeys, onSelectionChange, onAddRow, onRowDoubleClick, onSort,
  onColumnResize, onColumnOrderMove,
  gridAreaSize, offset, limit, onPageChange, prefetchNext,
}: GridTableSectionProps) {
  // resize 拖拽中的实时预览宽度（key 为列 key）；拖拽结束清空、宽度交由视图持久化
  const [previewWidths, setPreviewWidths] = useState<Record<string, number>>({})
  // resize 状态（ref：跨 mousemove/mouseup 事件共享，不触发渲染）
  const resizeRef = useRef<{ colKey: string; startX: number; startWidth: number } | null>(null)
  // 当前 HTML5 拖拽的源列 key
  const dragColRef = useRef<string | null>(null)
  // resize 结束后的首个 click 需要吞掉，防止误触排序
  const suppressClickRef = useRef(false)

  /** 在 th 右缘热区 mousedown —— 开始列宽拖拽 */
  const beginResize = useCallback((e: React.MouseEvent, colKey: string, startWidth: number) => {
    e.preventDefault()
    e.stopPropagation()
    resizeRef.current = { colKey, startX: e.clientX, startWidth }
    suppressClickRef.current = true
    const onMove = (ev: MouseEvent) => {
      const r = resizeRef.current
      if (!r) return
      setPreviewWidths(p => ({ ...p, [r.colKey]: clampWidth(r.startWidth + ev.clientX - r.startX) }))
    }
    const onUp = (ev: MouseEvent) => {
      document.removeEventListener('mousemove', onMove)
      document.removeEventListener('mouseup', onUp)
      const r = resizeRef.current
      resizeRef.current = null
      setPreviewWidths(p => {
        const { [r?.colKey ?? '']: _drop, ...rest } = p
        return rest
      })
      if (r) onColumnResize?.(r.colKey, clampWidth(r.startWidth + ev.clientX - r.startX))
    }
    document.addEventListener('mousemove', onMove)
    document.addEventListener('mouseup', onUp)
  }, [onColumnResize])

  // 排序列点击三态循环：asc → desc → null（取消），由受控 sortOrder 计算下一状态。
  // 不走 antd Table onChange 的 sorter 参数 —— antd 取消排序时因 legacy 兼容逻辑
  // 会把 sorter.field 清成 undefined，事件无法定位字段（详见 gridTableSection.sort.test.tsx）。
  const sortableColumns = useMemo(
    () => columns?.map(col => {
      if ('children' in col) return col
      const colKey = typeof col.key === 'string' ? col.key : String(col.key)
      const numericWidth = typeof col.width === 'number' ? col.width : undefined
      // resize 拖拽中的实时宽度预览
      const width = previewWidths[colKey] ?? numericWidth

      const headerCell: Record<string, unknown> = {}

      // 排序三态循环（操作列无 sorter，不注入）
      if (col.sorter && !Array.isArray(col.dataIndex) && typeof col.dataIndex === 'string') {
        const field = col.dataIndex
        const next = col.sortOrder === 'ascend' ? 'desc' : col.sortOrder === 'descend' ? null : 'asc'
        headerCell.onClick = () => {
          if (suppressClickRef.current) {
            suppressClickRef.current = false
            return
          }
          onSort(field, next)
        }
        headerCell.onKeyDown = (e: React.KeyboardEvent) => {
          // 键盘可达性：Enter 触发与点击一致的三态循环
          if (e.keyCode === 13) onSort(field, next)
        }
      }

      // 调宽热区 + 列序拖拽（操作列 __row_ops__ 不参与，宽度未知的列不注入 resize）
      if (colKey !== '__row_ops__' && numericWidth !== undefined) {
        headerCell.onMouseDown = (e: React.MouseEvent) => {
          const rect = (e.currentTarget as HTMLElement).getBoundingClientRect()
          // 右缘热区内才启动 resize；否则放行（默认行为 + onClick 排序）
          if (rect.right - e.clientX <= RESIZE_HOTZONE_PX) {
            beginResize(e, colKey, numericWidth)
          }
        }
        headerCell.onMouseMove = (e: React.MouseEvent) => {
          const el = e.currentTarget as HTMLElement
          const rect = el.getBoundingClientRect()
          el.style.cursor = rect.right - e.clientX <= RESIZE_HOTZONE_PX ? 'col-resize' : ''
        }
        headerCell.onMouseLeave = (e: React.MouseEvent) => {
          (e.currentTarget as HTMLElement).style.cursor = ''
        }
        headerCell.draggable = true
        headerCell.onDragStart = (e: React.DragEvent) => {
          // resize 进行中禁止拖列序（互斥）
          if (resizeRef.current) {
            e.preventDefault()
            return
          }
          dragColRef.current = colKey
          e.dataTransfer.setData('text/plain', colKey)
          e.dataTransfer.effectAllowed = 'move'
        }
        headerCell.onDragOver = (e: React.DragEvent) => {
          e.preventDefault()
          e.dataTransfer.dropEffect = 'move'
        }
        headerCell.onDrop = (e: React.DragEvent) => {
          e.preventDefault()
          const src = dragColRef.current
          dragColRef.current = null
          if (src && src !== colKey) onColumnOrderMove?.(src, colKey)
        }
      }

      return { ...col, width, onHeaderCell: () => headerCell }
    }),
    [columns, onSort, onColumnOrderMove, previewWidths, beginResize],
  )

  // 横向滚动宽度 = 各列宽之和（含 rowSelection 40），保证列宽自适应后无空白拉伸
  const scrollX = Math.max(
    1200,
    (columns ?? []).reduce((sum, col) => sum + (typeof col.width === 'number' ? col.width : 160), 0) + 40,
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
        scroll={{ x: scrollX, y: Math.max(gridAreaSize.height - 140, 200) }}
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
