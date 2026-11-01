/** 画布全局筛选条（ADR 0023 P3）.
 *
 * 只负责收集 `global_filters` 的值（date_range / select / search），
 * 值的注入由 `dashboardGlobals.resolveQueryGlobals` 在取数前统一改写 filters；
 * 组件本身不读取行数据，也不做条件拼接。
 */

import { Button, DatePicker, Input, Select, Space } from 'antd'
import dayjs, { type Dayjs } from 'dayjs'
import type { DashboardGlobalFilter } from './dashboardModel'
import type { DashboardGlobals } from './dashboardGlobals'

export interface GlobalFilterBarProps {
  filters: DashboardGlobalFilter[]
  values: DashboardGlobals
  onChange: (values: DashboardGlobals) => void
  /** 只读模式下不允许改值 */
  disabled?: boolean
}

function rangeValue(raw: unknown): [Dayjs | null, Dayjs | null] | null {
  if (!Array.isArray(raw) || raw.length < 2) return null
  const start = raw[0] ? dayjs(String(raw[0])) : null
  const end = raw[1] ? dayjs(String(raw[1])) : null
  if (!start && !end) return null
  return [start, end]
}

export default function GlobalFilterBar({
  filters,
  values,
  onChange,
  disabled = false,
}: GlobalFilterBarProps) {
  if (!filters.length) return null
  const setValue = (id: string, value: unknown) => {
    const next = { ...values }
    const empty = value == null || value === '' || (Array.isArray(value) && value.length === 0)
    if (empty) delete next[id]
    else next[id] = value
    onChange(next)
  }

  return (
    <div
      data-testid="dashboard-globals"
      style={{
        flexShrink: 0, display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap',
        padding: '6px 12px', borderBottom: '1px solid var(--cn-border)',
        background: 'var(--cn-bg-container)',
      }}
    >
      {filters.map((filter) => {
        const label = filter.label || filter.field
        const common = { size: 'small' as const, disabled, 'aria-label': label }
        if (filter.kind === 'date_range') {
          return (
            <DatePicker.RangePicker
              key={filter.id}
              {...common}
              data-testid={`dashboard-global-${filter.id}`}
              value={rangeValue(values[filter.id])}
              onChange={(dates) => {
                if (!dates || !dates[0] || !dates[1]) {
                  setValue(filter.id, undefined)
                  return
                }
                setValue(filter.id, [dates[0].format('YYYY-MM-DD'), dates[1].format('YYYY-MM-DD')])
              }}
            />
          )
        }
        if (filter.kind === 'select') {
          const current = values[filter.id]
          return (
            <Select
              key={filter.id}
              {...common}
              mode="tags"
              allowClear
              placeholder={label}
              style={{ minWidth: 160 }}
              data-testid={`dashboard-global-${filter.id}`}
              value={Array.isArray(current) ? (current as string[]) : undefined}
              onChange={(next: string[]) => setValue(filter.id, next)}
            />
          )
        }
        return (
          <Input.Search
            key={filter.id}
            {...common}
            allowClear
            placeholder={label}
            style={{ width: 200 }}
            data-testid={`dashboard-global-${filter.id}`}
            value={typeof values[filter.id] === 'string' ? (values[filter.id] as string) : ''}
            onChange={(event) => setValue(filter.id, event.target.value)}
          />
        )
      })}
      {Object.keys(values).length > 0 && (
        <Space>
          <Button size="small" disabled={disabled} onClick={() => onChange({})} data-testid="dashboard-globals-reset">
            清除筛选
          </Button>
        </Space>
      )}
    </div>
  )
}
