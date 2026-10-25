/** 大纲抽屉：实时标题层级，点击滚动定位预览区锚点（从 DocumentEditorPage 抽出）. */

import { Drawer, Typography } from 'antd'

import type { OutlineItem } from '@/components/Document/outline'
import { WEIGHT } from '@/theme/tokens'

const { Text } = Typography

export default function OutlineDrawer({
  open,
  onClose,
  outline,
  onAnchorClick,
}: {
  open: boolean
  onClose: () => void
  outline: OutlineItem[]
  onAnchorClick: (anchor: string) => void
}) {
  return (
    <Drawer title="大纲" width={320} open={open} onClose={onClose}>
      {outline.length === 0 ? (
        <Text type="secondary">暂无标题（用 # 起首行添加，编辑时实时更新）</Text>
      ) : (
        outline.map((o, i) => (
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
        ))
      )}
    </Drawer>
  )
}
