import React, { useMemo, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { Table, Button, Space, Tag, Input, Modal, Typography, message, Tooltip, Dropdown, Empty, Row, Col, Badge } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { PlusOutlined, DeleteOutlined, ReloadOutlined, ColumnHeightOutlined, FilterOutlined, MoreOutlined, ArrowLeftOutlined, EyeOutlined, SettingOutlined, AppstoreOutlined } from '@ant-design/icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { tableApi, recordApi } from '@/api'
import type { RowResponse, Field, TableDetail } from '@/api'
import GridCell from './components/GridCell'
import RowDetailDrawer from './components/RowDetailDrawer'
import FieldManager from '@/pages/modals/FieldManager'
import { useResponsive } from '@/hooks/useResponsive'

const { Text } = Typography
type ViewMode = 'grid' | 'kanban' | 'gallery'

export default function GridPage() {
  const { wid, tid } = useParams<{ wid: string; tid: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { isMobile } = useResponsive()
  const [mode, setMode] = useState<ViewMode>('grid')
  const [selectedRowKeys, setSelectedRowKeys] = useState<React.Key[]>([])
  const [detailOpen, setDetailOpen] = useState(false)
  const [detailRow, setDetailRow] = useState<RowResponse | null>(null)
  const [fieldMgrOpen, setFieldMgrOpen] = useState(false)
  const [offset, setOffset] = useState(0)
  const [limit, setLimit] = useState(50)
  const tableKey = `${wid}/${tid}`

  const { data: table, isLoading } = useQuery<TableDetail>({
    queryKey: ['table', tableKey],
    queryFn: () => tableApi.get(wid!, tid!),
    enabled: !!wid && !!tid,
  })
  const { data: rowList = { items: [], total: 0, offset: 0, limit: 0 } } = useQuery({
    queryKey: ['table-records', tableKey, offset, limit],
    queryFn: () => recordApi.list(wid!, tid!, { offset, limit }),
    enabled: !!wid && !!tid,
  })
  const deleteRows = useMutation({
    mutationFn: (ids: React.Key[]) => recordApi.bulkDelete(wid!, tid!, ids as Array<number | string>),
    onSuccess: () => {
      message.success('已删除')
      queryClient.invalidateQueries({ queryKey: ['table-records', tableKey] })
      queryClient.invalidateQueries({ queryKey: ['table', tableKey] })
      setSelectedRowKeys([])
    },
  })
  const quickAdd = useMutation({
    mutationFn: () => recordApi.create(wid!, tid!, { values: {} }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['table-records', tableKey] })
      queryClient.invalidateQueries({ queryKey: ['table', tableKey] })
    },
  })
  const updateRow = useMutation({
    mutationFn: async (args: { rowId: number | string; fieldName: string; value: unknown }) => {
      const payload: Record<string, unknown> = { [args.fieldName]: args.value }
      return recordApi.update(wid!, tid!, args.rowId, { values: payload })
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['table-records', tableKey] })
    },
    onError: (err) => {
      message.error(err instanceof Error ? err.message : '保存失败')
    },
  })

  if (!wid || !tid) return <Empty description="无效的表 ID" style={{ padding: 48 }} />

    const columns = buildColumns(table?.fields || [],
    updateRow.isPending
      ? undefined
      : (rowId, fieldName, value) => updateRow.mutateAsync({ rowId, fieldName, value }),
  )
  const numericFields = (table?.fields || []).filter(f => ['number', 'decimal'].includes(f.field_type))
  const selectedRows = (rowList.items || []).filter(r => selectedRowKeys.includes(r.id))
  const aggregates = useMemo(() => {
    const out: Record<string, { count: number; sum: number; avg: number }> = {}
    for (const f of numericFields) {
      let sum = 0, count = 0
      for (const r of selectedRows) {
        const col = f.name
        const v = Number(r[col])
        if (!Number.isNaN(v)) { sum += v; count++ }
      }
      if (count > 0) out[f.name] = { count, sum, avg: sum / count }
    }
    return out
  }, [selectedRows, numericFields])

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0 }}>
      <div style={{ padding: '12px 16px', borderBottom: '1px solid #e5e7eb', background: '#fff', display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center' }}>
        <Button icon={<ArrowLeftOutlined />} onClick={() => navigate(`/w/${wid}`)}>返回</Button>
        <Text strong style={{ fontSize: 16 }}>{table?.name || '...'}</Text>
        <div style={{ flex: 1 }} />
        <Space>
          <Button.Group>
            <Button type={mode === 'grid' ? 'primary' : 'default'} icon={<ColumnHeightOutlined />} onClick={() => setMode('grid')}>{!isMobile && '表格'}</Button>
            <Button type={mode === 'kanban' ? 'primary' : 'default'} icon={<AppstoreOutlined />} onClick={() => setMode('kanban')}>{!isMobile && '看板'}</Button>
            <Button type={mode === 'gallery' ? 'primary' : 'default'} icon={<EyeOutlined />} onClick={() => setMode('gallery')}>{!isMobile && '画廊'}</Button>
          </Button.Group>
          <Tooltip title="字段管理"><Button icon={<SettingOutlined />} onClick={() => setFieldMgrOpen(true)} /></Tooltip>
          <Dropdown menu={{ items: [
            { key: 'refresh', icon: <ReloadOutlined />, label: '刷新', onClick: () => queryClient.invalidateQueries({ queryKey: ['table-records', tableKey] }) },
            { type: 'divider' },
            { key: 'delete', icon: <DeleteOutlined />, danger: true, label: '删除表', disabled: true },
          ] }}><Button icon={<MoreOutlined />} /></Dropdown>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => quickAdd.mutate()}>新增行</Button>
        </Space>
      </div>

      <div style={{ flex: 1, overflow: 'auto', padding: '12px 16px', background: '#fafafa' }}>
        {isLoading ? (
          <div style={{ textAlign: 'center', padding: 48 }}>加载中...</div>
        ) : mode === 'grid' ? (
          <Table
            rowKey="id" size="middle" loading={isLoading} columns={columns} dataSource={rowList.items || []}
            rowSelection={{ selectedRowKeys, onChange: setSelectedRowKeys }}
            pagination={{
              current: Math.floor(offset / limit) + 1, pageSize: limit, total: rowList.total,
              showSizeChanger: true, pageSizeOptions: [25, 50, 100, 200],
              onChange: (p, l) => { setOffset((p - 1) * l); setLimit(l) },
              showTotal: (t) => `共 ${t} 条`,
            }}
            scroll={{ x: Math.max(800, (table?.fields.length || 4) * 160) }}
            onRow={(record) => ({ onDoubleClick: () => { setDetailRow(record); setDetailOpen(true) } })}
          />
        ) : mode === 'kanban' ? (
          <KanbanView rows={rowList.items || []} fields={table?.fields || []} />
        ) : (
          <GalleryView rows={rowList.items || []} fields={table?.fields || []} />
        )}
      </div>

      {selectedRowKeys.length > 0 && (
        <div style={{ padding: '8px 16px', borderTop: '1px solid #e5e7eb', background: '#fff', display: 'flex', alignItems: 'center', gap: 16, flexWrap: 'wrap' }}>
          <Badge color="blue" text={`已选 ${selectedRowKeys.length} 行`} />
          <Space size="middle">
            {Object.entries(aggregates).map(([name, a]) => (
              <Tag key={name} style={{ margin: 0 }}>{name}: {a.count}条 · 和 {a.sum.toFixed(2)} · 均值 {a.avg.toFixed(2)}</Tag>
            ))}
          </Space>
          <div style={{ marginLeft: 'auto' }}>
            <Space>
              <Button size="small" danger icon={<DeleteOutlined />}
                onClick={() => Modal.confirm({ title: `确定删除 ${selectedRowKeys.length} 行？`, onOk: () => deleteRows.mutate(selectedRowKeys) })}
                loading={deleteRows.isPending}>删除选中</Button>
              <Button size="small" onClick={() => setSelectedRowKeys([])}>取消选择</Button>
            </Space>
          </div>
        </div>
      )}

      <RowDetailDrawer open={detailOpen} row={detailRow} fields={table?.fields || []} wid={wid} tid={tid} onClose={() => { setDetailOpen(false); setDetailRow(null) }} />
      <FieldManager open={fieldMgrOpen} wid={wid} tid={tid} fields={table?.fields || []}
        onClose={() => setFieldMgrOpen(false)}
        onChanged={() => {
          queryClient.invalidateQueries({ queryKey: ['table', tableKey] })
          queryClient.invalidateQueries({ queryKey: ['table-records', tableKey] })
        }}
      />
      <span style={{ display: 'none' }}><FilterOutlined /><Input /></span>
    </div>
  )
}

function buildColumns(
  fields: Field[],
  onCellSave?: (rowId: number | string, fieldName: string, value: unknown) => Promise<void>,
): ColumnsType<RowResponse> {
  return fields.filter(f => !f.hidden).sort((a, b) => (a.order ?? 0) - (b.order ?? 0))
    .map<NonNullable<ColumnsType<RowResponse>>[number]>(f => ({
      key: String(f.id),
      title: <span>{f.name}{f.required && <span style={{ color: '#ff4d4f' }}>*</span>}</span>,
      dataIndex: f.name,
      ellipsis: true,
      width: 160,
      render: (v: unknown, record: RowResponse) => (
        <GridCell
          value={v}
          field={f}
          rowId={record.id}
          onSave={onCellSave ? (fieldName, value) => onCellSave(record.id, fieldName, value) : undefined}
        />
      ),
    }))
}

function KanbanView({ rows, fields }: { rows: RowResponse[]; fields: Field[] }) {
  const selectField = fields.find(f => f.field_type === 'select')
  const cols: Array<{ key: string; title: string; rows: RowResponse[] }> = []
  if (selectField) {
    const col = selectField.name
    const groups = new Map<string, RowResponse[]>()
    for (const r of rows) {
      const v = String(r[col] || '未分类')
      if (!groups.has(v)) groups.set(v, [])
      groups.get(v)!.push(r)
    }
    for (const [title, list] of groups) cols.push({ key: title, title, rows: list })
  } else {
    cols.push({ key: 'all', title: '全部', rows })
  }
  return (
    <div style={{ display: 'flex', gap: 16, overflowX: 'auto', paddingBottom: 16 }}>
      {cols.map(c => (
        <div key={c.key} style={{ minWidth: 280, background: '#fff', borderRadius: 8, padding: 12, border: '1px solid #e5e7eb' }}>
          <Text strong>{c.title} <span style={{ color: '#9ca3af', fontSize: 12 }}>({c.rows.length})</span></Text>
          {c.rows.map(r => (
            <div key={r.id} style={{ padding: 12, marginBottom: 8, border: '1px solid #e5e7eb', borderRadius: 6 }}>
              {String(r[fields.find(f => f.is_primary)?.name || 'id'] ?? r.id)}
            </div>
          ))}
        </div>
      ))}
    </div>
  )
}

function GalleryView({ rows, fields }: { rows: RowResponse[]; fields: Field[] }) {
  const titleField = fields.find(f => f.field_type === 'text') || fields.find(f => f.is_primary)
  const titleCol = titleField?.name || 'id'
  return (
    <Row gutter={[16, 16]}>
      {rows.map(r => (
        <Col xs={24} sm={12} md={8} lg={6} key={r.id}>
          <div style={{ padding: 16, border: '1px solid #e5e7eb', borderRadius: 8, background: '#fff', cursor: 'pointer' }}>
            <div style={{ fontWeight: 600, marginBottom: 8 }}>{String(r[titleCol] ?? r.id)}</div>
            <div style={{ fontSize: 12, color: '#6b7280' }}>ID: {r.id}</div>
          </div>
        </Col>
      ))}
      {rows.length === 0 && <Empty description="暂无记录" style={{ padding: 48 }} />}
    </Row>
  )
}
