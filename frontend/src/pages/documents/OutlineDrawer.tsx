/** 大纲抽屉：实时标题层级，点击滚动定位预览区锚点（窄屏入口）.
 *
 * 条目渲染与桌面常驻栏共用 `OutlineList`，避免两套样式 / testid。
 */

import { Drawer } from 'antd'

import type { OutlineItem } from '@/components/Document/outline'
import OutlineList from './OutlineList'

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
    <Drawer title="大纲" size={320} open={open} onClose={onClose}>
      <OutlineList outline={outline} onAnchorClick={onAnchorClick} />
    </Drawer>
  )
}
