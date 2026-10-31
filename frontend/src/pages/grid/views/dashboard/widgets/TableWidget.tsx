/** dashboard 明细表格组件（只读，ADR 0023 P0）.
 *
 * P0 仅按列的字段名直出，不接格式化/单元格编辑器；表头与行内容均由 columns 白名单驱动。
 */
import type { RowResponse } from '@/api'
import type { DashboardTableWidget } from '../dashboardModel'

export default function TableWidget({
  widget,
  rows,
}: {
  widget: DashboardTableWidget
  rows: RowResponse[]
}) {
  const columns = widget.table.columns
  const body = rows.slice(0, widget.table.row_limit)
  return (
    <div data-testid={`dashboard-table-${widget.id}`} style={{ flex: 1, minHeight: 0, overflow: 'auto' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
        <thead>
          <tr>
            {columns.map((name) => (
              <th
                key={name}
                style={{
                  position: 'sticky', top: 0, zIndex: 1, textAlign: 'left', padding: '6px 8px',
                  borderBottom: '1px solid var(--cn-border)', background: 'var(--cn-bg-page)',
                  color: 'var(--cn-text-secondary)', fontWeight: 600, whiteSpace: 'nowrap',
                }}
              >
                {name}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {body.map((row, i) => (
            <tr key={row.id ?? i}>
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
