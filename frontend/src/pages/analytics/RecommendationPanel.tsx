/** 智能推荐 —— 字段角色 chips + 推荐图表 / 汇总 / 公式 / 典型示例.
 *
 * 定位：只负责展示与交互回调（props 注入），请求与状态由 AnalyticsPage 编排，
 * 因此可脱离路由独立单测；接口失败时页面静默降级（不弹全局错误），这里仅展示空态。
 *
 * 排版：卡片头只留标题 + 采样口径，正文按「维度 / 时间 / 指标 / 公式」分组紧凑排列，
 * 一键应用按钮合并到同一行，避免三行按钮把配置栏顶长。
 */

import { Button, Dropdown, Empty, Skeleton, Tag, Tooltip } from 'antd'
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
import { AnalyticsBox } from './AnalyticsBox'
import {
  RECOMMENDATION_CHIP_ROLES,
  formatRecommendationRole,
  recommendationRoleColor,
} from './analyticsModel'
import { WEIGHT } from '@/theme/tokens'

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
      <AnalyticsBox
        title={
          <span className="cn-an-rec-title">
            <ThunderboltOutlined /> 智能推荐
            {tableName ? <span className="cn-an-muted">{tableName}</span> : null}
          </span>
        }
        extra={
          recommendations ? (
            <span data-testid="analytics-recommend-meta">
              采样 {recommendations.sampled_rows}/{recommendations.row_count} 行
              {recommendations.truncated ? '（已截断）' : ''}
            </span>
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
          <>
            {/* 字段角色 chips：维度 / 时间 / 指标（点一下即写入图表与汇总） */}
            {groups.map(group => (
              <div
                key={group.role}
                className="cn-an-chips"
                data-testid={`analytics-recommend-group-${group.role}`}
              >
                <span className="cn-an-chips-label">{formatRecommendationRole(group.role)}</span>
                {group.items.map(field => (
                  <Tooltip key={field.name} title={fieldTooltip(field)}>
                    <Tag
                      className="cn-an-chip"
                      color={recommendationRoleColor(group.role)}
                      data-testid={`analytics-recommend-${group.role}-${field.name}`}
                      onClick={() => chipClick(group.role, field.name)}
                    >
                      {field.name}
                    </Tag>
                  </Tooltip>
                ))}
              </div>
            ))}

            {/* 推荐公式 */}
            {formulaCount > 0 && (
              <div className="cn-an-chips">
                <span className="cn-an-chips-label">公式</span>
                {recommendations!.formulas.map(formula => (
                  <Tooltip key={formula.key} title={formula.reason || formula.expr}>
                    <Tag
                      className="cn-an-chip"
                      color="geekblue"
                      data-testid={`analytics-recommend-formula-${formula.key}`}
                    >
                      {formula.label || formula.key}
                    </Tag>
                  </Tooltip>
                ))}
              </div>
            )}

            {/* 一键应用：同排小按钮，避免三行按钮占掉配置栏高度 */}
            <div className="cn-an-rec-actions">
              <Tooltip title={recommendations?.chart?.reason || '应用推荐图表配置'}>
                <Button
                  size="small"
                  icon={<BarChartOutlined />}
                  data-testid="analytics-recommend-chart"
                  disabled={!recommendations?.chart}
                  onClick={() => recommendations?.chart && onApplyChart(recommendations.chart.chart)}
                >
                  图表
                </Button>
              </Tooltip>
              <Tooltip title={recommendations?.summary?.reason || '应用推荐分组汇总'}>
                <Button
                  size="small"
                  icon={<TableOutlined />}
                  data-testid="analytics-recommend-summary"
                  disabled={!recommendations?.summary}
                  onClick={() => recommendations?.summary && onApplySummary(recommendations.summary.summary)}
                >
                  汇总
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
                  公式
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
                        <div style={{ fontWeight: WEIGHT.medium }}>{example.name}</div>
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
                  示例
                </Button>
              </Dropdown>
            </div>
          </>
        )}
      </AnalyticsBox>
    </div>
  )
}

export default RecommendationPanel
