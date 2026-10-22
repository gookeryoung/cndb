/** AI 结果抽屉 —— 统一「预览 → 确认」承载层（ADR 0020 C11 / D16）.
 *
 * 只负责展示状态与动作按钮：loading / error / 原文与新文本对照 / 结构化分区；
 * 请求由 `useLlmAction` 发起，是否应用（写回编辑器内存态或元数据）由调用方决定。
 * 改写类结果应用后**不自动保存**，保存仍走既有草稿 / 提交流程。
 */

import type { ReactNode } from 'react'
import { Alert, Button, Drawer, Skeleton, Space, Typography } from 'antd'

import { RADIUS, SPACE, TEXT } from '@/theme/tokens'
import AiSuggestionList from './AiSuggestionList'

const { Paragraph, Text } = Typography

/** 结构化结果分区：一段文字（摘要）或一组 chips（要点 / 标签） */
export interface AiResultSection {
  key: string
  title: string
  /** 段落正文 */
  text?: string
  /** chips 列表 */
  items?: string[]
  /** chips 为空时的文案 */
  emptyText?: string
  /** chips 是否可多选 */
  selectable?: boolean
  /** 多选选中项（配合 onSelect） */
  selected?: string[]
  onSelect?: (next: string[]) => void
  /** 分区底部补充说明 */
  hint?: ReactNode
  testId?: string
}

export interface AiResultDrawerProps {
  open: boolean
  /** 抽屉标题 */
  title?: ReactNode
  onClose: () => void
  /** 请求中（展示骨架屏，禁用应用 / 重新生成） */
  loading?: boolean
  /** 失败文案（展示 Alert，禁用应用） */
  error?: string | null
  /** 改写类：原文片段（与 resultText 组成左右对照） */
  originalText?: string
  /** 改写类：AI 生成的新片段 */
  resultText?: string
  originalLabel?: string
  resultLabel?: string
  /** 结构化结果（摘要 / 要点 / 标签建议等） */
  sections?: AiResultSection[]
  /** 顶部元信息（模型 / token 用量 / 留痕 id） */
  meta?: ReactNode
  /** 底部说明（如「应用不会自动保存」） */
  hint?: ReactNode
  /** 「应用」按钮文案；不传 onApply 时不渲染应用按钮 */
  applyText?: string
  onApply?: () => void
  /** 「重新生成」按钮文案；不传 onRegenerate 时不渲染该按钮 */
  regenerateText?: string
  onRegenerate?: () => void
  /** 抽屉宽度 */
  width?: number
  testId?: string
}

/** 原文 / AI 结果的左右对照块（不做字符级 diff：AI 往往整段重写，行内高亮收益低） */
function CompareBlock({ label, text, testId }: { label: string; text: string; testId: string }) {
  return (
    <div style={{ flex: '1 1 220px', minWidth: 0 }}>
      <Text strong style={{ display: 'block', fontSize: TEXT.sm, marginBottom: SPACE.xs }}>
        {label}
      </Text>
      <Paragraph
        data-testid={testId}
        style={{
          margin: 0,
          padding: SPACE.md,
          minHeight: 80,
          maxHeight: 320,
          overflow: 'auto',
          whiteSpace: 'pre-wrap',
          wordBreak: 'break-word',
          background: 'var(--cn-bg-subtle, #fafafa)',
          border: '1px solid var(--cn-border, #e8e8e8)',
          borderRadius: RADIUS.sm,
          fontSize: TEXT.sm,
          lineHeight: '1.7',
        }}
      >
        {text}
      </Paragraph>
    </div>
  )
}

export default function AiResultDrawer({
  open,
  title = 'AI 结果',
  onClose,
  loading = false,
  error = null,
  originalText,
  resultText,
  originalLabel = '原文',
  resultLabel = 'AI 结果',
  sections = [],
  meta,
  hint,
  applyText = '应用',
  onApply,
  regenerateText = '重新生成',
  onRegenerate,
  width = 760,
  testId = 'ai-result-drawer',
}: AiResultDrawerProps) {
  const disabled = loading || Boolean(error)
  const hasCompare = originalText !== undefined || resultText !== undefined

  const footer = (
    <Space style={{ width: '100%', justifyContent: 'flex-end' }} wrap>
      <Button data-testid="ai-result-cancel" onClick={onClose}>
        取消
      </Button>
      {onRegenerate && (
        <Button
          data-testid="ai-result-regenerate"
          disabled={loading}
          onClick={onRegenerate}
        >
          {regenerateText}
        </Button>
      )}
      {onApply && (
        <Button
          type="primary"
          data-testid="ai-result-apply"
          disabled={disabled}
          onClick={onApply}
        >
          {applyText}
        </Button>
      )}
    </Space>
  )

  return (
    <Drawer
      open={open}
      title={title}
      width={width}
      onClose={onClose}
      footer={footer}
      destroyOnHidden
    >
      <div data-testid={testId} style={{ display: 'flex', flexDirection: 'column', gap: SPACE.lg }}>
        {meta && (
          <Text type="secondary" style={{ fontSize: TEXT.xs }} data-testid="ai-result-meta">
            {meta}
          </Text>
        )}

        {error && (
          <div data-testid="ai-result-error">
            <Alert
              type="error"
              showIcon
              message={error}
              description="本次调用未改动文档；可稍后重新生成，或缩短选区后重试。"
            />
          </div>
        )}

        {loading && (
          <div data-testid="ai-result-loading">
            <Skeleton active title={false} paragraph={{ rows: 4 }} />
          </div>
        )}

        {!loading && !error && hasCompare && (
          <div
            data-testid="ai-result-compare"
            style={{ display: 'flex', flexWrap: 'wrap', gap: SPACE.lg }}
          >
            <CompareBlock label={originalLabel} text={originalText ?? ''} testId="ai-result-original" />
            <CompareBlock label={resultLabel} text={resultText ?? ''} testId="ai-result-text" />
          </div>
        )}

        {!loading && !error &&
          sections.map(section => (
            <div key={section.key} data-testid={section.testId ?? `ai-result-section-${section.key}`}>
              <Text strong style={{ display: 'block', fontSize: TEXT.sm, marginBottom: SPACE.xs }}>
                {section.title}
              </Text>
              {section.text != null && (
                <Paragraph style={{ margin: 0, fontSize: TEXT.sm, lineHeight: '1.7' }}>
                  {section.text}
                </Paragraph>
              )}
              {section.items != null && (
                <AiSuggestionList
                  items={section.items}
                  emptyText={section.emptyText}
                  selected={section.selectable ? (section.selected ?? []) : undefined}
                  onChange={section.selectable ? section.onSelect : undefined}
                  testId={`${section.testId ?? `ai-result-section-${section.key}`}-chips`}
                />
              )}
              {section.hint && (
                <Text type="secondary" style={{ display: 'block', fontSize: TEXT.xs, marginTop: SPACE.xs }}>
                  {section.hint}
                </Text>
              )}
            </div>
          ))}

        {hint && !error && (
          <Text type="secondary" style={{ fontSize: TEXT.xs }} data-testid="ai-result-hint">
            {hint}
          </Text>
        )}
      </div>
    </Drawer>
  )
}
