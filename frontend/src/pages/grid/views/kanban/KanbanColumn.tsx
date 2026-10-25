/** 看板列（虚拟化）—— 列头统计 + 卡片列表 + 新建入口. */

import { memo, useRef } from 'react'
import { Button, Tag, Tooltip } from 'antd'
import { useVirtualizer } from '@tanstack/react-virtual'
import { PlusOutlined } from '@ant-design/icons'
import type { Field, RowResponse, RowValues } from '@/api'
import type { Density } from '@/theme/tableSettings'
import type { KanbanColumnData } from '../kanbanBoard'
import { densityColumnStyle, estimateCardHeight } from './kanbanDensity'
import { KanbanCard } from './KanbanCard'
import { WEIGHT } from '@/theme/tokens'

export interface KanbanColumnProps {
  col: KanbanColumnData
  fields: Field[]
  opts: Record<string, unknown>
  density: Density
  colStyle: ReturnType<typeof densityColumnStyle>
  onRowClick?: (r: RowResponse) => void
  onDeleteCard?: (r: RowResponse) => void
  canDelete?: boolean
  onAddCard?: (initialValues: RowValues) => void
  canAdd?: boolean
  onToggleDone?: (r: RowResponse, values: RowValues) => void
  canEdit?: boolean
  /** PDF 导出模式：强制全量渲染卡片（虚拟滚动关闭），使滚动区外卡片进入 DOM */
  pdfExporting?: boolean
}

/** KanbanColumn —— 单列看板列组件.
 *
 *  内部使用虚拟化（useVirtualizer）只 mount 可视窗口 + overscan 的卡片，
 *  避免 500 行真实数据全量挂载重型 antd 卡片（Progress / Tag / Tooltip）.
 *  外层 memo 包装阻止 GridPage 无关重渲染时所有列重渲；
 *  列内 virtualizer 只在列首次 mount 时初始化，后续 GridPage 重渲染不触发列内重建。 */
export const KanbanColumn = memo(function KanbanColumn(props: KanbanColumnProps) {
  return <KanbanColumnInner {...props} />
})

/** 完整的 KanbanColumn 内容 —— 含 useVirtualizer + KanbanCard 树. */
export const KanbanColumnInner = memo(function KanbanColumnInner({ col, fields, opts, density, colStyle, onRowClick, onDeleteCard, canDelete, onAddCard, canAdd, onToggleDone, canEdit, pdfExporting }: KanbanColumnProps) {
  const scrollRef = useRef<HTMLDivElement>(null)
  // 阈值 30：真实数据（如 500 行项目表按片区分组）单列常在 60-90 行，
  // 旧阈值 100 下这些列全量挂载重型 antd 卡片导致切看板卡顿；
  // PDF 导出模式下强制全量渲染，滚动区外的卡片才能进入快照
  const useVirtual = col.rows.length >= 30 && !pdfExporting
  const estimatedSize = estimateCardHeight(density)

  const virtualizer = useVirtualizer({
    count: col.rows.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => estimatedSize,
    overscan: 5,
  })

  const items = useVirtual
    ? virtualizer.getVirtualItems()
    : col.rows.map((_, i) => ({ index: i, start: 0, size: estimatedSize, key: i, lane: 0 }))

  // 新增卡片时预填 group_field 的值
  const handleAddCard = () => {
    if (!onAddCard) return
    const groupFieldName = (opts.group_field as string)
    if (groupFieldName && col.rawValue !== undefined) {
      onAddCard({ [groupFieldName]: col.rawValue })
    } else {
      onAddCard({})
    }
  }

  return (
    <div
      key={col.key}
      style={{
        minWidth: colStyle.colMinWidth,
        maxWidth: colStyle.colMaxWidth,
        background: 'var(--cn-bg-subtle)',
        borderRadius: colStyle.borderRadius,
        padding: colStyle.colPadding,
        border: '1px solid var(--cn-border)',
        flexShrink: 0,
        display: 'flex',
        flexDirection: 'column',
      }}
    >
      {/* 列头 */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: colStyle.colHeaderPadding,
          borderBottom: '1px solid var(--cn-border)',
          marginBottom: colStyle.colHeaderMarginBottom,
        }}
      >
        <span style={{ fontWeight: WEIGHT.semibold, fontSize: colStyle.colHeaderFontSize, color: 'var(--cn-text-primary)' }}>
          {col.title}
        </span>
        <span style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
          <span
            style={{
              fontSize: colStyle.colHeaderCountFontSize,
              color: 'var(--cn-text-muted)',
              background: 'var(--cn-bg-container)',
              padding: '2px 8px',
              borderRadius: 10,
            }}
          >
            {col.rows.length}
          </span>
          {col.urgentCount > 0 && (
            <Tag color="red" style={{ margin: 0, fontSize: colStyle.colHeaderCountFontSize }}>
              {col.urgentCount} 紧急
            </Tag>
          )}
          {/* 新增项入口 —— 位于列头最右侧，hover 放大图标与背景色 */}
          {canAdd && onAddCard && (
            <Tooltip title={`在「${col.title}」中新增一项（仅标题字段需填写，其余自动生成）`}>
              <Button
                type="text"
                size="small"
                icon={<PlusOutlined />}
                onClick={(e) => {
                  e.stopPropagation()
                  handleAddCard()
                }}
                style={{ padding: 2, color: 'var(--cn-text-muted)' }}
              />
            </Tooltip>
          )}
        </span>
      </div>

      {/* 卡片列表 —— minHeight:0 允许在 flex column 内收缩，内容超高时列内滚动而非撑开整列 */}
      <div ref={scrollRef} style={{ flex: 1, minHeight: 0, overflowY: 'auto' }}>
        {col.rows.length === 0 ? (
          <div
            style={{
              textAlign: 'center',
              padding: colStyle.emptyPadding,
              color: 'var(--cn-text-muted)',
              fontSize: colStyle.emptyFontSize,
            }}
          >
            无记录
          </div>
        ) : useVirtual ? (
          <div style={{ height: virtualizer.getTotalSize(), position: 'relative' }}>
            {items.map((vi) => (
              <div
                key={vi.key}
                style={{
                  position: 'absolute',
                  top: 0,
                  left: 0,
                  width: '100%',
                  height: vi.size,
                  transform: `translateY(${vi.start}px)`,
                }}
                ref={virtualizer.measureElement}
                data-index={vi.index}
              >
                <KanbanCard
                  row={col.rows[vi.index]}
                  fields={fields}
                  opts={opts}
                  density={density}
                  onRowClick={onRowClick}
                  onDelete={onDeleteCard}
                  canDelete={canDelete}
                  onToggleDone={onToggleDone}
                  canEdit={canEdit}
                />
              </div>
            ))}
          </div>
        ) : (
          col.rows.map((r) => (
            <KanbanCard
              key={r.id}
              row={r}
              fields={fields}
              opts={opts}
              density={density}
              onRowClick={onRowClick}
              onDelete={onDeleteCard}
              canDelete={canDelete}
              onToggleDone={onToggleDone}
              canEdit={canEdit}
            />
          ))
        )}
      </div>

    </div>
  )
})
