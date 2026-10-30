/** AI 结论解读抽屉（ADR 0020 P3 / 附录 F）.
 *
 * 定位：只展示「结论 + 口径提醒」，不做任何写回（解读只读，不写模板 / 数据）。
 * 由分析页 `lazy(() => import(...))` 挂载，避免解读 UI 进入分析页首屏 chunk；
 * 状态（loading / error / 结果）由页面用 `useLlmAction` 统一管理后透传。
 *
 * 与 P1 `components/Ai/AiResultDrawer` 同视觉语言：元信息一行、Alert + Skeleton
 * 承载失败与加载、正文用主题 token；差异是摘要 / 要点用可折叠区展示，并明确
 * 「只读、不修改」。
 */

import type { ReactNode } from 'react'
import { Alert, Button, Collapse, Drawer, Empty, Skeleton, Space, Typography } from 'antd'

import type { AnalyticsAiExplainResult } from '@/api/analytics'
import { LINE, SPACE, TEXT } from '@/theme/tokens'

const { Paragraph, Text } = Typography

export interface AnalyticsAiExplainDrawerProps {
  open: boolean
  onClose: () => void
  /** 请求中（展示骨架屏，禁用重新解读） */
  loading: boolean
  /** 失败文案（后端 detail 优先） */
  error: string | null
  result: AnalyticsAiExplainResult | null
  /** 顶部元信息（模型 / token 用量 / 留痕 id） */
  meta?: ReactNode
  /** 解读依据（如「分组汇总 8 行 · 图表类型 bar」），帮助用户判断口径 */
  basis?: string
  /** 重新解读（使用同一份结果再请求一次） */
  onRegenerate: () => void
  testId?: string
}

export default function AnalyticsAiExplainDrawer({
  open,
  onClose,
  loading,
  error,
  result,
  meta,
  basis,
  onRegenerate,
  testId = 'analytics-ai-explain',
}: AnalyticsAiExplainDrawerProps) {
  const caveats = result?.caveats ?? []
  const footer = (
    <Space style={{ width: '100%', justifyContent: 'flex-end' }}>
      <Button data-testid="analytics-ai-explain-close" onClick={onClose}>
        关闭
      </Button>
      <Button
        data-testid="analytics-ai-explain-regenerate"
        loading={loading}
        disabled={loading}
        onClick={onRegenerate}
      >
        重新解读
      </Button>
    </Space>
  )

  return (
    <Drawer
      open={open}
      title="AI 结论解读"
      size={640}
      onClose={onClose}
      footer={footer}
      destroyOnHidden
    >
      <div data-testid={testId} style={{ display: 'flex', flexDirection: 'column', gap: SPACE.lg }}>
        <Text type="secondary" style={{ fontSize: TEXT.xs }}>
          AI 只依据当前汇总结果（最多 50 行）生成解读，不修改模板与数据；结论需结合业务口径自行判断。
        </Text>

        {basis && (
          <Text type="secondary" style={{ fontSize: TEXT['2xs'] }} data-testid="analytics-ai-explain-basis">
            {basis}
          </Text>
        )}

        {meta && (
          <Text type="secondary" style={{ fontSize: TEXT['2xs'] }} data-testid="analytics-ai-explain-meta">
            {meta}
          </Text>
        )}

        {loading && (
          <div data-testid="analytics-ai-explain-loading">
            <Skeleton active title={false} paragraph={{ rows: 4 }} />
          </div>
        )}

        {!loading && error && (
          <div data-testid="analytics-ai-explain-error">
            <Alert
              type="error"
              showIcon
              title={error}
              description="本次调用未改动任何模板或数据；可稍后点「重新解读」，或先运行分析刷新结果。"
            />
          </div>
        )}

        {!loading && !error && result && (
          <>
            <section data-testid="analytics-ai-insight">
              <Text strong style={{ display: 'block', fontSize: TEXT.sm, marginBottom: SPACE.xs }}>
                结论
              </Text>
              <Paragraph
                style={{
                  margin: 0,
                  fontSize: TEXT.sm,
                  lineHeight: LINE.relaxed,
                  whiteSpace: 'pre-wrap',
                  wordBreak: 'break-word',
                }}
              >
                {result.insight?.trim() || '（模型未给出结论，可点「重新解读」再试）'}
              </Paragraph>
            </section>

            <Collapse
              data-testid="analytics-ai-caveats"
              size="small"
              defaultActiveKey={caveats.length > 0 ? ['caveats'] : []}
              items={[
                {
                  key: 'caveats',
                  label: `口径提醒（${caveats.length}）`,
                  children: caveats.length > 0 ? (
                    <ul style={{ margin: 0, paddingInlineStart: SPACE.xl }}>
                      {caveats.map(item => (
                        <li key={item} style={{ fontSize: TEXT.xs }}>{item}</li>
                      ))}
                    </ul>
                  ) : (
                    <Empty
                      image={Empty.PRESENTED_IMAGE_SIMPLE}
                      description="模型未提出额外口径提醒"
                    />
                  ),
                },
              ]}
            />
          </>
        )}

        {!loading && !error && !result && (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无解读结果" />
        )}
      </div>
    </Drawer>
  )
}
