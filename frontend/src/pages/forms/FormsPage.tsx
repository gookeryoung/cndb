/** 表单列表页 — 展示工作区内所有表单定义. */

import React from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { Card, Table, Tag, Space, Typography, Spin, Empty } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { formApi, tableApi } from '@/api'
import type { FormDefinitionSummary, TableSummary } from '@/api'

const { Title, Text } = Typography

export default function FormsPage() {
  const { wid } = useParams<{ wid: string }>()
  const navigate = useNavigate()
  const workspaceId = Number(wid)

  const { data: forms = [], isLoading } = useQuery<FormDefinitionSummary[]>({
    queryKey: ['forms', workspaceId],
    queryFn: () => formApi.list(workspaceId),
    enabled: !Number.isNaN(workspaceId),
  })

  const { data: tables = [] } = useQuery<TableSummary[]>({
    queryKey: ['workspaces', workspaceId, 'tables'],
    queryFn: () => tableApi.list(workspaceId),
    enabled: !Number.isNaN(workspaceId),
  })

  const tableNameMap: Record<number, string> = React.useMemo(() => {
    const m: Record<number, string> = {}
    for (const t of tables) m[Number(t.id)] = t.name
    return m
  }, [tables])

  const columns = React.useMemo(() => [
    {
      title: '表单名称',
      dataIndex: 'name',
      key: 'name',
      render: (name: string) => <a>{name}</a>,
    },
    {
      title: '所属表',
      dataIndex: 'table_id',
      key: 'table_id',
      render: (tid: number) => tableNameMap[tid] || `#${tid}`,
    },
    {
      title: '描述',
      dataIndex: 'description',
      key: 'description',
      ellipsis: true,
    },
    {
      title: '权限阈值',
      key: 'roles',
      render: (_: unknown, row: FormDefinitionSummary) => {
        const items: Array<{ label: string; value: string; color: string }> = []
        if (row.use_role) items.push({ label: '使用', value: row.use_role, color: 'blue' })
        if (row.edit_role) items.push({ label: '编辑', value: row.edit_role, color: 'orange' })
        if (row.delete_role) items.push({ label: '删除', value: row.delete_role, color: 'red' })
        if (items.length === 0) return <Text type="secondary">无限制</Text>
        return <Space size={[4, 4]} wrap>{items.map(i => <Tag key={i.label} color={i.color}>{i.label}: {i.value}</Tag>)}</Space>
      },
    },
  ], [tableNameMap])

  return (
    <div style={{ padding: 24 }}>
      <Title level={3} style={{ marginBottom: 16 }}>表单</Title>
      <Card styles={{ body: { padding: 0 } }}>
        {isLoading ? (
          <div style={{ padding: 48, textAlign: 'center' }}><Spin /></div>
        ) : forms.length === 0 ? (
          <Empty description="暂无表单" style={{ padding: 48 }} />
        ) : (
          <Table
            rowKey="id"
            dataSource={forms}
            columns={columns}
            pagination={false}
            onRow={(record) => ({
              onClick: () => navigate(`/w/${workspaceId}/forms/${record.id}`),
              style: { cursor: 'pointer' },
            })}
          />
        )}
      </Card>
    </div>
  )
}
