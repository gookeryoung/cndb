/** 分析页「用一句话生成分析」入口（ADR 0020 P3 / 附录 F）.
 *
 * 定位：只负责输入问题与展示生成状态（loading / 错误 / 提醒 / 已填入提示），
 * 请求由页面用 `useLlmAction` 发起，是否覆盖当前编辑态也由页面确认。
 *
 * 硬约束（ADR 0020 D15 / 附录 F）：
 * - 生成结果只填编辑态，**不自动保存**；保存仍由用户点「保存 / 保存为模板」；
 * - 后端已过 `normalize_config`，前端只展示 warnings，不静默丢弃用户当前配置；
 * - 未选分析表时入口禁用（生成必须有 table_id）。
 */

import { useState } from 'react'
import { Alert, Input, Space, Typography } from 'antd'
import { RobotOutlined } from '@ant-design/icons'

import type { AnalyticsAiTemplateSuggestion } from '@/api/analytics'
import AiActionButton from '@/components/Ai/AiActionButton'
import { SPACE, TEXT } from '@/theme/tokens'
import { AnalyticsBox } from './AnalyticsBox'
import { suggestionWarnings } from './analyticsAi'

const { Text } = Typography

export interface AnalyticsAiPanelProps {
  /** 是否已选分析表：未选时禁用输入与生成按钮 */
  tableReady: boolean
  /** 生成请求中 */
  loading: boolean
  /** 失败文案（后端 detail 优先，由页面从 useLlmAction 透传） */
  error: string | null
  /** 最近一次生成结果：只用于展示 warnings，不代表已保存 */
  suggestion: AnalyticsAiTemplateSuggestion | null
  /** 最近一次真正填入编辑态的模板名（null = 本次会话尚未填入过） */
  appliedName: string | null
  /** 发起生成（问题已 trim；页面负责「覆盖未保存配置」确认与填入编辑态） */
  onGenerate: (question: string) => void
}

export function AnalyticsAiPanel({
  tableReady,
  loading,
  error,
  suggestion,
  appliedName,
  onGenerate,
}: AnalyticsAiPanelProps) {
  const [question, setQuestion] = useState('')
  const warnings = suggestionWarnings(suggestion)
  const trimmed = question.trim()
  const disabled = !tableReady || loading || !trimmed

  const submit = () => {
    if (disabled) return
    onGenerate(trimmed)
  }

  return (
    <div data-testid="analytics-ai-panel">
      <AnalyticsBox
        title="用一句话生成分析"
        icon={<RobotOutlined />}
        extra={<span className="cn-an-muted">AI 只生成建议，不自动保存</span>}
      >
        <Space direction="vertical" size={SPACE.md} style={{ width: '100%' }}>
          <Text type="secondary" style={{ fontSize: TEXT.xs }}>
            描述想看的分析，AI 会把公式 / 图表 / 分组汇总填进下方编辑区；
            例如「按月份看各城市的平均气温，并标出温差最大的三个城市」。
          </Text>
          <Input.TextArea
            data-testid="analytics-ai-question"
            value={question}
            disabled={!tableReady}
            onChange={event => setQuestion(event.target.value)}
            placeholder={
              tableReady
                ? '例如：按产品看合格率，并标出合格率最低的 5 个产品'
                : '请先在「数据源」中选择分析表'
            }
            autoSize={{ minRows: 1, maxRows: 4 }}
            maxLength={500}
            showCount={tableReady}
          />
          <Space size={SPACE.md} wrap>
            <AiActionButton
              type="primary"
              label="生成分析"
              icon={<RobotOutlined />}
              loading={loading}
              disabled={disabled}
              onClick={submit}
              tooltip={tableReady ? '调用大模型生成模板配置建议（不保存）' : '请先选择分析表'}
              ariaLabel="用一句话生成分析"
              testId="analytics-ai-generate"
            />
            <Text type="secondary" style={{ fontSize: TEXT['2xs'] }}>
              问题越具体（指标、维度、排序）生成的配置越贴合；结果需你确认后保存。
            </Text>
          </Space>

          {error && (
            <div data-testid="analytics-ai-error">
              <Alert
                type="error"
                showIcon
                message={error}
                description="生成结果未改动当前配置；可调整问题后重试，或继续手动配置。"
              />
            </div>
          )}

          {appliedName && !error && (
            <div data-testid="analytics-ai-applied">
              <Alert
                type="success"
                showIcon
                message={`已填入编辑态：${appliedName}`}
                description="尚未保存：确认公式 / 图表 / 汇总无误后，点右上角「保存 / 保存为模板」才会写入后端。"
              />
            </div>
          )}

          {warnings.length > 0 && (
            <div data-testid="analytics-ai-warnings">
              <Alert
                type="warning"
                showIcon
                message="生成结果含待确认的假设"
                description={
                  <ul style={{ margin: 0, paddingInlineStart: SPACE.xl }}>
                    {warnings.map(item => (
                      <li key={item} style={{ fontSize: TEXT.xs }}>{item}</li>
                    ))}
                  </ul>
                }
              />
            </div>
          )}
        </Space>
      </AnalyticsBox>
    </div>
  )
}

export default AnalyticsAiPanel
