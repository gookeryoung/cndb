/** 甘特图左侧任务名列 body —— 与右侧共享同一个纵向虚拟窗口. */

import { useEffect, useRef } from 'react'
import type { VirtualItem } from '@tanstack/react-virtual'
import type { RowResponse } from '@/api'
import { densityStyle } from '../gantt/ganttDensity'
import { GanttFlatItem } from '../gantt/ganttTypes'
import { WEIGHT } from '@/theme/tokens'

export interface LeftColBodyProps {
  items: GanttFlatItem[]
  virtualItems: VirtualItem[]
  totalSize: number
  hasGroup: boolean
  ds: ReturnType<typeof densityStyle>
  onRowClick?: (r: RowResponse) => void
  bodyRef: React.RefObject<HTMLDivElement | null>
}

export function LeftColBody({ items, virtualItems, totalSize, hasGroup, ds, onRowClick, bodyRef }: LeftColBodyProps) {
  const leftRef = useRef<HTMLDivElement>(null)

  // 滚动双向同步：右侧 body 是 virtualizer 的滚动元素，右滚时左列跟随 scrollTop；
  // 左列滚动条/滚轮则转发到右侧，由 virtualizer 统一驱动两侧窗口切片
  useEffect(() => {
    const leftEl = leftRef.current
    const rightEl = bodyRef.current
    if (!leftEl || !rightEl) return

    let syncing = false
    const onRightScroll = () => {
      if (syncing) return
      syncing = true
      leftEl.scrollTop = rightEl.scrollTop
      requestAnimationFrame(() => { syncing = false })
    }
    const onLeftScroll = () => {
      if (syncing) return
      syncing = true
      rightEl.scrollTop = leftEl.scrollTop
      requestAnimationFrame(() => { syncing = false })
    }
    rightEl.addEventListener('scroll', onRightScroll)
    leftEl.addEventListener('scroll', onLeftScroll)
    return () => {
      rightEl.removeEventListener('scroll', onRightScroll)
      leftEl.removeEventListener('scroll', onLeftScroll)
    }
  }, [bodyRef])

  return (
    <div
      ref={leftRef}
      style={{
        flex: 1,
        overflowY: 'auto',
        overflowX: 'hidden',
      }}
    >
      <div style={{ position: 'relative', height: totalSize }}>
        {virtualItems.map((vi) => {
          const item = items[vi.index]
          if (item.kind === 'group') {
            const group = item.group
            return (
              <div
                key={vi.key}
                style={{
                  position: 'absolute',
                  top: 0,
                  left: 0,
                  width: '100%',
                  height: item.size,
                  transform: `translateY(${vi.start}px)`,
                  padding: '0 12px',
                  background: `${group.color}15`,
                  borderBottom: '1px solid var(--cn-border)',
                  display: 'flex',
                  alignItems: 'center',
                  gap: 8,
                  fontSize: ds.metaFontSize,
                  fontWeight: WEIGHT.semibold,
                  color: group.color,
                }}
              >
                {/* 左侧色条 */}
                <span
                  style={{
                    width: 3,
                    height: 16,
                    borderRadius: 2,
                    background: group.color,
                    flexShrink: 0,
                  }}
                />
                {/* WBS 组编号 */}
                <span
                  style={{
                    fontSize: ds.metaFontSize - 1,
                    color: 'var(--cn-text-muted)',
                    fontWeight: WEIGHT.medium,
                    fontFamily: 'var(--cn-font-mono)',
                  }}
                >
                  G{group.index}
                </span>
                <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {group.label}
                </span>
                <span style={{ color: 'var(--cn-text-muted)', fontWeight: WEIGHT.regular, marginLeft: 'auto' }}>
                  ({group.tasks.length})
                </span>
              </div>
            )
          }

          {/* 任务行 —— 带树状连接线 */ }
          const { group, task, tIndex } = item
          const isLast = tIndex === group.tasks.length - 1
          return (
            <div
              key={vi.key}
              onClick={() => onRowClick?.(task.row)}
              style={{
                position: 'absolute',
                top: 0,
                left: 0,
                width: '100%',
                height: item.size,
                transform: `translateY(${vi.start}px)`,
                padding: '0 12px',
                borderBottom: '1px solid var(--cn-border)',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                gap: 8,
                transition: 'background 0.15s',
              }}
              onMouseEnter={(e) => { e.currentTarget.style.background = 'var(--cn-bg-subtle)' }}
              onMouseLeave={(e) => { e.currentTarget.style.background = '' }}
            >
              {/* WBS 编号 */}
              <span
                style={{
                  fontSize: ds.metaFontSize - 1,
                  color: 'var(--cn-text-muted)',
                  fontFamily: 'var(--cn-font-mono)',
                  flexShrink: 0,
                  minWidth: hasGroup ? 36 : 28,
                }}
              >
                {hasGroup ? `G${group.index}.${tIndex + 1}` : `${tIndex + 1}`}
              </span>
              {/* 树状连接符 */}
              <span
                style={{
                  color: 'var(--cn-text-muted)',
                  fontSize: ds.titleFontSize,
                  lineHeight: 1,
                  flexShrink: 0,
                  width: 10,
                  textAlign: 'center',
                }}
              >
                {hasGroup ? (isLast ? '└' : '├') : (isLast ? '—' : '│')}
              </span>
              {/* 任务标题 */}
              <div
                style={{
                  flex: 1,
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                  fontSize: ds.titleFontSize,
                  fontWeight: WEIGHT.medium,
                }}
              >
                {task.title}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
