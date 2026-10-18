/** 智能推荐卡片 —— 字段角色 chips + 推荐图表 / 汇总 / 公式 / 典型示例.
 *
 * 定位：只负责展示与交互回调（props 注入），请求与状态由 AnalyticsPage 编排，
 * 因此可脱离路由独立单测；接口失败时页面静默降级（不弹全局错误），这里仅展示空态。
 */

import { Button, Card, Dropdown, Empty, Skeleton, Tag, Tooltip, Typography } from 'antd'
import {
  BarChartOutlined, ExperimentOutlined, FunctionOutlined, TableOutlined, ThunderboltOutlined,
} from '@ant-design/icons'
import type {
  AnalyticsChart,
  AnalyticsFormula,
  AnalyticsRecommendationExample,
  AnalyticsRecommendationField,
  AnalyticsRecommendations,
  AnalyticsRecommendationRole,
  AnalyticsSummary,
} from '@/api/analytics'
import {
  RECOMMENDATION_CHIP_ROLES,
  formatRecommendationRole,
  recommendationRoleColor,
} from './analyticsModel'

const { Text } = Typography

interface Props {
  /** 推荐结果（未加载 / 失败时为 null） */
  recommendations: AnalyticsRecommendations | null
  loading?: boolean
  /** 请求失败：静默降级为「暂无推荐」，不阻塞页面 */
  error?: boolean
  /** 已选数据源表名（展示用） */
  tableName?: string
  /** 点击推荐维度 → 图表 X */
  onSelectDimension: (name: string) => void
  /** 点击推荐指标 → 图表 Y，并补充分组汇总维度 */
  onSelectMetric: (name: string) => void
  /** 点击时间字段 → 折线图 X */
  onSelectTime: (name: string) => void
  onApplyChart: (chart: AnalyticsChart) => void
  onApplySummary: (summary: AnalyticsSummary) => void
  onApplyFormulas: (formulas: AnalyticsFormula[]) => void
  onApplyExample: (example: AnalyticsRecommendationExample) => void
}

/** 字段 chip 提示：理由 + 基数 / 非空率 */
function fieldTooltip(field: AnalyticsRecommendationField) {
  return (
    <div style={{ lineHeight: 1.8 }}>
      <div>{field.reason || `${formatRecommendationRole(field.role)}字段`}</div>
      <div style={{ fontSize: 12, opacity: 0.85 }}>
        类型：{field.field_type || '未知'}
        {typeof field.cardinality === 'number' ? ` · 基数：${field.cardinality}` : ''}
        {typeof field.completeness === 'number' ? ` · 非空率：${Math.round(field.completeness * 100)}%` : ''}
      </div>
    </div>
  )
}

export function RecommendationPanel({
  recommendations,
  loading = false,
  error = false,
  tableName,
  onSelectDimension,
  onSelectMetric,
  onSelectTime,
  onApplyChart,
  onApplySummary,
  onApplyFormulas,
  onApplyExample,
}: Props) {
  const fields = recommendations?.fields ?? []
  const groups = RECOMMENDATION_CHIP_ROLES
    .map(role => ({ role, items: fields.filter(f => f.role === role) }))
    .filter(group => group.items.length > 0)
  const formulaCount = recommendations?.formulas.length ?? 0
  const examples = recommendations?.examples ?? []
  const hasContent = groups.length > 0 || formulaCount > 0 ||
    !!recommendations?.chart || !!recommendations?.summary || examples.length > 0

  const chipClick = (role: AnalyticsRecommendationRole, name: string) => {
    if (role === 'metric') onSelectMetric(name)
    else if (role === 'time') onSelectTime(name)
    else onSelectDimension(name)
  }

  return (
    <div data-testid="analytics-recommend">
      <Card
        size="small"
        title={
          <span>
            <ThunderboltOutlined /> 智能推荐
            {tableName ? <Text type="secondary" style={{ fontSize: 12, marginLeft: 8 }}>{tableName}</Text> : null}
          </span>
        }
        extra={
          recommendations ? (
            <Text type="secondary" style={{ fontSize: 12 }} data-testid="analytics-recommend-meta">
              采样 {recommendations.sampled_rows}/{recommendations.row_count} 行
              {recommendations.truncated ? '（数据量大，已截断采样）' : ''}
            </Text>
          ) : null
        }
      >
        {loading ? (
          <div data-testid="analytics-recommend-loading">
            <Skeleton active title={false} paragraph={{ rows: 3 }} />
          </div>
        ) : !recommendations || !hasContent ? (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description={error ? '暂无推荐（智能推荐服务暂不可用，不影响手动配置）' : '暂无推荐'}
          />
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {/* 字段角色 chips：维度 / 时间 / 指标 */}
            {groups.map(group => (
              <div
                key={group.role}
                data-testid={`analytics-recommend-group-${group.role}`}
                style={{ display: 'flex', flexWrap: 'wrap', gap: 4, alignItems: 'center' }}
              >
                <Text type="secondary" style={{ fontSize: 12 }}>
                  {formatRecommendationRole(group.role)}：
                </Text>
                {group.items.map(field => (
                  <Tooltip key={field.name} title={fieldTooltip(field)}>
                    <Tag
                      data-testid={`analytics-recommend-${group.role}-${field.name}`}
                      color={recommendationRoleColor(group.role)}
                      style={{ cursor: 'pointer', marginInlineEnd: 0 }}
                      onClick={() => chipClick(group.role, field.name)}
                    >
                      {field.name}
                    </Tag>
                  </Tooltip>
                ))}
                <Text type="secondary" style={{ fontSize: 12 }}>
                  {group.role === 'metric' ? '点击设为指标' : group.role === 'time' ? '点击设为折线时间轴' : '点击设为维度'}
                </Text>
              </div>
            ))}

            {/* 推荐公式 */}
            {formulaCount > 0 && (
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, alignItems: 'center' }}>
                <Text type="secondary" style={{ fontSize: 12 }}>公式：</Text>
                {recommendations!.formulas.map(formula => (
                  <Tooltip key={formula.key} title={formula.reason || formula.expr}>
                    <Tag
                      color="geekblue"
                      style={{ marginInlineEnd: 0 }}
                      data-testid={`analytics-recommend-formula-${formula.key}`}
                    >
                      {formula.label || formula.key}
                    </Tag>
                  </Tooltip>
                ))}
              </div>
            )}

            {/* 一键应用操作 */}
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
              <Tooltip title={recommendations?.chart?.reason}>
                <Button
                  size="small"
                  icon={<BarChartOutlined />}
                  data-testid="analytics-recommend-chart"
                  disabled={!recommendations?.chart}
                  onClick={() => recommendations?.chart && onApplyChart(recommendations.chart.chart)}
                >
                  应用推荐图表
                </Button>
              </Tooltip>
              <Tooltip title={recommendations?.summary?.reason}>
                <Button
                  size="small"
                  icon={<TableOutlined />}
                  data-testid="analytics-recommend-summary"
                  disabled={!recommendations?.summary}
                  onClick={() => recommendations?.summary && onApplySummary(recommendations.summary.summary)}
                >
                  应用推荐汇总
                </Button>
              </Tooltip>
              <Tooltip title="把推荐公式追加到当前公式列表（自动跳过重复键名）">
                <Button
                  size="small"
                  icon={<FunctionOutlined />}
                  data-testid="analytics-recommend-formulas"
                  disabled={formulaCount === 0}
                  onClick={() => onApplyFormulas(recommendations?.formulas ?? [])}
                >
                  追加推荐公式
                </Button>
              </Tooltip>
              <Dropdown
                trigger={['click']}
                disabled={examples.length === 0}
                menu={{
                  items: examples.map(example => ({
                    key: example.id,
                    label: (
                      <div
                        data-testid={`analytics-recommend-example-${example.id}`}
                        style={{ maxWidth: 340, padding: '2px 0' }}
                      >
                        <div style={{ fontWeight: 500 }}>{example.name}</div>
                        <div style={{ fontSize: 12, color: '#94a3b8', whiteSpace: 'normal' }}>
                          {example.description || example.reason}
                        </div>
                      </div>
                    ),
                  })),
                  onClick: ({ key }) => {
                    const example = examples.find(item => item.id === key)
                    if (example) onApplyExample(example)
                  },
                }}
              >
                <Button
                  size="small"
                  icon={<ExperimentOutlined />}
                  data-testid="analytics-recommend-examples"
                  disabled={examples.length === 0}
                >
                  应用典型示例
                </Button>
              </Dropdown>
            </div>
          </div>
        )}
      </Card>
    </div>
  )
}

export default RecommendationPanel
