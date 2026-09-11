/** Grid 主应用 — 集成视图 Tab / 三种视图 / inline 编辑 / 导入导出 / 行复制. */

import { useMemo, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { Table, Button, Space, Tag, Modal, Typography, message, Tooltip, Dropdown, Empty, Row, Col, Badge, Input, Tabs, Select, Form, Switch } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import {
  PlusOutlined, DeleteOutlined, ReloadOutlined, ColumnHeightOutlined,
  FilterOutlined, MoreOutlined, ArrowLeftOutlined, EyeOutlined, SettingOutlined,
  AppstoreOutlined, CopyOutlined, ImportOutlined, DownOutlined, CloseOutlined,
} from '@ant-design/icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { tableApi, recordApi, viewApi } from '@/api'
import type { RowResponse, Field, TableDetail, View, ViewCreate } from '@/api'
import GridCell from './components/GridCell'
import RowDetailDrawer from './components/RowDetailDrawer'
import FieldManager from '@/pages/modals/FieldManager'
import ImportExportDialog from '@/pages/modals/ImportExportDialog'
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
  const [importExportOpen, setImportExportOpen] = useState(false)
  const [viewConfigOpen, setViewConfigOpen] = useState(false)
  const [activeViewId, setActiveViewId] = useState<number | string | null>(null)
  const [viewFilters, setViewFilters] = useState<Record<string, unknown> | null>(null)
  const [offset, setOffset] = useState(0)
  const [limit, setLimit] = useState(50)
  const tableKey = `${wid}/${tid}`

  const { data: table, isLoading } = useQuery<TableDetail>({
    queryKey: ['table', tableKey],
    queryFn: () => tableApi.get(wid!, tid!),
    enabled: !!wid && !!tid,
  })
  const { data: views = [] } = useQuery<View[]>({
    queryKey: ['table-views', tableKey],
    queryFn: () => viewApi.list(wid!, tid!),
    enabled: !!wid && !!tid,
  })
  // 加载 active view 的 filters
  const loadView = (v: View | null) => {
    if (v) {
      setActiveViewId(v.id)
      setViewFilters(v.filters ?? null)
      if (v.view_type === 'kanban') setMode('kanban')
      else if (v.view_type === 'gallery') setMode('gallery')
      else setMode('grid')
    } else {
      setActiveViewId(null)
      setViewFilters(null)
      setMode('grid')
    }
    setOffset(0)
  }

  const { data: rowList = { items: [], total: 0, offset: 0, limit: 0 } } = useQuery({
    queryKey: ['table-records', tableKey, offset, limit, viewFilters],
    queryFn: () => recordApi.list(wid!, tid!, { offset, limit, filters: viewFilters ?? undefined }),
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
  const copyRow = useMutation({
    mutationFn: async (ids: Array<number | string>) => {
      const copies: Array<Record<string, unknown>> = []
      for (const id of ids) {
        const r = rowList.items.find(x => x.id === id)
        if (r) {
          const { id: _skip, created_at: _c, updated_at: _u, created_by: _cb, updated_by: _ub, ...rest } = r
          copies.push(rest as Record<string, unknown>)
        }
      }
      if (copies.length === 0) return []
      return recordApi.bulkCreate(wid!, tid!, copies.map(values => ({ values })))
    },
    onSuccess: (ids) => {
      message.success(`已复制 ${ids.length} 行`)
      queryClient.invalidateQueries({ queryKey: ['table-records', tableKey] })
      queryClient.invalidateQueries({ queryKey: ['table', tableKey] })
    },
  })
  const createView = useMutation({
    mutationFn: (data: ViewCreate) => viewApi.create(wid!, tid!, data),
    onSuccess: () => {
      message.success('视图已创建')
      queryClient.invalidateQueries({ queryKey: ['table-views', tableKey] })
    },
  })
  const removeView = useMutation({
    mutationFn: (vid: number | string) => viewApi.remove(wid!, tid!, vid),
    onSuccess: () => {
      message.success('视图已删除')
      setActiveViewId(null)
      queryClient.invalidateQueries({ queryKey: ['table-views', tableKey] })
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

  // 视图 Tab 项（全部 + 各自定义视图）
  const viewTabItems: Array<{ key: string; label: React.ReactNode; closable?: boolean }> = [
    { key: 'all', label: <span>全部</span> },
    ...views.map(v => ({
      key: String(v.id),
      label: (
        <span>
          {v.name}
          {v.default && <Tag color="blue" style={{ marginLeft: 4 }}>默认</Tag>}
        </span>
      ),
      closable: true,
    })),
  ]

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0 }}>
      {/* 顶部工具栏 */}
      <div style={{ padding: '12px 16px', borderBottom: '1px solid #e5e7eb', background: '#fff', display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center' }}>
        <Button icon={<ArrowLeftOutlined />} onClick={() => navigate(`/w/${wid}`)}>返回</Button>
        <Text strong style={{ fontSize: 16 }}>{table?.name || '...'}</Text>
        <div style={{ flex: 1 }} />
        <Space>
          <Tooltip title="字段管理"><Button icon={<SettingOutlined />} onClick={() => setFieldMgrOpen(true)} /></Tooltip>
          <Button icon={<ImportOutlined />} onClick={() => setImportExportOpen(true)}>导入/导出</Button>
          <Dropdown menu={{ items: [
            { key: 'refresh', icon: <ReloadOutlined />, label: '刷新', onClick: () => queryClient.invalidateQueries({ queryKey: ['table-records', tableKey] }) },
            { type: 'divider' },
            { key: 'copy', icon: <CopyOutlined />, label: '复制当前表', onClick: () => tableApi.copy(wid!, tid!).then(() => message.success('表已复制')).then(() => queryClient.invalidateQueries({ queryKey: ['table', tableKey] })) },
            { type: 'divider' },
            { key: 'delete', icon: <DeleteOutlined />, danger: true, label: '删除表', disabled: true },
          ] }}><Button icon={<MoreOutlined />} /></Dropdown>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => quickAdd.mutate()}>新增行</Button>
        </Space>
      </div>

      {/* 视图 Tab + 视图切换 */}
      <div style={{ padding: '0 16px', background: '#fff', borderBottom: '1px solid #e5e7eb', display: 'flex', alignItems: 'center' }}>
        <Tabs
          activeKey={activeViewId ? String(activeViewId) : 'all'}
          onChange={(k) => loadView(k === 'all' ? null : views.find(v => String(v.id) === k) || null)}
          onEdit={(targetKey, action) => {
            if (action === 'add') {
              Modal.confirm({
                title: '创建新视图',
                content: <CreateViewForm onCreate={(name, vt) => createView.mutate({ name, view_type: vt })} />,
                okText: '创建',
                cancelText: '取消',
              })
            } else if (action === 'remove' && typeof targetKey === 'string') {
              removeView.mutate(targetKey)
            }
          }}
          items={viewTabItems.map(item => ({
            key: item.key,
            label: item.label,
            closable: item.closable,
          }))}
          style={{ flex: 1 }}
        />
        <Button.Group style={{ marginLeft: 8 }}>
          <Button size="small" type={mode === 'grid' ? 'primary' : 'default'} icon={<ColumnHeightOutlined />} onClick={() => setMode('grid')}>{!isMobile && '表格'}</Button>
          <Button size="small" type={mode === 'kanban' ? 'primary' : 'default'} icon={<AppstoreOutlined />} onClick={() => setMode('kanban')}>{!isMobile && '看板'}</Button>
          <Button size="small" type={mode === 'gallery' ? 'primary' : 'default'} icon={<EyeOutlined />} onClick={() => setMode('gallery')}>{!isMobile && '画廊'}</Button>
        </Button.Group>
        <Tooltip title="当前视图筛选规则">
          <Button
            size="small"
            icon={<FilterOutlined />}
            type={viewFilters ? 'primary' : 'default'}
            style={{ marginLeft: 8 }}
            onClick={() => setViewConfigOpen(true)}
          />
        </Tooltip>
      </div>

      {/* 主内容 */}
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
          <KanbanView rows={rowList.items || []} fields={table?.fields || []} onRowClick={(r) => { setDetailRow(r); setDetailOpen(true) }} />
        ) : (
          <GalleryView rows={rowList.items || []} fields={table?.fields || []} onRowClick={(r) => { setDetailRow(r); setDetailOpen(true) }} />
        )}
      </div>

      {/* 底部聚合条 */}
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
              <Button size="small" icon={<CopyOutlined />} loading={copyRow.isPending}
                onClick={() => copyRow.mutate(selectedRowKeys as Array<number | string>)}>复制选中</Button>
              <Button size="small" danger icon={<DeleteOutlined />}
                onClick={() => Modal.confirm({ title: `确定删除 ${selectedRowKeys.length} 行？`, onOk: () => deleteRows.mutate(selectedRowKeys) })}
                loading={deleteRows.isPending}>删除选中</Button>
              <Button size="small" onClick={() => setSelectedRowKeys([])}>取消选择</Button>
            </Space>
          </div>
        </div>
      )}

      {/* 抽屉 & 对话框 */}
      <RowDetailDrawer open={detailOpen} row={detailRow} fields={table?.fields || []} wid={wid} tid={tid}
        onClose={() => { setDetailOpen(false); setDetailRow(null) }} />
      <FieldManager open={fieldMgrOpen} wid={wid} tid={tid} fields={table?.fields || []}
        onClose={() => setFieldMgrOpen(false)}
        onChanged={() => {
          queryClient.invalidateQueries({ queryKey: ['table', tableKey] })
          queryClient.invalidateQueries({ queryKey: ['table-records', tableKey] })
        }}
      />
      <ImportExportDialog open={importExportOpen} wid={wid} tid={tid}
        onClose={() => setImportExportOpen(false)}
        onImported={() => {
          queryClient.invalidateQueries({ queryKey: ['table-records', tableKey] })
          queryClient.invalidateQueries({ queryKey: ['table', tableKey] })
        }}
      />
      <ViewConfigDialog open={viewConfigOpen} filters={viewFilters} onClose={() => setViewConfigOpen(false)}
        onSave={(f) => { setViewFilters(f); setViewConfigOpen(false); setOffset(0) }} />
    </div>
  )
}

// ─────────────── 创建视图表单 ───────────────

function CreateViewForm({ onCreate }: { onCreate: (name: string, viewType: string) => void }) {
  const [name, setName] = useState('')
  const [vt, setVt] = useState('grid')
  return (
    <Form layout="vertical" style={{ marginTop: 12 }}>
      <Form.Item label="视图名称" required>
        <Input placeholder="例如：只看进行中" value={name} onChange={e => setName(e.target.value)} autoFocus />
      </Form.Item>
      <Form.Item label="视图类型">
        <Select value={vt} onChange={setVt} options={[
          { value: 'grid', label: '表格（Grid）' },
          { value: 'kanban', label: '看板（Kanban）' },
          { value: 'gallery', label: '画廊（Gallery）' },
          { value: 'calendar', label: '日历（Calendar）' },
          { value: 'form', label: '表单（Form）' },
        ]} />
      </Form.Item>
      <div style={{ textAlign: 'right', marginTop: 12 }}>
        <Button type="primary" disabled={!name.trim()}
          onClick={() => { onCreate(name.trim(), vt); Modal.destroyAll() }}>创建</Button>
      </div>
    </Form>
  )
}

// ─────────────── 视图配置对话框（筛选 + 排序 JSON） ───────────────

function ViewConfigDialog({
  open, filters, onClose, onSave,
}: {
  open: boolean
  filters: Record<string, unknown> | null
  onClose: () => void
  onSave: (f: Record<string, unknown> | null) => void
}) {
  const [text, setText] = useState(filters ? JSON.stringify(filters, null, 2) : '')

  // 每次打开重置 text
  useMemo(() => { if (open) setText(filters ? JSON.stringify(filters, null, 2) : '') }, [open, filters])

  return (
    <Modal
      title="当前视图 — 筛选 / 排序"
      open={open}
      onCancel={onClose}
      width={560}
      footer={[
        <Button key="cancel" onClick={onClose}>取消</Button>,
        <Button key="clear" onClick={() => onSave(null)}>清空筛选</Button>,
        <Button key="ok" type="primary" onClick={() => {
          if (!text.trim()) { onSave(null); return }
          try {
            const parsed = JSON.parse(text)
            onSave(parsed)
          } catch {
            message.error('JSON 格式错误')
          }
        }}>保存</Button>,
      ]}
      destroyOnClose
    >
      <div style={{ fontSize: 12, color: '#64748b', marginBottom: 8 }}>
        筛选规则使用 JSON 格式，例如 {`{"状态": "进行中", "优先级": {"$gt": 3}}`}。暂时由后端解析。
      </div>
      <Input.TextArea
        value={text}
        onChange={e => setText(e.target.value)}
        rows={8}
        placeholder='{"字段名": "值"}  或  {"字段名": {"$op": "值"}}'
      />
    </Modal>
  )
}

// ─────────────── Grid 列构建 ───────────────

function buildColumns(
  fields: Field[],
  onCellSave?: (rowId: number | string, fieldName: string, value: unknown) => Promise<unknown>,
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

// ─────────────── Kanban 视图 ───────────────

function KanbanView({ rows, fields, onRowClick }: { rows: RowResponse[]; fields: Field[]; onRowClick?: (r: RowResponse) => void }) {
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
            <div
              key={r.id}
              onClick={() => onRowClick?.(r)}
              style={{ padding: 12, marginBottom: 8, border: '1px solid #e5e7eb', borderRadius: 6, cursor: 'pointer' }}
            >
              {String(r[fields.find(f => f.is_primary)?.name || 'id'] ?? r.id)}
            </div>
          ))}
        </div>
      ))}
    </div>
  )
}

// ─────────────── Gallery 视图 ───────────────

function GalleryView({ rows, fields, onRowClick }: { rows: RowResponse[]; fields: Field[]; onRowClick?: (r: RowResponse) => void }) {
  const titleField = fields.find(f => f.field_type === 'text') || fields.find(f => f.is_primary)
  const titleCol = titleField?.name || 'id'
  return (
    <Row gutter={[16, 16]}>
      {rows.map(r => (
        <Col xs={24} sm={12} md={8} lg={6} key={r.id}>
          <div
            onClick={() => onRowClick?.(r)}
            style={{ padding: 16, border: '1px solid #e5e7eb', borderRadius: 8, background: '#fff', cursor: 'pointer' }}
          >
            <div style={{ fontWeight: 600, marginBottom: 8 }}>{String(r[titleCol] ?? r.id)}</div>
            <div style={{ fontSize: 12, color: '#6b7280' }}>ID: {r.id}</div>
          </div>
        </Col>
      ))}
      {rows.length === 0 && <Empty description="暂无记录" style={{ padding: 48 }} />}
    </Row>
  )
}

// ─────────────── 一些保留但暂隐藏的图标引用（让打包器知道没丢依赖） ───────────────

void DownOutlined; void CloseOutlined; void Switch
