/** 简易 unified diff 渲染（行级着色）—— 从 DocumentEditorPage 抽出. */

import { useMemo } from 'react'

/** 简易 unified diff 渲染（行级着色） */
export default function DiffView({ diff }: { diff: string }) {
  const lines = useMemo(() => diff.split('\n'), [diff])
  return (
    <pre
      style={{
        fontSize: 12,
        lineHeight: 1.6,
        fontFamily: 'var(--cn-mono, monospace)',
        overflow: 'auto',
        maxHeight: 480,
        padding: 12,
        background: 'var(--cn-bg-secondary, #f6f6f6)',
        borderRadius: 8,
      }}
    >
      {lines.map((line, i) => {
        const color = line.startsWith('+') && !line.startsWith('+++')
          ? '#2e7d32'
          : line.startsWith('-') && !line.startsWith('---')
            ? '#c62828'
            : undefined
        const bg = color ? (line.startsWith('+') ? '#e8f5e9' : '#ffebee') : undefined
        return (
          <div key={i} style={{ color, background: bg, whiteSpace: 'pre-wrap' }}>
            {line || ' '}
          </div>
        )
      })}
    </pre>
  )
}
