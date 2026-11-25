/** 底部聚合条 — 数值列统计 + 批量操作，支持「选中 / 本页 / 全表」三种口径（需求 0147）.
 *
 * - 选中：GridPage 已算好的选中行聚合（原行为，默认）；
 * - 本页：当前页所有可见行的同类聚合（本地算，零请求）；
 * - 全表：走服务端 `POST /records/aggregate`（筛选范围与列表同源，行级权限一致），
 *   数据量大时不会把全表拉到浏览器。
 */

import { useMemo, useState } from 'react'
import { App as AntApp, Button, Segmented, Space, Spin, Tag, Tooltip } from 'antd'
import { CopyOutlined, DeleteOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'

import { recordApi } from '@/api'
import type { Field, RowResponse } from '@/api'

export type AggregateScope = 'selected' | 'page' | 'all'

interface Aggregate {
  count: number
  sum: number
  avg: number
}

interface GridAggregationBarProps {
  selectedCount: number
  aggregates: Record<string, Aggregate>
  copyLoading: boolean
  deleteLoading: boolean
  onCopy: () => void
  onDelete: () => void
  onClear: () => void
  /** 以下为「本页 / 全表」口径所需（缺省时只保留原来的选中口径） */
  wid?: string
  tid?: string
  rows?: RowResponse[]
  filters?: Array<Record<string, unknown>>
  filterLogic?: 'AND' | 'OR'
}

/** 本地聚合：对一组行的某个字段算 count / sum / avg（非数值忽略） */
export function computeLocalAggregate(rows: RowResponse[], fieldName: string): Aggregate {
  let count = 0
  let sum = 0
  for (const row of rows) {
    const raw = row[fieldName]
    if (raw === null || raw === undefined || raw === '') continue
    const value = typeof raw === 'number' ? raw : Number(raw)
    if (!Number.isFinite(value)) continue
    count += 1
    sum += value
  }
  return { count, sum, avg: count ? sum / count : 0 }
}

export default function GridAggregationBar({
  selectedCount, aggregates, copyLoading, deleteLoading, onCopy, onDelete, onClear,
  wid, tid, rows = [], filters, filterLogic,
}: GridAggregationBarProps) {
  const { modal } = AntApp.useApp()
  const [scope, setScope] = useState<AggregateScope>('selected')

  const fieldNames = useMemo(() => Object.keys(aggregates), [aggregates])
  const canSwitch = Boolean(wid && tid)

  const allQuery = useQuery({
    queryKey: ['records-aggregate', wid, tid, fieldNames.join(','), JSON.stringify(filters ?? []), filterLogic],
    queryFn: () =>
      recordApi.aggregate(wid!, tid!, {
        metrics: fieldNames.flatMap(name => [
          { field: name, agg: 'sum' as const, alias: `${name}__sum` },
          { field: name, agg: 'avg' as const, alias: `${name}__avg` },
          { field: name, agg: 'count' as const, alias: `${name}__count` },
        ]),
        filters: filters?.length ? filters : undefined,
        filter_logic: filterLogic,
      }),
    enabled: canSwitch && scope === 'all' && fieldNames.length > 0,
    staleTime: 10_000,
  })

  /** 当前口径下的展示数据 */
  const shown: Record<string, Aggregate> = useMemo(() => {
    if (scope === 'page') {
      return Object.fromEntries(fieldNames.map(name => [name, computeLocalAggregate(rows, name)]))
    }
    if (scope === 'all') {
      const metrics = allQuery.data?.rows?.[0]?.metrics ?? {}
      return Object.fromEntries(
        fieldNames.map(name => [
          name,
          {
            sum: Number(metrics[`${name}__sum`] ?? 0),
            avg: Number(metrics[`${name}__avg`] ?? 0),
            count: Number(metrics[`${name}__count`] ?? 0),
          },
        ]),
      )
    }
    return aggregates
  }, [scope, fieldNames, rows, aggregates, allQuery.data])

  if (selectedCount <= 0) return null

  const scopeHint =
    scope === 'page'
      ? '当前页可见行的统计'
      : scope === 'all'
        ? '全表统计（与当前视图筛选同源，受行级权限约束）'
        : '仅统计选中的行'

  return (
    <div className="cn-agg-bar" style={{ padding: '6px 12px', display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
      <span className="cn-agg-count">已选 {selectedCount} 行</span>
      {canSwitch && (
        <Tooltip title={scopeHint}>
          <Segmented<AggregateScope>
            size="small"
            data-testid="grid-agg-scope"
            value={scope}
            onChange={value => setScope(value)}
            options={[
              { label: '选中', value: 'selected' },
              { label: '本页', value: 'page' },
              { label: '全表', value: 'all' },
            ]}
          />
        </Tooltip>
      )}
      <Space size="middle">
        {allQuery.isFetching && scope === 'all' && <Spin size="small" />}
        {fieldNames.map(name => (
          <Tag key={name} style={{ margin: 0 }} data-testid={`grid-agg-${name}`}>
            {name}: {shown[name]?.count ?? 0}条 · 和 {(shown[name]?.sum ?? 0).toFixed(2)} · 均值{' '}
            {(shown[name]?.avg ?? 0).toFixed(2)}
          </Tag>
        ))}
        {scope === 'all' && allQuery.isError && (
          <Tag color="red">全表统计失败：{allQuery.error instanceof Error ? allQuery.error.message : '未知错误'}</Tag>
        )}
      </Space>
      <div style={{ marginLeft: 'auto' }}>
        <Space>
          <Button size="small" icon={<CopyOutlined />} loading={copyLoading} onClick={onCopy}>复制选中</Button>
          <Button size="small" danger icon={<DeleteOutlined />}
            onClick={() => modal.confirm({
              title: `确定删除 ${selectedCount} 行？`,
              onOk: onDelete,
            })}
            loading={deleteLoading}>删除选中</Button>
          <Button size="small" onClick={onClear}>取消选择</Button>
        </Space>
      </div>
    </div>
  )
}

/** 网格页需要对「本页/全表」口径有感知的字段（数值列名） */
export function numericFieldNames(fields: Field[]): string[] {
  return fields
    .filter(f => !f.trashed && ['number', 'float', 'percentage'].includes(f.field_type))
    .map(f => f.name)
}
