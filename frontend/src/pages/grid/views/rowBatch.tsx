/**
 * 非 grid 视图的分批挂载（ADR 0046 D7）.
 *
 * 非 grid 视图由 `useGridData` 一次拉最多 2000 行（VIEW_FETCH_ALL_LIMIT），
 * gallery 已按 48/批分批，其余视图此前是全量挂载 —— 2000 个 DOM 节点 + 每个节点的
 * 字段格式化足以让切视图明显卡顿。
 *
 * 这组工具给「线性渲染整行」的视图用：拿到前 N 行 + 「加载更多」，rows / 视图 id 变化
 * 时自动回到第一批。聚合型视图（图表按分组聚合成点、看板按列分组）不需要分批。
 */

import { useEffect, useMemo, useState } from 'react'
import { Button } from 'antd'

import { WEIGHT } from '@/theme/tokens'

/** 每批挂载的行数（页面上 200 行 ≈ 可感知的一次渲染成本上限） */
export const VIEW_BATCH_SIZE = 200

export interface RowBatch<T> {
  /** 当前批次可见的行（总是 rows 的前缀） */
  visibleRows: T[]
  /** 尚未挂载的行数 */
  remaining: number
  /** 全部行数 */
  total: number
  /** 追加一批 */
  loadMore: () => void
}

/**
 * 分批挂载行。
 *
 * @param rows 视图拿到的全部行（服务端已按 sortings 排好序）
 * @param batchSize 每批行数，默认 VIEW_BATCH_SIZE
 */
export function useRowBatch<T>(rows: T[], batchSize: number = VIEW_BATCH_SIZE): RowBatch<T> {
  const [visibleCount, setVisibleCount] = useState(batchSize)

  // rows 变化（切表 / 切视图 / 筛选变化）时回到第一批，避免保留旧的展开量
  useEffect(() => {
    setVisibleCount(batchSize)
  }, [rows, batchSize])

  const visibleRows = useMemo(
    () => (rows.length > visibleCount ? rows.slice(0, visibleCount) : rows),
    [rows, visibleCount],
  )

  return {
    visibleRows,
    remaining: rows.length - visibleRows.length,
    total: rows.length,
    loadMore: () => setVisibleCount(c => c + batchSize),
  }
}

interface ViewBatchFooterProps {
  remaining: number
  total: number
  onLoadMore: () => void
  fontSize?: number
}

/** 分批挂载的底部「加载更多」条（行数不超过一批时不渲染） */
export function ViewBatchFooter({ remaining, total, onLoadMore, fontSize = 12 }: ViewBatchFooterProps) {
  if (total <= VIEW_BATCH_SIZE) return null
  return (
    <div
      data-testid="view-batch-footer"
      style={{
        padding: '12px 0',
        textAlign: 'center',
        borderTop: '1px solid var(--cn-border)',
        background: 'var(--cn-bg-container)',
        flexShrink: 0,
      }}
    >
      {remaining > 0 ? (
        <Button data-testid="view-load-more" size="small" onClick={onLoadMore}>
          加载更多（剩余 {remaining}）
        </Button>
      ) : (
        <span style={{ fontSize, color: 'var(--cn-text-muted)', fontWeight: WEIGHT.regular }}>
          已显示全部 {total} 条
        </span>
      )}
    </div>
  )
}
