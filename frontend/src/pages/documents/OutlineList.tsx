/** 大纲条目列表：抽屉与右侧常驻栏共用，避免两套样式与 testid 漂移. */

import type { OutlineItem } from '@/components/Document/outline'
import { Typography } from 'antd'
import { WEIGHT } from '@/theme/tokens'

const { Text } = Typography

export default function OutlineList({
  outline,
  onAnchorClick,
}: {
  outline: OutlineItem[]
  onAnchorClick: (anchor: string) => void
}) {
  if (outline.length === 0) {
    return <Text type="secondary">暂无标题（用 # 起首行添加，编辑时实时更新）</Text>
  }
  return (
    <>
      {outline.map((o, i) => (
        <div
          key={`${o.anchor}-${i}`}
          data-testid={`doc-outline-item-${i}`}
          style={{
            paddingLeft: (o.level - 1) * 12,
            paddingRight: 8,
            paddingTop: 4,
            paddingBottom: 4,
            fontSize: o.level <= 2 ? 13 : 12,
            fontWeight: o.level === 1 ? WEIGHT.semibold : WEIGHT.regular,
            color: o.level <= 2 ? 'var(--cn-text, inherit)' : 'var(--cn-text-secondary, #666)',
            cursor: 'pointer',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
            borderRadius: 4,
          }}
          onClick={() => onAnchorClick(o.anchor)}
        >
          {o.text}
        </div>
      ))}
    </>
  )
}
