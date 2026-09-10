import { Card, Row, Col, Typography, Empty, Spin, Tag } from 'antd'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import * as Icons from '@ant-design/icons'
import { systemApi, type AppItem } from '@/api'

const { Title, Text, Paragraph } = Typography

/** 将 icon 字符串（如 "ApiOutlined"）映射到 @ant-design/icons 组件 */
function resolveIcon(name: string): React.ReactNode {
  if (!name) return <Icons.AppstoreOutlined />
  const Comp = (Icons as unknown as Record<string, React.ComponentType>)[name]
  return Comp ? <Comp /> : <Icons.AppstoreOutlined />
}

/** 应用分类标签配置（与后端 AppItem.category 约定值对齐） */
const CATEGORY_LABELS: Record<string, { label: string; color: string }> = {
  tool: { label: '实用工具', color: 'green' },
  analysis: { label: '分析工具', color: 'blue' },
  integration: { label: '集成对接', color: 'purple' },
}

export default function AppCenter() {
  const navigate = useNavigate()

  const { data: apps = [], isLoading } = useQuery({
    queryKey: ['apps'],
    queryFn: () => systemApi.apps().then((r) => r.data),
  })

  // 按分类分组
  const groupedApps = apps.reduce(
    (acc, app) => {
      if (!acc[app.category]) acc[app.category] = []
      acc[app.category].push(app)
      return acc
    },
    {} as Record<string, AppItem[]>,
  )

  if (isLoading) {
    return (
      <div style={{ textAlign: 'center', padding: 80 }}>
        <Spin size="large" />
      </div>
    )
  }

  return (
    <div>
      <div style={{ marginBottom: 24 }}>
        <Title level={3} style={{ marginBottom: 4 }}>
          应用中心
        </Title>
        <Text type="secondary">
          工具型与分析型功能模块，以可扩展的 APP 形式提供
        </Text>
      </div>

      {apps.length === 0 ? (
        <Empty description="暂无可用应用" />
      ) : (
        Object.entries(groupedApps).map(([category, items]) => {
          const catInfo = CATEGORY_LABELS[category] || {
            label: category,
            color: 'default',
          }
          return (
            <div key={category} style={{ marginBottom: 32 }}>
              <div style={{ marginBottom: 12 }}>
                <Tag color={catInfo.color}>{catInfo.label}</Tag>
                <Text type="secondary" style={{ marginLeft: 8 }}>
                  {items.length} 个应用
                </Text>
              </div>
              <Row gutter={[16, 16]}>
                {items.map((app) => (
                  <Col xs={24} sm={12} md={8} lg={6} key={app.key}>
                    <Card
                      hoverable
                      onClick={() => navigate(app.path)}
                      style={{ height: '100%' }}
                    >
                      <div
                        style={{
                          display: 'flex',
                          flexDirection: 'column',
                          height: '100%',
                        }}
                      >
                        <div
                          style={{
                            fontSize: 32,
                            color: '#1677ff',
                            marginBottom: 12,
                          }}
                        >
                          {resolveIcon(app.icon)}
                        </div>
                        <Title level={5} style={{ marginBottom: 4 }}>
                          {app.label}
                        </Title>
                        <Paragraph
                          type="secondary"
                          style={{
                            fontSize: 12,
                            marginBottom: 0,
                            flex: 1,
                          }}
                          ellipsis={{ rows: 3 }}
                        >
                          {app.description}
                        </Paragraph>
                      </div>
                    </Card>
                  </Col>
                ))}
              </Row>
            </div>
          )
        })
      )}
    </div>
  )
}
