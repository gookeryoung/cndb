import { useEffect, useState } from 'react'
import { Alert, Button, Card, Descriptions, Space, Tag, Typography, Spin } from 'antd'
import {
  ReloadOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
} from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import dayjs from 'dayjs'
import { healthApi, type HealthPingResponse } from '@/api'

const { Title, Text } = Typography

export default function HealthPage() {
  // 实时 ping，每 10 秒自动刷新
  const { data, isLoading, isFetching, isError, refetch } = useQuery<HealthPingResponse>({
    queryKey: ['health-ping'],
    queryFn: () => healthApi.ping().then((r) => r.data),
    refetchInterval: 10_000,
    retry: 1,
  })

  const [lastUpdate, setLastUpdate] = useState<string>('')

  useEffect(() => {
    if (data?.timestamp) {
      setLastUpdate(dayjs(data.timestamp).format('YYYY-MM-DD HH:mm:ss'))
    }
  }, [data])

  return (
    <div style={{ padding: 8 }}>
      <Title level={3} style={{ marginTop: 0 }}>
        健康检查
      </Title>

      {/* 顶部状态条 */}
      {isError ? (
        <Alert
          type="error"
          showIcon
          icon={<CloseCircleOutlined />}
          message="后端连接失败"
          description="无法访问 /api/v1/health/ping，请确认 FastAPI 服务正在运行。"
          action={
            <Button size="small" type="primary" danger onClick={() => refetch()}>
              重试
            </Button>
          }
          style={{ marginBottom: 16 }}
        />
      ) : data ? (
        <Alert
          type="success"
          showIcon
          icon={<CheckCircleOutlined />}
          message={`服务响应: ${data.status}`}
          description={
            <span>
              最后更新: <Text code>{lastUpdate}</Text>
              {isFetching && <Spin size="small" style={{ marginLeft: 8 }} />}
            </span>
          }
          style={{ marginBottom: 16 }}
        />
      ) : null}

      <Card
        title="运行环境信息"
        extra={
          <Button
            size="small"
            icon={<ReloadOutlined />}
            loading={isFetching}
            onClick={() => refetch()}
          >
            手动刷新
          </Button>
        }
      >
        {isLoading && !data ? (
          <Spin style={{ display: 'block', margin: '40px auto' }} />
        ) : data ? (
          <Descriptions bordered column={1} size="small">
            <Descriptions.Item label="状态">
              <Tag color={data.status === 'pong' ? 'green' : 'red'}>
                {data.status}
              </Tag>
            </Descriptions.Item>
            <Descriptions.Item label="服务器时间">
              <Text code>{data.timestamp}</Text>
            </Descriptions.Item>
            <Descriptions.Item label="Python 版本">
              <Text code>{data.python}</Text>
            </Descriptions.Item>
            <Descriptions.Item label="操作系统">
              <Text code>{data.platform}</Text>
            </Descriptions.Item>
          </Descriptions>
        ) : null}
      </Card>

      <Space style={{ marginTop: 16 }} wrap>
        <Text type="secondary">提示：本页面每 10 秒自动刷新。</Text>
      </Space>
    </div>
  )
}
