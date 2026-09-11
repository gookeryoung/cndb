import { Card, Table, Button, Tabs, Empty, message } from 'antd'
import { DeleteOutlined, UndoOutlined } from '@ant-design/icons'
import { useParams } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { trashApi } from '@/api'
import type { WorkspaceTrashResponse } from '@/api'

interface Props { embedded?: boolean }

export default function TrashPanel({ embedded }: Props) {
  const { wid, tid } = useParams<{ wid: string; tid?: string }>()
  const queryClient = useQueryClient()

  const { data, isLoading } = useQuery<WorkspaceTrashResponse>({
    queryKey: ['trash', wid],
    queryFn: () => trashApi.list(wid!),
    enabled: !!wid,
  })

  const restoreTable = useMutation({
    mutationFn: (tid2: string | number) => trashApi.restoreTable(wid!, tid2),
    onSuccess: () => { message.success('已恢复表'); queryClient.invalidateQueries({ queryKey: ['trash', wid] }); queryClient.invalidateQueries({ queryKey: ['tables', wid] }) },
  })
  const restoreField = useMutation({
    mutationFn: (fid: string | number) => trashApi.restoreField(wid!, fid),
    onSuccess: () => { message.success('已恢复字段'); queryClient.invalidateQueries({ queryKey: ['trash', wid] }) },
  })
  const restoreRow = useMutation({
    mutationFn: (rowId: string | number) => trashApi.restoreRow(wid!, tid || '', rowId),
    onSuccess: () => { message.success('已恢复行'); queryClient.invalidateQueries({ queryKey: ['trash', wid] }) },
  })

  if (!wid) return <Empty description="无效工作区" />
  if (isLoading) return <div style={{ padding: 48, textAlign: 'center' }}>加载中...</div>

  const tabs = [
    { key: 'tables', label: `表 (${data?.tables.length ?? 0})`, children: (
      <Table rowKey="id" size="small" pagination={false}
        dataSource={data?.tables || []}
        columns={[
          { title: '名称', dataIndex: 'name' },
          { title: '记录数', dataIndex: 'record_count' },
          { title: '操作', key: 'op', width: 120, render: (_, r) => <Button size="small" icon={<UndoOutlined />} onClick={() => restoreTable.mutate(r.id)} loading={restoreTable.isPending}>恢复</Button> },
        ]} />
    )},
    { key: 'fields', label: `字段 (${data?.fields.length ?? 0})`, children: (
      <Table rowKey="id" size="small" pagination={false}
        dataSource={data?.fields || []}
        columns={[
          { title: '名称', dataIndex: 'name' },
          { title: '类型', dataIndex: 'field_type', render: v => String(v) },
          { title: '操作', key: 'op', width: 120, render: (_, r) => <Button size="small" icon={<UndoOutlined />} onClick={() => restoreField.mutate(r.id)} loading={restoreField.isPending}>恢复</Button> },
        ]} />
    )},
    { key: 'rows', label: `行 (${data?.trashed_rows.length ?? 0})`, children: (
      <Table rowKey="id" size="small" pagination={false}
        dataSource={data?.trashed_rows || []}
        columns={[
          { title: '原始 ID', dataIndex: 'original_id' },
          { title: '删除时间', dataIndex: 'deleted_at' },
          { title: '操作', key: 'op', width: 120, render: (_, r) => <Button size="small" icon={<UndoOutlined />} onClick={() => restoreRow.mutate(r.id)} loading={restoreRow.isPending}>恢复</Button> },
        ]} />
    )},
  ]

  return (
    <div style={{ padding: embedded ? 16 : 24 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 16 }}>
        <DeleteOutlined style={{ fontSize: 20, color: '#f59e0b' }} />
        <h2 style={{ margin: 0 }}>回收站</h2>
      </div>
      <Card bodyStyle={{ padding: 16 }}>
        <Tabs items={tabs} />
      </Card>
    </div>
  )
}
