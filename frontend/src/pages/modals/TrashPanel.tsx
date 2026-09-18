/** 回收站面板 — 工作区级概览 + 表/字段恢复 + 表级软删行列表与恢复. */

import { useState } from 'react'
import { Card, Table, Button, Tabs, Empty, message, Select, Space, Tag, Popconfirm, InputNumber } from 'antd'
import { DeleteOutlined, UndoOutlined, ClearOutlined } from '@ant-design/icons'
import { useParams } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { trashApi } from '@/api'

interface Props { embedded?: boolean }

export default function TrashPanel({ embedded }: Props) {
  const { wid } = useParams<{ wid: string }>()
  const queryClient = useQueryClient()
  const [selectedTid, setSelectedTid] = useState<number | string | null>(null)

  const { data: overview, isLoading } = useQuery({
    queryKey: ['trash', wid],
    queryFn: () => trashApi.overview(wid!),
    enabled: !!wid,
  })

  // 选中某表后加载该表的软删行
  const { data: rowData, isLoading: rowsLoading } = useQuery<{ rows: unknown[]; total: number }>({
    queryKey: ['trash-rows', wid, selectedTid],
    queryFn: () => trashApi.rows(wid!, selectedTid!),
    enabled: !!wid && !!selectedTid,
  })

  const restoreTable = useMutation({
    mutationFn: (tid: string | number) => trashApi.restoreTable(wid!, tid),
    onSuccess: () => { message.success('已恢复表'); queryClient.invalidateQueries({ queryKey: ['trash', wid] }) },
    onError: (err) => message.error(err instanceof Error ? err.message : '恢复表失败'),
  })
  const restoreField = useMutation({
    mutationFn: (fid: string | number) => trashApi.restoreField(wid!, fid),
    onSuccess: () => { message.success('已恢复字段'); queryClient.invalidateQueries({ queryKey: ['trash', wid] }) },
    onError: (err) => message.error(err instanceof Error ? err.message : '恢复字段失败'),
  })
  const restoreRows = useMutation({
    mutationFn: (rowIds: Array<string | number>) => trashApi.restoreRows(wid!, selectedTid!, rowIds),
    onSuccess: () => { message.success('已恢复行'); queryClient.invalidateQueries({ queryKey: ['trash-rows', wid, selectedTid] }); queryClient.invalidateQueries({ queryKey: ['trash', wid] }) },
    onError: (err) => message.error(err instanceof Error ? err.message : '恢复行失败'),
  })
  const [purgeDays, setPurgeDays] = useState<number>(30)
  const purgeRows = useMutation({
    mutationFn: () => trashApi.purgeRows(wid!, selectedTid!, purgeDays),
    onSuccess: (data) => {
      message.success(`已硬清理 ${data?.purged ?? 0} 条超过 ${data?.older_than_days ?? purgeDays} 天的软删行`)
      queryClient.invalidateQueries({ queryKey: ['trash-rows', wid, selectedTid] })
      queryClient.invalidateQueries({ queryKey: ['trash', wid] })
    },
    onError: (err) => {
      message.error(err instanceof Error ? err.message : '清理失败')
    },
  })

  if (!wid) return <Empty description="无效工作区" />
  if (isLoading) return <div style={{ padding: 48, textAlign: 'center' }}>加载中...</div>

  const rowCountOptions = (overview?.row_counts || []).map((r: { table_id: number | string; table_name: string; trashed_rows: number }) => ({
    value: r.table_id,
    label: `${r.table_name} (${r.trashed_rows})`,
    trashed_rows: r.trashed_rows,
  }))

  const tabs = [
    {
      key: 'tables',
      label: `表 (${overview?.tables.length ?? 0})`,
      children: (
        <Table
          rowKey="id"
          size="small"
          pagination={false}
          dataSource={overview?.tables || []}
          columns={[
            { title: '名称', dataIndex: 'name' },
            {
              title: '删除时间',
              dataIndex: 'trashed_at',
              render: (v: string | null) => v ? new Date(v).toLocaleString() : '—',
            },
            {
              title: '操作', key: 'op', width: 120,
              render: (_, r) => (
                <Button size="small" icon={<UndoOutlined />} loading={restoreTable.isPending}
                  onClick={() => restoreTable.mutate(r.id)}>恢复</Button>
              ),
            },
          ]}
        />
      ),
    },
    {
      key: 'fields',
      label: `字段 (${overview?.fields.length ?? 0})`,
      children: (
        <Table
          rowKey="id"
          size="small"
          pagination={false}
          dataSource={overview?.fields || []}
          columns={[
            { title: '名称', dataIndex: 'name' },
            {
              title: '所属表', dataIndex: 'table_name',
              render: (v, r) => v || <Tag>{r.table_id}</Tag>,
            },
            {
              title: '类型', dataIndex: 'field_type',
              render: v => <Tag>{String(v)}</Tag>,
            },
            {
              title: '删除时间', dataIndex: 'trashed_at',
              render: (v: string | null) => v ? new Date(v).toLocaleString() : '—',
            },
            {
              title: '操作', key: 'op', width: 120,
              render: (_, r) => (
                <Button size="small" icon={<UndoOutlined />} loading={restoreField.isPending}
                  onClick={() => restoreField.mutate(r.id)}>恢复</Button>
              ),
            },
          ]}
        />
      ),
    },
    {
      key: 'rows',
      label: `行 (${rowCountOptions.reduce((s, o) => s + (o.trashed_rows ?? 0), 0)})`,
      children: (
        <div>
          {rowCountOptions.length === 0 ? (
            <Empty description="当前没有被软删的行" />
          ) : (
            <>
              <Space style={{ marginBottom: 12 }}>
                <span style={{ color: '#6b7280' }}>选择表：</span>
                <Select
                  style={{ width: 240 }}
                  placeholder="选择要查看的表"
                  options={rowCountOptions}
                  onChange={(v) => setSelectedTid(v)}
                />
                {selectedTid && rowData && (
                  <Button danger size="small" onClick={() => restoreRows.mutate([])}>恢复全部 {rowData.total} 行</Button>
                )}
                {selectedTid && (
                  <Space>
                    <span style={{ color: '#6b7280' }}>清理超过</span>
                    <InputNumber size="small" min={1} max={365} value={purgeDays}
                      onChange={v => setPurgeDays(Number(v))} style={{ width: 70 }} />
                    <span style={{ color: '#6b7280' }}>天</span>
                    <Popconfirm
                      title={`硬清理 ${purgeDays} 天前的软删行？`}
                      description="此操作不可恢复"
                      okText="确认清理"
                      cancelText="取消"
                      okButtonProps={{ danger: true }}
                      onConfirm={() => purgeRows.mutate()}
                    >
                      <Button danger size="small" icon={<ClearOutlined />} loading={purgeRows.isPending}>硬清理</Button>
                    </Popconfirm>
                  </Space>
                )}
              </Space>
              {selectedTid && (
                <Table
                  rowKey="id"
                  size="small"
                  loading={rowsLoading}
                  pagination={{ pageSize: 50, showSizeChanger: true, pageSizeOptions: [50, 100, 200] }}
                  dataSource={(rowData?.rows || []) as any[]}
                  columns={[
                    { title: '行 ID', dataIndex: 'id', width: 80 },
                    {
                      title: '软删时间',
                      dataIndex: '_trashed_at',
                      render: (v: string | null) => v ? new Date(v).toLocaleString() : '—',
                    },
                    {
                      title: '操作', key: 'op', width: 120,
                      render: (_, r) => (
                        <Button size="small" icon={<UndoOutlined />} loading={restoreRows.isPending}
                          onClick={() => restoreRows.mutate([r.id])}>恢复</Button>
                      ),
                    },
                  ]}
                />
              )}
            </>
          )}
        </div>
      ),
    },
  ]

  return (
    <div style={{ padding: embedded ? 16 : 24 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 16 }}>
        <DeleteOutlined style={{ fontSize: 20, color: '#f59e0b' }} />
        <h2 style={{ margin: 0 }}>回收站</h2>
      </div>
      <Card styles={{ body: { padding: 16 } }}>
        <Tabs items={tabs} />
      </Card>
    </div>
  )
}

