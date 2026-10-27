/** 文档大纲右侧常驻栏：桌面端默认展开，可拖拽 / 键盘调宽.
 *
 * 宽度只经 `clampOutlineWidth` 收敛；拖动过程回调 `commit=false`（仅预览），
 * 松手 / 键盘操作回调 `commit=true`（由页面写入本地偏好）。
 */

import { useEffect, useRef } from 'react'

import type { OutlineItem } from '@/components/Document/outline'
import OutlineList from './OutlineList'
import {
  OUTLINE_WIDTH_MAX,
  OUTLINE_WIDTH_MIN,
  clampOutlineWidth,
} from './outlinePrefs'

export default function OutlinePanel({
  width,
  outline,
  onWidthChange,
  onAnchorClick,
}: {
  width: number
  outline: OutlineItem[]
  onWidthChange: (width: number, commit?: boolean) => void
  onAnchorClick: (anchor: string) => void
}) {
  /** 卸载时清理拖动监听，避免监听残留 */
  const cleanupRef = useRef<(() => void) | null>(null)
  useEffect(() => () => cleanupRef.current?.(), [])

  const handleMouseDown = (e: React.MouseEvent) => {
    if (e.button !== 0) return
    e.preventDefault()
    cleanupRef.current?.()

    const startX = e.clientX
    const startWidth = width
    let latest = width

    const handleMove = (ev: MouseEvent) => {
      latest = clampOutlineWidth(startWidth - (ev.clientX - startX))
      onWidthChange(latest)
    }
    const handleUp = () => {
      cleanupRef.current?.()
      cleanupRef.current = null
      onWidthChange(latest, true)
    }
    const cleanup = () => {
      document.removeEventListener('mousemove', handleMove)
      document.removeEventListener('mouseup', handleUp)
      document.body.style.userSelect = ''
    }

    cleanupRef.current = cleanup
    document.body.style.userSelect = 'none'
    document.addEventListener('mousemove', handleMove)
    document.addEventListener('mouseup', handleUp)
  }

  /** 手柄键盘可达：左 / 右 = 加宽 / 收窄 16px，Home / End = 最小 / 最大宽度 */
  const handleKeyDown = (e: React.KeyboardEvent) => {
    const next =
      e.key === 'ArrowLeft'
        ? width + 16
        : e.key === 'ArrowRight'
          ? width - 16
          : e.key === 'Home'
            ? OUTLINE_WIDTH_MIN
            : e.key === 'End'
              ? OUTLINE_WIDTH_MAX
              : null
    if (next === null) return
    e.preventDefault()
    onWidthChange(clampOutlineWidth(next), true)
  }

  return (
    <aside
      data-testid="doc-outline-panel"
      aria-label="文档大纲"
      style={{
        width,
        flexShrink: 0,
        minHeight: 0,
        display: 'flex',
        flexDirection: 'column',
        position: 'relative',
        borderLeft: '1px solid var(--cn-border, #e8e8e8)',
        background: 'var(--cn-bg-container, #fff)',
      }}
    >
      <div
        className="cn-doc-outline-resizer"
        data-testid="doc-outline-resizer"
        role="separator"
        aria-orientation="vertical"
        aria-label="调整大纲栏宽度"
        aria-valuemin={OUTLINE_WIDTH_MIN}
        aria-valuemax={OUTLINE_WIDTH_MAX}
        aria-valuenow={width}
        tabIndex={0}
        onMouseDown={handleMouseDown}
        onKeyDown={handleKeyDown}
      />
      <div
        style={{
          flexShrink: 0,
          padding: '10px 12px',
          borderBottom: '1px solid var(--cn-border, #e8e8e8)',
          fontSize: 12,
          color: 'var(--cn-text-secondary, #666)',
        }}
      >
        大纲{outline.length > 0 ? ` (${outline.length})` : ''}
      </div>
      <div style={{ flex: 1, minHeight: 0, overflow: 'auto', padding: '8px 8px' }}>
        <OutlineList outline={outline} onAnchorClick={onAnchorClick} />
      </div>
    </aside>
  )
}
