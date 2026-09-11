import { useParams } from 'react-router-dom'
import { Card, Table, Typography, Spin, Empty } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { publicApi } from '@/api'
import type { SharedGrid } from '@/api'

const { Title, Text } = Typography

export default function PublicSharePage() {
  const { slug } = useParams<{ slug: string }>()
  const { data, isLoading } = useQuery<SharedGrid>({
    queryKey: ['public-share', slug],
    queryFn: () => publicApi.getShare(slug!),
    enabled: !!slug,
  })

  if (isLoading) return <div style={{ padding: 48, textAlign: 'center' }}><Spin /></div>
  if (!data) return <Empty description="分享链接无效或已过期" />

  return (
    <Card>
      <Title level={3}>{data.title}</Title>
      <Text type="secondary">只读视图 · 共 {data.total} 条记录</Text>
      <Table
        rowKey="id" size="small" style={{ marginTop: 16 }}
        columns={data.table.fields.filter(f => !f.hidden).map(f => ({
          key: String(f.id),
          title: f.name,
          dataIndex: f.name,
          render: (v) => v === null || v === undefined || v === '' ? '—' : String(v),
        }))}
        dataSource={data.rows}
        pagination={{ pageSize: 20, showTotal: t => `共 ${t} 条` }}
      />
    </Card>
  )
}
