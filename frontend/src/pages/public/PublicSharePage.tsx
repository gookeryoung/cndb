/** 公开分享只读页面 — 匿名访问分享视图. */

import { useParams, Link } from 'react-router-dom'
import { Card, Table, Typography, Spin, Empty, Tag, Space } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { publicApi } from '@/api'
import GridCell from '@/pages/grid/components/GridCell'

const { Title, Text } = Typography

export default function PublicSharePage() {
  const { slug } = useParams<{ slug: string }>()
  const { data, isLoading, error } = useQuery({
    queryKey: ['public-share', slug],
    queryFn: () => publicApi.getShare(slug!),
    enabled: !!slug,
  })

  if (isLoading) return <div style={{ padding: 48, textAlign: 'center' }}><Spin size="large" /></div>
  if (error || !data) return (
    <div style={{ padding: 64, textAlign: 'center' }}>
      <Empty description="分享链接无效或已过期" />
      <div style={{ marginTop: 16 }}>
        <Link to="/">返回首页</Link>
      </div>
    </div>
  )

  const fields = data.table.fields
  const viewName = data.view.name
  const tableName = data.table.name

  return (
    <div style={{ maxWidth: 1200, margin: '0 auto', padding: 24 }}>
      <Card>
        <Space direction="vertical" size={4} style={{ width: '100%' }}>
          <Space>
            <Title level={3} style={{ margin: 0 }}>{viewName}</Title>
            <Tag color="blue">{tableName}</Tag>
            <Tag>只读分享</Tag>
          </Space>
          {data.table.description && <Text type="secondary">{data.table.description}</Text>}
          <Text type="secondary">共 {data.total} 条记录 · {fields.length} 个字段</Text>
        </Space>

        <Table
          rowKey="id"
          size="middle"
          style={{ marginTop: 16 }}
          columns={fields.filter(f => !f.hidden).map(f => ({
            key: String(f.id),
            title: f.name + (f.required ? ' *' : ''),
            dataIndex: f.name,
            width: 160,
            render: (v: unknown, record: Record<string, unknown>) => (
              <GridCell
                value={v}
                field={f}
                rowId={record.id as number | string}
              />
            ),
          }))}
          dataSource={data.rows}
          pagination={{ pageSize: 20, showTotal: t => `共 ${t} 条`, showSizeChanger: true }}
          scroll={{ x: Math.max(600, fields.length * 160) }}
        />

        <div style={{ marginTop: 24, textAlign: 'center' }}>
          <Text type="secondary" style={{ fontSize: 12 }}>
            由 cndb 提供 · <Link to="/login">登录后访问完整功能</Link>
          </Text>
        </div>
      </Card>
    </div>
  )
}
