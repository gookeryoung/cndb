/** dashboard 明细表格组件（只读，ADR 0023 P2）.
 *
 * - 列白名单与行数上限由配置驱动（≤8 列 / ≤50 行）；
 * - 点击表头本地排序（升序 / 降序切换），不写回视图配置；
 * - 点击行触发 `onRowClick`，复用既有 `RowDetailDrawer`；
 * - 大表由服务端返回裁剪后的 `TableDataset`，小表直接用已拉取行集。
 */

import { useMemo, useState } from 'react'
import type { RowResponse } from '@/api'
import type { DashboardTableWidget } from '../dashboardModel'
import type { TableDataset } from '../chart/types'

type SortState = { field: string; dir: 'asc' | 'desc' } | null

function toSortable(value: unknown): number | string | null {
  if (value === null || value === undefined || value === '') return null
  if (typeof value === 'number') return Number.isFinite(value) ? value : null
  const text = String(value)
  const num = Number(text)
  return Number.isFinite(num) ? num : text
}

function compareRows(a: RowResponse, b: RowResponse, field: string): number {
  const left = toSortable(a[field])
  const right = toSortable(b[field])
  if (left === null && right === null) return 0
  if (left === null) return 1
  if (right === null) return -1
  if (typeof left === 'number' && typeof right === 'number') return left - right
  return String(left).localeCompare(String(right), 'zh-CN')
}

export interface TableWidgetProps {
  widget: Extract<DashboardTableWidget, { type: 'table' }>
  rows: RowResponse[]
  /** 服务端返回的明细（大表路径） */
  dataset?: TableDataset
  onRowClick?: (row: RowResponse) => void
}

export default function TableWidget({ widget, rows, dataset, onRowClick }: TableWidgetProps) {
  const columns = dataset?.columns?.length ? dataset.columns : widget.table.columns
  const source = dataset?.rows ?? rows
  const [sort, setSort] = useState<SortState>(null)

  const body = useMemo(() => {
    if (!sort) return source.slice(0, widget.table.row_limit)
    const ordered = [...source].sort((a, b) => {
      const c = compareRows(a, b, sort.field)
      return sort.dir === 'asc' ? c : -c
    })
    return ordered.slice(0, widget.table.row_limit)
  }, [source, sort, widget.table.row_limit])

  const toggleSort = (field: string) => {
    setSort((prev) => {
      if (!prev || prev.field !== field) return { field, dir: 'asc' }
      return prev.dir === 'asc' ? { field, dir: 'desc' } : null
    })
  }

  return (
    <div data-testid={`dashboard-table-${widget.id}`} style={{ flex: 1, minHeight: 0, overflow: 'auto' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
        <thead>
          <tr>
            {columns.map((name) => {
              const active = sort?.field === name
              return (
                <th
                  key={name}
                  onClick={() => toggleSort(name)}
                  data-testid={`dashboard-table-head-${widget.id}-${name}`}
                  aria-sort={active ? (sort.dir === 'asc' ? 'ascending' : 'descending') : 'none'}
                  style={{
                    position: 'sticky', top: 0, zIndex: 1, textAlign: 'left', padding: '6px 8px',
                    borderBottom: '1px solid var(--cn-border)', background: 'var(--cn-bg-page)',
                    color: 'var(--cn-text-secondary)', fontWeight: 600, whiteSpace: 'nowrap',
                    cursor: 'pointer', userSelect: 'none',
                  }}
                >
                  {name}
                  {active && (sort.dir === 'asc' ? ' ▲' : ' ▼')}
                </th>
              )
            })}
          </tr>
        </thead>
        <tbody>
          {body.map((row, i) => (
            <tr
              key={row.id ?? i}
              onClick={onRowClick ? () => onRowClick(row) : undefined}
              data-testid={`dashboard-table-row-${widget.id}-${i}`}
              style={{ cursor: onRowClick ? 'pointer' : undefined }}
            >
              {columns.map((name) => (
                <td
                  key={name}
                  style={{
                    padding: '6px 8px', borderBottom: '1px solid var(--cn-border)',
                    color: 'var(--cn-text-primary)', maxWidth: 220, overflow: 'hidden',
                    textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                  }}
                  title={String(row[name] ?? '')}
                >
                  {String(row[name] ?? '')}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {body.length === 0 && (
        <div data-testid={`dashboard-table-empty-${widget.id}`} style={{ padding: 12, fontSize: 12, color: 'var(--cn-text-secondary)' }}>
          暂无数据
        </div>
      )}
    </div>
  )
}
