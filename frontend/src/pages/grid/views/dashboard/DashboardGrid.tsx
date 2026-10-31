/** dashboard 栅格编辑器（ADR 0023 P1）.
 *
 * 读路径与 P0 一致：`normalizeLayout` 收敛后生成 grid 样式；
 * 编辑态在此之上叠加：标题栏拖拽（@dnd-kit）、右下角缩放手柄、方向键微调、
 * 选中描边与文字栅格底纹。拖拽/缩放期间只做本地预览，松手才提交一次
 * `onLayout`（进入撤销栈），避免逐帧写 draft 造成连串重排。
 */

import { useCallback, useMemo, useRef, useState, type CSSProperties, type ReactNode } from 'react'
import {
  DndContext,
  PointerSensor,
  useDraggable,
  useSensor,
  useSensors,
  type DragEndEvent,
} from '@dnd-kit/core'
import type { DashboardConfig, DashboardWidget } from './dashboardModel'
import { DASHBOARD_TYPE_LABELS } from './dashboardModel'
import {
  moveBoxBy,
  normalizeLayout,
  resizeBoxBy,
  toGridStyle,
  type WidgetBox,
} from './dashboardLayout'
import WidgetShell from './WidgetShell'

export interface DashboardGridProps {
  config: DashboardConfig
  editing: boolean
  selectedId: string | null
  onSelect: (id: string | null) => void
  /** 松手提交布局（进入草稿撤销栈） */
  onLayout: (boxes: WidgetBox[]) => void
  onRemove: (id: string) => void
  renderBody: (widget: DashboardWidget) => ReactNode
  isWidgetEmpty: (widget: DashboardWidget) => boolean
  loading?: boolean
  error?: string | null
  /** widget_id → 取数失败文案（单卡隔离，不影响其它卡片） */
  errorById?: Map<string, string>
  /** widget_id → 取数口径提示（样本 / 总行数） */
  metaById?: Map<string, string>
}

interface DraggableCardProps {
  box: WidgetBox
  editing: boolean
  selected: boolean
  title: string
  empty: boolean
  loading: boolean
  error?: string
  metaText?: string
  onSelect: () => void
  onRemove: () => void
  onKeyNudge: (dx: number, dy: number, resize: boolean) => void
  onResizeStart: (event: React.PointerEvent<HTMLDivElement>, box: WidgetBox) => void
  children: ReactNode
}

function DraggableCard({
  box, editing, selected, title, empty, loading, error, metaText, onSelect, onRemove, onKeyNudge, onResizeStart, children,
}: DraggableCardProps) {
  const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({
    id: box.id,
    disabled: !editing,
  })
  const style: CSSProperties = {
    ...toGridStyle(box),
    minWidth: 0,
    minHeight: 0,
    position: 'relative',
    touchAction: editing ? 'none' : undefined,
    transform: isDragging && transform
      ? `translate3d(${transform.x}px, ${transform.y}px, 0)`
      : undefined,
    zIndex: isDragging ? 20 : undefined,
    opacity: isDragging ? 0.85 : undefined,
  }
  return (
    <div
      ref={setNodeRef}
      style={style}
      data-testid={`dashboard-card-${box.id}`}
      role="group"
      aria-label={title}
      aria-selected={selected}
      tabIndex={editing ? 0 : -1}
      onClick={(e) => { e.stopPropagation(); if (editing) onSelect() }}
      onKeyDown={(e) => {
        if (!editing) return
        const resize = e.shiftKey
        const step: Record<string, [number, number]> = {
          ArrowLeft: [-1, 0],
          ArrowRight: [1, 0],
          ArrowUp: [0, -1],
          ArrowDown: [0, 1],
        }
        const delta = step[e.key]
        if (!delta) return
        e.preventDefault()
        onSelect()
        onKeyNudge(delta[0], delta[1], resize)
      }}
    >
      <WidgetShell
        title={title}
        error={error ?? undefined}
        loading={loading}
        empty={empty}
        editing={editing}
        selected={selected}
        dragHandleProps={{ ...attributes, listeners }}
        onRemove={onRemove}
        metaText={metaText}
        testId={`dashboard-widget-${box.id}`}
      >
        {children}
      </WidgetShell>
      {editing && (
        <div
          data-testid={`dashboard-resize-${box.id}`}
          aria-label={`缩放 ${title}`}
          onPointerDown={(e) => onResizeStart(e, box)}
          style={{
            position: 'absolute', right: 2, bottom: 2, width: 16, height: 16,
            cursor: 'nwse-resize', touchAction: 'none', zIndex: 3,
            background: 'linear-gradient(135deg, transparent 45%, var(--cn-text-muted) 45%, var(--cn-text-muted) 55%, transparent 55%)',
          }}
        />
      )}
    </div>
  )
}

export default function DashboardGrid({
  config, editing, selectedId, onSelect, onLayout, onRemove, renderBody, isWidgetEmpty,
  loading = false, error = null, errorById, metaById,
}: DashboardGridProps) {
  const canvasRef = useRef<HTMLDivElement>(null)
  const [preview, setPreview] = useState<WidgetBox[] | null>(null)
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 4 } }))

  const baseBoxes = useMemo(
    () => normalizeLayout(config.widgets.map((w) => w.layout), config.canvas.cols),
    [config.widgets, config.canvas.cols],
  )
  const boxes = preview ?? baseBoxes
  const boxById = new Map(boxes.map((b) => [b.id, b]))
  const titleByWidget = new Map(config.widgets.map((w) => [w.id, w.title || DASHBOARD_TYPE_LABELS[w.type]]))

  /** CSS 像素 → 栅格步长（含 gap；与 CSS Grid 的实际排布一致） */
  const gridMetrics = useCallback(() => {
    const width = canvasRef.current?.clientWidth ?? 0
    const padding = config.canvas.padding * 2
    const cols = config.canvas.cols
    const gap = config.canvas.gap
    const content = Math.max(1, width - padding)
    const colWidth = Math.max(1, (content - gap * (cols - 1)) / cols)
    const rowUnit = Math.max(1, config.canvas.row_height + gap)
    return { colWidth, rowUnit }
  }, [config.canvas])

  const handleDragEnd = useCallback((event: DragEndEvent) => {
    const id = String(event.active.id)
    const box = config.widgets.find((w) => w.id === id)?.layout
    if (!box || !event.delta) return
    const { colWidth, rowUnit } = gridMetrics()
    const dx = Math.round(event.delta.x / colWidth)
    const dy = Math.round(event.delta.y / rowUnit)
    if (!dx && !dy) return
    const moved = moveBoxBy(box, dx, dy, config.canvas.cols)
    const all = config.widgets.map((w) => (w.id === id ? moved : w.layout))
    onLayout(normalizeLayout(all, config.canvas.cols, id))
  }, [config.widgets, config.canvas.cols, gridMetrics, onLayout])

  const handleResizeStart = useCallback((event: React.PointerEvent<HTMLDivElement>, box: WidgetBox) => {
    event.preventDefault()
    event.stopPropagation()
    const startX = event.clientX
    const startY = event.clientY
    const { colWidth, rowUnit } = gridMetrics()
    let latest: WidgetBox[] | null = null
    const move = (ev: PointerEvent) => {
      const dw = Math.round((ev.clientX - startX) / colWidth)
      const dh = Math.round((ev.clientY - startY) / rowUnit)
      const resized = resizeBoxBy(box, dw, dh, config.canvas.cols)
      const all = config.widgets.map((w) => (w.id === box.id ? resized : w.layout))
      latest = normalizeLayout(all, config.canvas.cols, box.id)
      setPreview(latest)
    }
    const up = () => {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', up)
      setPreview(null)
      if (latest) onLayout(latest)
    }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', up)
  }, [config.widgets, config.canvas.cols, gridMetrics, onLayout])

  const handleKeyNudge = useCallback((id: string, dx: number, dy: number, resize: boolean) => {
    const box = config.widgets.find((w) => w.id === id)?.layout
    if (!box) return
    const next = resize
      ? resizeBoxBy(box, dx, dy, config.canvas.cols)
      : moveBoxBy(box, dx, dy, config.canvas.cols)
    const all = config.widgets.map((w) => (w.id === id ? next : w.layout))
    onLayout(normalizeLayout(all, config.canvas.cols, id))
  }, [config.widgets, config.canvas.cols, onLayout])

  return (
    <DndContext sensors={sensors} onDragEnd={handleDragEnd}>
      <div
        ref={canvasRef}
        data-testid="dashboard-canvas"
        onClick={() => editing && onSelect(null)}
        style={{
          flex: 1, minHeight: 0, overflow: 'auto',
          display: 'grid',
          gridTemplateColumns: `repeat(${config.canvas.cols}, minmax(0, 1fr))`,
          gridAutoRows: `${config.canvas.row_height}px`,
          gap: config.canvas.gap,
          padding: config.canvas.padding,
          alignContent: 'start',
          background: 'var(--cn-bg-page)',
          backgroundImage: editing
            ? 'repeating-linear-gradient(to right, var(--cn-border) 0, var(--cn-border) 1px, transparent 1px, transparent calc(100% / var(--db-cols)))'
            : undefined,
          ['--db-cols' as string]: config.canvas.cols,
        }}
      >
        {config.widgets.map((widget) => {
          const box = boxById.get(widget.id) ?? widget.layout
          return (
            <DraggableCard
              key={widget.id}
              box={box}
              editing={editing}
              selected={selectedId === widget.id}
              title={titleByWidget.get(widget.id) ?? DASHBOARD_TYPE_LABELS[widget.type]}
              empty={isWidgetEmpty(widget)}
              loading={loading}
              error={errorById?.get(widget.id) ?? error ?? undefined}
              metaText={metaById?.get(widget.id)}
              onSelect={() => onSelect(widget.id)}
              onRemove={() => onRemove(widget.id)}
              onKeyNudge={(dx, dy, resize) => handleKeyNudge(widget.id, dx, dy, resize)}
              onResizeStart={handleResizeStart}
            >
              {renderBody(widget)}
            </DraggableCard>
          )
        })}
      </div>
    </DndContext>
  )
}
