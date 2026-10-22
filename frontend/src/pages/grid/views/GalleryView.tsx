/** 卡片画廊视图 — 内容型数据表的阅读态：标题 / 摘要 / 彩色标签 / 日期徽章 / 元信息.
 *
 * view_options 契约（GALLERY_OPTIONS，7 项）:
 * - title_field:    卡片标题字段（text/longtext，留空自动取首个文本字段，再退 id）
 * - summary_field:  摘要字段（longtext/text，留空自动取首个 longtext）
 * - tag_fields:     彩色标签字段列表（select/multiselect/text，单卡最多 6 个，超出以 +N 表示）
 * - meta_fields:    底部元信息字段列表（最多 4 项，空值跳过）
 * - date_field:     日期徽章字段（date/datetime，取前 10 位）
 * - card_size:      栅格最小列宽 small(220) / medium(280) / large(360)
 * - summary_lines:  摘要截断行数 2 / 3 / 4 / 6
 *
 * 交互约定:
 * - 只读阅读态：不做内联编辑 / 拖拽 / 行选中，编辑入口仍为 grid 与行详情。
 * - 整卡可点击 + 可键盘（Enter / Space）打开行详情。
 * - 非 grid 视图最多 2000 行，前端按 GALLERY_BATCH_SIZE 分批挂载 +「加载更多」；
 *   rows / view.id 变化时重置批次。
 * - 排序沿用视图 sortings（服务端已生效），组件内不再排序。
 *
 * 子模块：配置解析 / 标签归一 / 元信息在 ./galleryBoard.ts（纯函数，可独立单测）。
 */

import { memo, useEffect, useMemo, useState } from 'react'
import { Button, Empty, Skeleton, Tag } from 'antd'

import type { Field, RowResponse, View } from '@/api'
import { resolveTagColor } from '@/utils/tagColors'
import { GALLERY_OPTIONS, resolveOpts } from '../view-config/viewOptionSchema'
import {
  GALLERY_BATCH_SIZE,
  GALLERY_COLUMN_MIN_PX,
  galleryCardTags,
  galleryCardTitle,
  galleryDateBadge,
  galleryMetaItems,
  gallerySummaryText,
  galleryTagOptions,
  resolveGalleryConfig,
  type GalleryConfig,
} from './galleryBoard'

// ── 单卡 ──────────────────────────────────────────────

function GalleryCard({
  row,
  fields,
  config,
  onRowClick,
}: {
  row: RowResponse
  fields: Field[]
  config: GalleryConfig
  onRowClick?: (r: RowResponse) => void
}) {
  const [hovered, setHovered] = useState(false)
  const title = galleryCardTitle(row, config.titleField)
  const summary = gallerySummaryText(row, config.summaryField)
  const dateBadge = config.dateField ? galleryDateBadge(row[config.dateField]) : ''
  const { tags, overflow } = galleryCardTags(row, fields, config.tagFields)
  const metaItems = galleryMetaItems(fields, row, config.metaFields)
  const clickable = !!onRowClick
  const hasHeader = tags.length > 0 || !!dateBadge

  return (
    <div
      data-testid="gallery-card"
      role={clickable ? 'button' : undefined}
      tabIndex={clickable ? 0 : undefined}
      aria-label={title}
      onClick={() => onRowClick?.(row)}
      onKeyDown={(e) => {
        if (!clickable) return
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          onRowClick?.(row)
        }
      }}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: 8,
        padding: 14,
        background: 'var(--cn-bg-container)',
        border: `1px solid ${hovered && clickable ? 'var(--cn-brand-color)' : 'var(--cn-border)'}`,
        borderRadius: 'var(--cn-radius-lg)',
        boxShadow: hovered && clickable ? '0 4px 12px rgba(0, 0, 0, 0.08)' : 'none',
        cursor: clickable ? 'pointer' : 'default',
        transition: 'border-color 0.15s, box-shadow 0.15s',
        minWidth: 0,
      }}
    >
      {hasHeader && (
        <div style={{ display: 'flex', alignItems: 'flex-start', gap: 8 }}>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, flex: 1, minWidth: 0 }}>
            {tags.map((tag, i) => (
              <Tag
                key={`${tag.field.name}-${tag.label}-${i}`}
                data-testid="gallery-tag"
                color={resolveTagColor(tag.label, galleryTagOptions(tag.field), i)}
                style={{ margin: 0 }}
              >
                {tag.label}
              </Tag>
            ))}
            {overflow > 0 && (
              <Tag data-testid="gallery-tag" style={{ margin: 0 }}>
                +{overflow}
              </Tag>
            )}
          </div>
          {dateBadge && (
            <span
              style={{
                flexShrink: 0,
                fontSize: 12,
                color: 'var(--cn-text-secondary)',
                whiteSpace: 'nowrap',
                lineHeight: '22px',
              }}
            >
              {dateBadge}
            </span>
          )}
        </div>
      )}
      <div
        data-testid="gallery-card-title"
        style={{
          fontSize: 15,
          fontWeight: 600,
          lineHeight: 1.45,
          color: 'var(--cn-text-primary)',
          display: '-webkit-box',
          WebkitBoxOrient: 'vertical',
          WebkitLineClamp: 2,
          overflow: 'hidden',
          wordBreak: 'break-word',
        }}
      >
        {title}
      </div>
      {summary && (
        <div
          data-testid="gallery-summary"
          style={{
            fontSize: 13,
            lineHeight: 1.6,
            color: 'var(--cn-text-secondary)',
            whiteSpace: 'pre-wrap',
            overflowWrap: 'anywhere',
            display: '-webkit-box',
            WebkitBoxOrient: 'vertical',
            WebkitLineClamp: config.summaryLines,
            overflow: 'hidden',
          }}
        >
          {summary}
        </div>
      )}
      {metaItems.length > 0 && (
        <div
          style={{
            display: 'flex',
            flexWrap: 'wrap',
            gap: 4,
            marginTop: 'auto',
            paddingTop: 8,
            borderTop: '1px solid var(--cn-border-soft)',
            fontSize: 12,
            color: 'var(--cn-text-muted)',
          }}
        >
          {metaItems.map((item, i) => (
            <span key={item.field.name} style={{ display: 'inline-flex', gap: 4, minWidth: 0 }}>
              {i > 0 && <span aria-hidden>·</span>}
              <span data-testid="gallery-meta" style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {item.label}：{item.text}
              </span>
            </span>
          ))}
        </div>
      )}
    </div>
  )
}

// ── 视图 ──────────────────────────────────────────────

export default memo(function GalleryView({
  rows,
  fields,
  view,
  onRowClick,
  loading = false,
  error = false,
  onRetry,
}: {
  rows: RowResponse[]
  fields: Field[]
  view?: View | null
  onRowClick?: (r: RowResponse) => void
  /** 数据请求进行中（且暂无缓存行）—— 显示骨架卡而不是「暂无数据」 */
  loading?: boolean
  /** 数据请求失败 —— 显示失败态与重试，不能伪装成空表 */
  error?: boolean
  onRetry?: () => void
}) {
  const opts = useMemo(
    () => resolveOpts(view?.view_options as Record<string, unknown> | undefined, GALLERY_OPTIONS),
    [view?.view_options],
  )
  const config = useMemo(() => resolveGalleryConfig(fields, opts), [fields, opts])

  const [visibleCount, setVisibleCount] = useState(GALLERY_BATCH_SIZE)
  // 数据或视图切换时重置批次 —— 否则换表后沿用上一次的「加载更多」进度
  useEffect(() => {
    setVisibleCount(GALLERY_BATCH_SIZE)
  }, [rows, view?.id])

  const minColPx = GALLERY_COLUMN_MIN_PX[config.cardSize]

  if (error) {
    return (
      <div data-testid="gallery-view" data-state="error" style={{ padding: 48 }}>
        <Empty description="数据加载失败">
          {onRetry && <Button data-testid="gallery-retry" onClick={onRetry}>重试</Button>}
        </Empty>
      </div>
    )
  }

  if (rows.length === 0) {
    // 加载态与空态必须区分：否则切表 / 返回表页的首帧永远显示「暂无数据」，看起来像数据没了
    if (loading) {
      return (
        <div
          data-testid="gallery-loading"
          style={{
            flex: 1,
            minHeight: 300,
            overflow: 'hidden',
            padding: '0 2px 8px',
            display: 'grid',
            gridTemplateColumns: `repeat(auto-fill, minmax(${minColPx}px, 1fr))`,
            gap: 16,
          }}
        >
          {Array.from({ length: 6 }, (_, i) => (
            <div
              key={i}
              style={{
                padding: 14,
                background: 'var(--cn-bg-container)',
                border: '1px solid var(--cn-border)',
                borderRadius: 'var(--cn-radius-lg)',
              }}
            >
              <Skeleton active title={{ width: '70%' }} paragraph={{ rows: 3 }} />
            </div>
          ))}
        </div>
      )
    }
    return <Empty data-testid="gallery-view" data-state="empty" description="暂无数据" style={{ padding: 48 }} />
  }

  const visibleRows = rows.slice(0, visibleCount)
  const remaining = rows.length - visibleRows.length

  return (
    <div
      data-testid="gallery-view"
      style={{ flex: 1, minHeight: 300, overflow: 'auto', padding: '0 2px 8px' }}
    >
      <div data-testid="gallery-count" style={{ padding: '0 2px 8px', fontSize: 12, color: 'var(--cn-text-muted)' }}>
        共 {rows.length} 条
      </div>
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: `repeat(auto-fill, minmax(${minColPx}px, 1fr))`,
          gap: 16,
        }}
      >
        {visibleRows.map((row) => (
          <GalleryCard
            key={row.id}
            row={row}
            fields={fields}
            config={config}
            onRowClick={onRowClick}
          />
        ))}
      </div>
      <div style={{ textAlign: 'center', padding: '16px 0' }}>
        {remaining > 0 ? (
          <Button
            data-testid="gallery-load-more"
            onClick={() => setVisibleCount((c) => c + GALLERY_BATCH_SIZE)}
          >
            加载更多（剩余 {remaining}）
          </Button>
        ) : rows.length > GALLERY_BATCH_SIZE ? (
          <span style={{ fontSize: 12, color: 'var(--cn-text-muted)' }}>已显示全部</span>
        ) : null}
      </div>
    </div>
  )
})
