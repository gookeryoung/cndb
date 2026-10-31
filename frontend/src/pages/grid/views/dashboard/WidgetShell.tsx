/** dashboard widget 外壳：统一卡片边框 + 标题 + 加载/错误/空态（ADR 0023 P0）.
 *
 * 只负责壳与状态呈现，具体内容由 widgets/* 注入；四态优先级：
 * 错误 > 加载 > 空 > 内容。
 */

import type { ReactNode } from 'react'
import { Empty, Skeleton, Tooltip } from 'antd'
import { DeleteOutlined, HolderOutlined } from '@ant-design/icons'
import type { DraggableAttributes, DraggableSyntheticListeners } from '@dnd-kit/core'
import { WEIGHT } from '@/theme/tokens'

/** 拖拽手柄属性（来自 @dnd-kit/useDraggable 的 attributes + listeners） */
export interface WidgetDragHandleProps extends DraggableAttributes {
 listeners?: DraggableSyntheticListeners
}

export interface WidgetShellProps {
  title?: string
  /** 错误文案；非空时覆盖内容显示错误态 */
  error?: string
  /** 数据加载中 */
  loading?: boolean
  /** 数据为空（text 组件恒为 false） */
  empty?: boolean
  emptyText?: string
  /** 卡片高度撑满栅格单元 */
  children: ReactNode
  testId?: string
  /** 编辑态：显示拖拽手柄与删除入口 */
  editing?: boolean
  /** 当前选中 */
  selected?: boolean
  dragHandleProps?: WidgetDragHandleProps
  onRemove?: () => void
}

export default function WidgetShell({
  title,
  error,
  loading = false,
  empty = false,
  emptyText = '暂无数据',
  children,
  testId = 'dashboard-widget',
  editing = false,
  selected = false,
  dragHandleProps,
  onRemove,
}: WidgetShellProps) {
  // listeners 是 { onPointerDown: ... } 的映射对象，必须逐事件展开到 DOM；
  // 若整体作为 `listeners={...}` 透传，dnd-kit 收不到激活事件（拖拽永不启动）。
  const { listeners, ...handleAttrs } = dragHandleProps ?? {}
  let body: ReactNode = children
  if (error) {
    body = (
      <div
        data-testid={`${testId}-error`}
        style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--cn-danger, #cf1322)', fontSize: 12 }}
      >
        {error}
      </div>
    )
  } else if (loading) {
    body = (
      <div data-testid={`${testId}-loading`} style={{ flex: 1, minHeight: 0 }}>
        <Skeleton active title={false} paragraph={{ rows: 3 }} />
      </div>
    )
  } else if (empty) {
    body = (
      <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={emptyText} data-testid={`${testId}-empty`} />
      </div>
    )
  }

  return (
    <div
      data-testid={testId}
      style={{
        height: '100%', minHeight: 0, display: 'flex', flexDirection: 'column',
        padding: '10px 12px', boxSizing: 'border-box', overflow: 'hidden',
        background: 'var(--cn-bg-container)',
        border: `1px solid ${selected ? 'var(--cn-primary, #1677ff)' : 'var(--cn-border)'}`,
        borderRadius: 8,
        boxShadow: selected ? '0 0 0 2px var(--cn-primary-bg, rgba(22,119,255,.15))' : undefined,
        transition: 'border-color .15s, box-shadow .15s',
      }}
    >
      {(title || editing) && (
        <div
          style={{ flexShrink: 0, display: 'flex', alignItems: 'center', gap: 6, marginBottom: 8 }}
        >
          {editing && (
            <span
              data-testid={`${testId}-drag-handle`}
              {...handleAttrs}
              {...(listeners ?? {})}
              // 手柄上的点击不应冒泡成卡片选中（拖动松手会误开属性面板）
              onClick={(e) => e.stopPropagation()}
              style={{ cursor: 'grab', color: 'var(--cn-text-muted)', display: 'inline-flex', touchAction: 'none' }}
            >
              <HolderOutlined style={{ pointerEvents: 'none' }} />
            </span>
          )}
          <div
            data-testid={`${testId}-title`}
            style={{
              flex: 1, minWidth: 0, fontWeight: WEIGHT.semibold, fontSize: 13,
              color: 'var(--cn-text-primary)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
            }}
          >
            {title}
          </div>
          {editing && onRemove && (
            <Tooltip title="删除组件">
              <span
                data-testid={`${testId}-remove`}
                onClick={(e) => { e.stopPropagation(); onRemove() }}
                style={{ cursor: 'pointer', color: 'var(--cn-text-muted)', display: 'inline-flex' }}
              >
                <DeleteOutlined />
              </span>
            </Tooltip>
          )}
        </div>
      )}
      <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column' }}>{body}</div>
    </div>
  )
}
