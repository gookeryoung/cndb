import { Card, Col, Row, Statistic, Table, Tag, Typography, Spin } from 'antd'
import {
  CheckCircleOutlined,
  InfoCircleOutlined,
  ApiOutlined,
  HeartOutlined,
} from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { systemApi, type PluginInfo, type NavItem } from '@/api'

const { Title, Text, Paragraph } = Typography

export default function Dashboard() {
  // 框架健康状态
  const { data: health, isLoading: healthLoading } = useQuery({
    queryKey: ['health'],
    queryFn: () => systemApi.health().then((r) => r.data),
    refetchInterval: 60_000,
  })

  // 已加载插件列表
  const { data: plugins = [], isLoading: pluginsLoading } = useQuery({
    queryKey: ['plugins'],
    queryFn: () => systemApi.plugins().then((r) => r.data.plugins),
  })

  // 侧边栏导航汇总
  const { data: navItems = [], isLoading: navLoading } = useQuery({
    queryKey: ['navigation'],
    queryFn: () => systemApi.navigation().then((r) => r.data.navigation),
  })

  const loading = healthLoading || pluginsLoading || navLoading

  // 插件表格列
  const pluginColumns = [
    {
      title: '名称',
      dataIndex: 'name',
      key: 'name',
      render: (name: string) => <Text strong>{name}</Text>,
    },
    {
      title: '版本',
      dataIndex: 'version',
      key: 'version',
      render: (v: string) => <Tag color="blue">v{v}</Tag>,
    },
    {
      title: '描述',
      dataIndex: 'description',
      key: 'description',
      ellipsis: true,
    },
  ]

  // 导航表格列
  const navColumns = [
    { title: 'Key', dataIndex: 'key', key: 'key' },
    { title: '标签', dataIndex: 'label', key: 'label' },
    {
      title: '路径',
      dataIndex: 'path',
      key: 'path',
      render: (p: string) => <Text code>{p}</Text>,
    },
    {
      title: '图标',
      dataIndex: 'icon',
      key: 'icon',
      render: (i: string) => <Tag>{i || '-'}</Tag>,
    },
  ]

  return (
    <div style={{ padding: 8 }}>
      <Title level={3} style={{ marginTop: 0 }}>
        仪表盘
      </Title>
      <Paragraph type="secondary">
        欢迎使用 pywt 模板。下方汇总框架运行状态、已加载插件及导航项。
      </Paragraph>

      {loading ? (
        <Spin style={{ display: 'block', margin: '60px auto' }} />
      ) : (
        <>
          {/* 统计卡片 */}
          <Row gutter={[16, 16]}>
            <Col xs={24} sm={12} md={6}>
              <Card>
                <Statistic
                  title="服务状态"
                  value={health?.status === 'ok' ? '正常' : '异常'}
                  prefix={
                    health?.status === 'ok' ? (
                      <CheckCircleOutlined style={{ color: '#52c41a' }} />
                    ) : (
                      <InfoCircleOutlined style={{ color: '#ff4d4f' }} />
                    )
                  }
                  valueStyle={{
                    color: health?.status === 'ok' ? '#3f8600' : '#cf1322',
                  }}
                />
              </Card>
            </Col>
            <Col xs={24} sm={12} md={6}>
              <Card>
                <Statistic
                  title="应用版本"
                  value={health?.version || '--'}
                  prefix={<ApiOutlined />}
                />
              </Card>
            </Col>
            <Col xs={24} sm={12} md={6}>
              <Card>
                <Statistic
                  title="已加载插件"
                  value={plugins.length}
                  prefix={<HeartOutlined />}
                />
              </Card>
            </Col>
            <Col xs={24} sm={12} md={6}>
              <Card>
                <Statistic
                  title="导航项"
                  value={navItems.length}
                  prefix={<InfoCircleOutlined />}
                />
              </Card>
            </Col>
          </Row>

          {/* 插件列表 */}
          <Card
            title="已加载插件"
            style={{ marginTop: 16 }}
            size="small"
          >
            <Table<PluginInfo>
              rowKey="name"
              columns={pluginColumns}
              dataSource={plugins}
              pagination={false}
              size="small"
            />
          </Card>

          {/* 导航项 */}
          <Card
            title="插件注册的导航项"
            style={{ marginTop: 16 }}
            size="small"
          >
            <Table<NavItem>
              rowKey="key"
              columns={navColumns}
              dataSource={navItems}
              pagination={false}
              size="small"
            />
          </Card>
        </>
      )}
    </div>
  )
}
