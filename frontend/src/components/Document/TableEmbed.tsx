/**
 * 数据表动态引用只读表格 — 文档预览中渲染 `{{table:…}}` 占位。
 *
 * 无 view 参数：直接分页拉取 records；带 view：经视图 rows 端点
 * 应用视图的 filters/sortings。表不存在/无权限时渲染占位提示。
 */

import { useMemo, useState } from 'react'
import { Alert, Skeleton, Space, Table, Typography } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { recordApi, tableApi, viewApi } from '@/api'
import type { Field, RowResponse } from '@/api'
import type { TableRef } from './tableRef'
import RefWidthControl from './RefWidthControl'
import { parseRefWidth } from './refWidth'

const { Text } = Typography

/** 单元格值文本化：null/undefined 显短横，对象序列化，其余转字符串 */
function cellText(value: unknown): string {
  if (value === null || value === undefined) return '-'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

export default function TableEmbed({ workspaceId, tableRef, refOrdinal, onWidthChange }: {
  workspaceId: number
  tableRef: TableRef
  /** 同表在正文中的出现序号（0 基），用于宽度控件定位 */
  refOrdinal?: number
  /** 宽度调整回调；不传不渲染控件（查看 / 游客只读） */
  onWidthChange?: (width: number) => void
}) {
  const [page, setPage] = useState(1)
  const pct = parseRefWidth(tableRef.width)
  const offset = (page - 1) * tableRef.limit

  const tableQuery = useQuery({
    queryKey: ['table-embed', workspaceId, tableRef.tableId, 'detail'],
    queryFn: () => tableApi.get(workspaceId, tableRef.tableId),
    enabled: Number.isFinite(workspaceId) && Number.isFinite(tableRef.tableId),
    retry: false,
  })

  // 行数据：带 view 走视图 rows（应用过滤/排序），否则直接分页拉 records
  const rowsQuery = useQuery({
    queryKey: [
      'table-embed', workspaceId, tableRef.tableId, 'rows',
      tableRef.view ?? null, offset, tableRef.limit,
    ],
    queryFn: async (): Promise<{ items: RowResponse[]; total: number }> => {
      if (tableRef.view) {
        const data = await viewApi.rows(
          workspaceId, tableRef.tableId, tableRef.view, tableRef.limit, offset,
        )
        return { items: data.rows, total: data.total }
      }
      const data = await recordApi.list(workspaceId, tableRef.tableId, {
        offset, limit: tableRef.limit,
      })
      return { items: data.items, total: data.total }
    },
    enabled: tableQuery.isSuccess,
    retry: false,
  })

  const columns = useMemo(() => {
    const fields: Field[] = (tableQuery.data?.fields ?? []).filter(f => !f.hidden)
    return fields.map(f => ({
      title: f.name,
      key: f.name,
      dataIndex: f.name,
      ellipsis: true,
      render: (value: unknown) => cellText(value),
    }))
  }, [tableQuery.data])

  if (tableQuery.isLoading) return <Skeleton active paragraph={{ rows: 3 }} />
  if (tableQuery.isError || !tableQuery.data) {
    return (
      <Alert
        type="warning"
        showIcon
        message="数据表引用无效"
        description={`表 #${tableRef.tableId} 不存在或无访问权限，请检查占位符 {{table:${tableRef.tableId}}} 中的表 ID。`}
        style={{ margin: '0.8em 0' }}
      />
    )
  }

  return (
    <div
      style={{ margin: '0.8em 0', width: `${pct}%`, maxWidth: '100%' }}
      data-testid={`table-embed-${tableRef.tableId}`}
      data-width={pct}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <Text type="secondary" style={{ fontSize: 12 }}>
          {tableQuery.data.name}
          {tableRef.view ? ` · 视图 #${tableRef.view}` : ''}
          {` · 共 ${rowsQuery.data?.total ?? 0} 行`}
        </Text>
        {onWidthChange && (
          <RefWidthControl
            value={pct}
            onChange={onWidthChange}
            testId={`table-embed-width-${tableRef.tableId}-${refOrdinal ?? 0}`}
          />
        )}
      </div>
      <Space direction="vertical" size={0} style={{ width: '100%', overflowX: 'auto' }}>
        <Table
          size="small"
          rowKey={(row: RowResponse) => String(row.id)}
          columns={columns}
          dataSource={rowsQuery.data?.items ?? []}
          loading={rowsQuery.isLoading}
          pagination={{
            current: page,
            pageSize: tableRef.limit,
            total: rowsQuery.data?.total ?? 0,
            showSizeChanger: false,
            onChange: p => setPage(p),
          }}
          scroll={{ x: 'max-content' }}
          style={{ minWidth: '100%' }}
        />
      </Space>
    </div>
  )
}
