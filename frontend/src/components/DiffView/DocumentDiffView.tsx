/**
 * 文档版本差异视图：统一 / 并排两种模式 + 双端行号 + 行内高亮 + 变更统计。
 *
 * 输入为后端 `GET /{wid}/documents/{doc_id}/diff` 返回的 unified diff 文本，
 * 解析与配对逻辑全部在 {@link ./diffModel} 中（纯函数、可单测）。
 */

import { useMemo, useState } from 'react'
import { Empty, Segmented } from 'antd'

import { buildSplitRows, diffStats, pairInline, parseUnifiedDiff } from './diffModel'
import type { DiffLine, InlineSegment } from './diffModel'

interface DocumentDiffViewProps {
  /** unified diff 文本；空串表示两版本一致 */
  diff: string
  /** 旧版本标签，如 `v3` */
  baseLabel?: string
  /** 新版本标签，如 `v4` */
  headLabel?: string
}

/** 渲染行内片段：变化片段用高亮底色标出 */
function renderInline(line: DiffLine) {
  if (!line.inline || line.inline.length === 0) return line.text
  return line.inline.map((seg: InlineSegment, i: number) =>
    seg.changed ? (
      <mark key={i} className="cn-diff-inline">
        {seg.text}
      </mark>
    ) : (
      <span key={i}>{seg.text}</span>
    ),
  )
}

const SIGN: Record<string, string> = { add: '+', del: '−' }

export default function DocumentDiffView({ diff, baseLabel, headLabel }: DocumentDiffViewProps) {
  const [mode, setMode] = useState<'unified' | 'split'>('unified')

  const lines = useMemo(() => pairInline(parseUnifiedDiff(diff)), [diff])
  const splitRows = useMemo(() => buildSplitRows(lines), [lines])
  const stats = useMemo(() => diffStats(lines), [lines])

  const toolbar = (
    <div className="cn-diff-toolbar">
      <div className="cn-diff-labels">
        {baseLabel && <span className="cn-diff-label">{baseLabel}</span>}
        <span className="cn-diff-arrow">→</span>
        {headLabel && <span className="cn-diff-label">{headLabel}</span>}
      </div>
      <div className="cn-diff-stats">
        <span className="cn-diff-stat cn-diff-stat--add">+{stats.added} 新增</span>
        <span className="cn-diff-stat cn-diff-stat--del">−{stats.removed} 删除</span>
      </div>
      <Segmented
        size="small"
        value={mode}
        onChange={(v) => setMode(v as 'unified' | 'split')}
        options={[
          { label: '统一', value: 'unified' },
          { label: '并排', value: 'split' },
        ]}
      />
    </div>
  )

  if (lines.length === 0) {
    return (
      <div className="cn-diff" data-testid="document-diff">
        {toolbar}
        <div className="cn-diff-empty">
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="两个版本内容一致，无差异" />
        </div>
      </div>
    )
  }

  return (
    <div className="cn-diff" data-testid="document-diff">
      {toolbar}
      {mode === 'unified' ? (
        <div className="cn-diff-body" data-testid="diff-unified">
          {lines.map((line, i) =>
            line.kind === 'hunk' || line.kind === 'meta' ? (
              <div key={i} className={`cn-diff-line cn-diff-line--${line.kind}`}>
                <span className="cn-diff-text">{line.text}</span>
              </div>
            ) : (
              <div key={i} className={`cn-diff-line cn-diff-line--${line.kind}`}>
                <span className="cn-diff-no">{line.oldNo ?? ''}</span>
                <span className="cn-diff-no">{line.newNo ?? ''}</span>
                <span className="cn-diff-sign">{SIGN[line.kind] ?? ''}</span>
                <span className="cn-diff-text">{renderInline(line)}</span>
              </div>
            ),
          )}
        </div>
      ) : (
        <div className="cn-diff-body cn-diff-body--split" data-testid="diff-split">
          {splitRows.map((row, i) =>
            row.kind === 'hunk' || row.kind === 'meta' ? (
              <div key={i} className={`cn-diff-line cn-diff-line--${row.kind}`}>
                <span className="cn-diff-text">{row.left?.text ?? row.right?.text ?? ''}</span>
              </div>
            ) : (
              <div key={i} className="cn-diff-row">
                <div className={`cn-diff-cell ${row.left ? `cn-diff-cell--${row.left.kind}` : 'cn-diff-cell--empty'}`}>
                  <span className="cn-diff-no">{row.left?.oldNo ?? ''}</span>
                  <span className="cn-diff-text">{row.left ? renderInline(row.left) : ''}</span>
                </div>
                <div
                  className={`cn-diff-cell ${row.right ? `cn-diff-cell--${row.right.kind}` : 'cn-diff-cell--empty'}`}
                >
                  <span className="cn-diff-no">{row.right?.newNo ?? ''}</span>
                  <span className="cn-diff-text">{row.right ? renderInline(row.right) : ''}</span>
                </div>
              </div>
            ),
          )}
        </div>
      )}
    </div>
  )
}
