/** 矩阵视图组件 — 二维分类网格：纵轴 × 横轴，单元格填入同时符合两类别的行卡片.
 *
 * 视觉采用「左侧彩色竖条 + 区域标题加粗」组合模式：
 * - 纵轴行头与横轴列头复用 MatrixAxisHeader —— 4px 圆角彩色竖条 + 加粗标题 + 数量徽章；
 *   竖条颜色按索引从 antd 官方预设主色循环取色（行列各算一组）。
 * - 配色基础对齐其他视图：角格/行头列/列头行等轴区结构底色用中性 var(--cn-bg-subtle)，
 *   边框为普通 1px var(--cn-border)；列方向用 8 色板色相透明色区分（列头 20% 混 bg-subtle，
 *   数据格 `${hex}26` ≈15% 半透明——整列长带浓度须高于甘特小面积行背景 8% 档，空格同色使列带连贯）；
 *   行方向用 1px 细实线区分（数据格 borderBottom，行头 borderBottom 贯通）。
 * - 左上角标注格展示「纵轴/横轴」主题色徽章 + 加粗字段名。
 * - 布局为 CSS Grid：首列行头 sticky left、首行列头 sticky top，左上角标注格双向 sticky；
 *   网格区域独立滚动，行头/列头在滚动时保持可见。
 * - 单元格高度随内容自适应（无硬上限），行轨道高度由该行最高单元格决定。
 *
 * view_options 契约：
 * - row_field（必填）/ column_field（必填）/ date_granularity（默认 month）/ title_field（可选）
 */

import { useMemo, useState } from 'react'
import { App as AntApp, Empty, InputNumber, Spin, Tooltip } from 'antd'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { fieldApi, recordApi } from '@/api'
import type { RowListResponse, RowResponse, Field, View } from '@/api'
import type { Density } from '@/theme/tableSettings'
import { resolveOpts, MATRIX_OPTIONS } from '../view-config/viewOptionSchema'
import { formatFieldDisplayValue } from '../cells/fieldValueFormat'
import {
  buildMatrixGrid,
  buildMonthKeys,
  buildScoreMatrixGrid,
  bucketTitle,
  cellKey,
  type MatrixDateGranularity,
} from './matrixBoard'
import { extractSelectOptions } from '../cells/fieldOps'
import { usePendingChanges } from '../useGridData'
import { mixColor } from '@/theme/themeMix'
import { WEIGHT } from '@/theme/tokens'

// ── 配色与密度 ────────────────────────────────────────

/** 轴头竖条色板 —— antd 官方预设主色（daybreak 系），按索引循环；不与主题变量绑定（语义为数据分类着色，同 tagColors 策略） */
const AXIS_COLORS: readonly string[] = [
  '#1677ff', // blue
  '#52c41a', // green
  '#fa8c16', // orange
  '#722ed1', // purple
  '#13c2c2', // cyan
  '#eb2f96', // magenta
  '#faad14', // gold
  '#2f54eb', // geekblue
]

const axisColor = (index: number): string => AXIS_COLORS[index % AXIS_COLORS.length]

// 配色对齐其他视图（参考甘特/看板表头与甘特分组 `${color}15` 透明色模式）：
// - 轴区结构底色用中性 var(--cn-bg-subtle)，边框回归普通 1px var(--cn-border)
// - 列方向区分：每列（列头 + 数据格）按列索引取 8 色板色相的透明淡染；列头 sticky 需不透明，
//   用 color-mix 混入 bg-subtle；数据格非 sticky，直接用 hex alpha 后缀。
//   浓度档位：甘特 `${color}15`（≈8%）是小面积行背景，整列长带需更高浓度才能区分相邻色相
//   （8% 下蓝/青、绿/青 ΔRGB<6 不可辨）——数据格 `hex26`（≈15%）、列头 20% 保持表头深一档
// - 行方向区分：行间 1px 细实线（数据格 borderBottom，行头 borderBottom 贯通）
const COL_HEADER_BG = (hex: string) => mixColor(hex, 20, 'var(--cn-bg-subtle)')
const CELL_BG = (hex: string) => `${hex}26`

/** 密度 → 单元格卡片间距/字号 */
function densityCardStyle(density: Density) {
  if (density === 'compact') {
    return { cellPadding: 6, cardPadding: '3px 8px', cardGap: 4, fontSize: 12 }
  }
  if (density === 'spacious') {
    return { cellPadding: 12, cardPadding: '7px 12px', cardGap: 10, fontSize: 15 }
  }
  return { cellPadding: 8, cardPadding: '5px 10px', cardGap: 6, fontSize: 13 }
}

// ── 组件 ──────────────────────────────────────────────

interface MatrixViewProps {
  rows: RowResponse[]
  fields: Field[]
  view?: View | null
  density: Density
  onRowClick?: (r: RowResponse) => void
  /** 评分矩阵（ADR 0136）需要的表上下文；缺省时保持原只读矩阵 */
  workspaceId?: string
  tableId?: string
  canEditRecords?: boolean
  /** 表配置了行级权限时矩阵只读，避免看不到已有行而重复建行 */
  rowRulesActive?: boolean
}

/** 单行单元格卡片：显示 title_field 格式化值，点击打开行详情 */
function MatrixCellCard({
  row,
  titleField,
  fields,
  fontSize,
  onClick,
}: {
  row: RowResponse
  titleField?: string
  fields: Field[]
  fontSize: number
  onClick?: (r: RowResponse) => void
}) {
  const fieldDef = titleField ? fields.find((f) => f.name === titleField) : undefined
  const text =
    (fieldDef && formatFieldDisplayValue(fieldDef, row[titleField!])) ||
    String(row.id ?? '')
  return (
    <Tooltip title={text} mouseEnterDelay={0.4}>
      <div
        data-testid="matrix-cell-card"
        onClick={() => onClick?.(row)}
        style={{
          padding: '5px 10px',
          fontSize,
          borderRadius: 6,
          background: 'var(--cn-bg-page)',
          border: '1px solid var(--cn-border)',
          cursor: onClick ? 'pointer' : 'default',
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
        }}
      >
        {text}
      </div>
    </Tooltip>
  )
}

/** 区域标题：左侧彩色竖条 + 加粗标题 + 数量徽章（纵轴行头 / 横轴列头复用） */
function MatrixAxisHeader({
  title,
  color,
  count,
  bold = true,
}: {
  title: string
  color: string
  count?: number
  bold?: boolean
}) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0 }}>
      <span aria-hidden style={{ flexShrink: 0, width: 4, height: 14, borderRadius: 2, background: color }} />
      <span style={{ fontWeight: bold ? WEIGHT.semibold : WEIGHT.medium, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
        {title}
      </span>
      {count !== undefined && (
        <span style={{ flexShrink: 0, fontSize: 11, color: 'var(--cn-text-secondary)' }}>{count}</span>
      )}
    </div>
  )
}

/** 左上角标注格轴标签：主题色「行 / 列」徽章 + 加粗字段名 */
function MatrixCornerAxis({ axis, name }: { axis: '行' | '列'; name: string }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6, minWidth: 0 }}>
      <span
        style={{
          flexShrink: 0, fontSize: 11, fontWeight: WEIGHT.semibold, lineHeight: '18px',
          padding: '0 6px', borderRadius: 4,
          color: 'var(--cn-brand-color)',
          background: 'var(--cn-mix-brand-color-12-bg-container)',
        }}
      >
        {axis}
      </span>
      <span
        style={{
          fontSize: 12.5, fontWeight: WEIGHT.semibold, color: 'var(--cn-text-primary)',
          overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
        }}
      >
        {name}
      </span>
    </div>
  )
}

/** 月份字符串的次月（`2026-12` → `2027-01`），用于 [当月1日, 次月1日) 过滤 */
function nextMonth(month: string): string {
  const [y, m] = month.split('-').map(Number)
  if (!y || !m) return month
  return m === 12 ? `${y + 1}-01` : `${y}-${String(m + 1).padStart(2, '0')}`
}

export default function MatrixView({
  rows,
  fields,
  view,
  density,
  onRowClick,
  workspaceId,
  tableId,
  canEditRecords = false,
  rowRulesActive = false,
}: MatrixViewProps) {
  const { message } = AntApp.useApp()
  const queryClient = useQueryClient()
  const opts = useMemo(
    () => resolveOpts(view?.view_options as Record<string, unknown> | undefined, MATRIX_OPTIONS),
    [view?.view_options],
  )
  const rowField = (opts.row_field as string) || ''
  const columnField = (opts.column_field as string) || ''
  const granularity = (opts.date_granularity as MatrixDateGranularity) || 'month'
  const titleField = (opts.title_field as string) || undefined
  const valueField = (opts.value_field as string) || ''
  const periodStart = (opts.period_start as string) || ''
  const periodEnd = (opts.period_end as string) || ''
  const style = densityCardStyle(density)

  const scoreMode = !!(rowField && columnField && valueField && periodStart && periodEnd)
  const baseEditable = !!(scoreMode && workspaceId && tableId && canEditRecords && !rowRulesActive)

  // 可编辑矩阵的 options 必须用全量（表详情默认截断 options，ADR 0046 D6）
  const { data: fullFields } = useQuery({
    queryKey: ['fields-full', workspaceId, tableId],
    queryFn: () => fieldApi.list(workspaceId!, tableId!, false, true),
    enabled: scoreMode && !!workspaceId && !!tableId,
    staleTime: 60_000,
  })
  const matrixFields = scoreMode ? (fullFields ?? fields) : fields
  const rowDef = matrixFields.find((f) => f.name === rowField)
  const colDef = matrixFields.find((f) => f.name === columnField)

  const rowOptions = useMemo(
    () => (scoreMode && rowDef?.field_type === 'select' ? extractSelectOptions(rowDef.config) : []),
    [scoreMode, rowDef],
  )
  const monthKeys = useMemo(
    () => (scoreMode ? buildMonthKeys(periodStart, periodEnd) : []),
    [scoreMode, periodStart, periodEnd],
  )
  const rowLabelByValue = useMemo(
    () => new Map(rowOptions.map((o) => [String(o.value), o.label])),
    [rowOptions],
  )
  const scoreReady = scoreMode && rowOptions.length > 0 && monthKeys.length > 0

  const scoreQueryKey = useMemo(
    () => [
      'matrix-scores',
      workspaceId,
      tableId,
      rowField,
      columnField,
      valueField,
      periodStart,
      periodEnd,
      rowOptions.map((o) => o.value).join('\u0000'),
    ],
    [workspaceId, tableId, rowField, columnField, valueField, periodStart, periodEnd, rowOptions],
  )
  const { data: scoreData, isFetching: scoreFetching } = useQuery<RowListResponse>({
    queryKey: scoreQueryKey,
    queryFn: () =>
      recordApi.list(workspaceId!, tableId!, {
        limit: 5000,
        // 操作符必须是后端 query.parse 支持的符号形式（>= / <）；写成 gte / lt 会被判「未知操作符」返回 400，
        // 表现为评分单元格永远加载不到已有数据（录入后刷新丢值）。
        filters: [
          { field_name: columnField, op: '>=', value: `${periodStart}-01` },
          { field_name: columnField, op: '<', value: `${nextMonth(periodEnd)}-01` },
          { field_name: rowField, op: 'in', value: rowOptions.map((o) => o.value) },
        ],
      }),
    // 评分矩阵不套视图筛选 / 搜索：否则未加载的已有行会被当成空单元格，保存时重复建行
    enabled: scoreReady && !!workspaceId && !!tableId,
    staleTime: 10_000,
  })
  const { data: pendingChanges } = usePendingChanges(workspaceId, tableId, baseEditable)

  const [drafts, setDrafts] = useState<Record<string, number | null>>({})
  const [saving, setSaving] = useState<Record<string, boolean>>({})

  const grid = useMemo(
    () => buildMatrixGrid(rows, fields, rowField, columnField, granularity),
    [rows, fields, rowField, columnField, granularity],
  )
  const scoreRows = useMemo(() => scoreData?.items ?? [], [scoreData])
  const scoreGrid = useMemo(
    () => buildScoreMatrixGrid(scoreRows, rowField, columnField, valueField, rowOptions.map((o) => o.value), monthKeys),
    [scoreRows, rowField, columnField, valueField, rowOptions, monthKeys],
  )

  const clearDraft = (key: string) => {
    setDrafts((prev) => {
      if (!(key in prev)) return prev
      const next = { ...prev }
      delete next[key]
      return next
    })
  }

  const saveCell = (rowKey: string, colKey: string, cell: { rowId: number | null; value: number | null } | undefined) => {
    const key = cellKey(rowKey, colKey)
    if (!(key in drafts) || !workspaceId || !tableId) return
    const next = drafts[key]
    const previous = cell?.value ?? null
    if (next === previous) {
      clearDraft(key)
      return
    }
    setSaving((prev) => ({ ...prev, [key]: true }))
    recordApi
      .matrixUpsert(workspaceId, tableId, {
        row_field: rowField,
        row_value: rowKey,
        month_field: columnField,
        month: colKey,
        value_field: valueField,
        value: next,
      })
      .then((res) => {
        if (res.action === 'change_request') {
          message.info('已提交修改申请，审批通过后生效')
        } else {
          message.success('已保存')
        }
        const savedRow = res.row
        if (savedRow) {
          queryClient.setQueryData<RowListResponse>(scoreQueryKey, (old) => {
            if (!old) return old
            const exists = old.items.some((r) => String(r.id) === String(savedRow.id))
            return {
              ...old,
              items: exists ? old.items.map((r) => (String(r.id) === String(savedRow.id) ? savedRow : r)) : [...old.items, savedRow],
              total: old.total + (exists ? 0 : 1),
            }
          })
        }
        void queryClient.invalidateQueries({ queryKey: scoreQueryKey })
        void queryClient.invalidateQueries({ queryKey: ['table-records', `${workspaceId}/${tableId}`] })
        void queryClient.invalidateQueries({ queryKey: ['pending-changes', `${workspaceId}/${tableId}`] })
        clearDraft(key)
      })
      .catch((err) => {
        message.error(err instanceof Error ? err.message : '评分保存失败')
        clearDraft(key)
      })
      .finally(() => {
        setSaving((prev) => {
          if (!(key in prev)) return prev
          const nextSaving = { ...prev }
          delete nextSaving[key]
          return nextSaving
        })
      })
  }

  // 未配置轴字段 → 引导空态（后端校验挡新视图，这里兜底历史数据）
  if (!rowField || !columnField) {
    return (
      <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <Empty description="矩阵视图需配置行分组字段与列分组字段（视图设置）" />
      </div>
    )
  }

  // ── 评分矩阵（ADR 0136）──
  if (scoreMode) {
    if (!scoreReady) {
      return (
        <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <Empty
            description={
              rowOptions.length === 0
                ? '评分矩阵的行字段没有固定选项，请先在字段设置中维护对象清单'
                : '评分矩阵需配置有效的起止月份（视图设置）'
            }
          />
        </div>
      )
    }
    if (scoreFetching && !scoreData) {
      return (
        <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <Spin tip="加载评分数据…" />
        </div>
      )
    }

    const editable = baseEditable
    const gridTemplateColumns = `minmax(150px, 200px) repeat(${scoreGrid.columnKeys.length}, minmax(110px, 1fr))`
    return (
      <div
        data-testid="matrix-score-view"
        style={{
          flex: 1, minHeight: 0, overflow: 'auto',
          background: 'var(--cn-bg-container)', border: '1px solid var(--cn-border)', borderRadius: 8,
        }}
      >
        {!editable && (
          <div
            data-testid="matrix-score-readonly-hint"
            style={{ padding: '6px 12px', borderBottom: '1px solid var(--cn-border)', fontSize: 12, color: 'var(--cn-text-secondary)' }}
          >
            {rowRulesActive ? '该表配置了行级权限，评分矩阵为只读' : '当前账号无编辑权限，评分矩阵为只读'}
          </div>
        )}
        <div style={{ display: 'grid', gridTemplateColumns, minWidth: 'min-content' }}>
          <div
            style={{
              position: 'sticky', left: 0, top: 0, zIndex: 3,
              background: 'var(--cn-bg-subtle)',
              borderBottom: '1px solid var(--cn-border)', borderRight: '1px solid var(--cn-border)',
              padding: '10px 12px',
              display: 'flex', flexDirection: 'column', justifyContent: 'center', gap: 5,
            }}
          >
            <MatrixCornerAxis axis="行" name={rowDef?.name ?? rowField} />
            <MatrixCornerAxis axis="列" name={colDef?.name ?? columnField} />
          </div>

          {scoreGrid.columnKeys.map((ck, ci) => (
            <div
              key={ck}
              data-testid="matrix-score-col-header"
              style={{
                position: 'sticky', top: 0, zIndex: 2,
                background: COL_HEADER_BG(axisColor(ci)), borderBottom: '1px solid var(--cn-border)',
                padding: '8px 10px',
              }}
            >
              <MatrixAxisHeader title={ck} color={axisColor(ci)} />
            </div>
          ))}


          {scoreGrid.rowKeys.map((rk, ri) => (
            <div key={rk} style={{ display: 'contents' }}>
              <div
                data-testid="matrix-score-row-header"
                style={{
                  position: 'sticky', left: 0, zIndex: 1,
                  background: 'var(--cn-bg-subtle)',
                  borderRight: '1px solid var(--cn-border)', borderBottom: '1px solid var(--cn-border)',
                  padding: '10px 10px',
                  display: 'flex', alignItems: 'center',
                }}
              >
                <MatrixAxisHeader title={rowLabelByValue.get(rk) ?? rk} color={axisColor(ri)} />
              </div>
              {scoreGrid.columnKeys.map((ck, ci) => {
                const key = cellKey(rk, ck)
                const cell = scoreGrid.cells.get(key)
                const duplicate = (cell?.duplicateCount ?? 0) > 1
                const displayed = key in drafts ? drafts[key] : cell?.value ?? null
                const isSaving = !!saving[key]
                const hasPending = cell?.rowId != null && (pendingChanges?.has(String(cell.rowId)) ?? false)
                return (
                  <div
                    key={key}
                    data-testid="matrix-score-cell"
                    style={{
                      padding: style.cellPadding,
                      borderBottom: '1px solid var(--cn-border)',
                      background: CELL_BG(axisColor(ci)),
                      minHeight: 36,
                      display: 'flex', alignItems: 'center', gap: 4,
                    }}
                  >
                    {duplicate ? (
                      <Tooltip title={`该对象在 ${ck} 存在 ${cell?.duplicateCount} 行重复记录，请在表格视图清理后再录入`}>
                        <span style={{ fontSize: 12, color: 'var(--cn-status-danger)' }}>重复 {cell?.duplicateCount} 行</span>
                      </Tooltip>
                    ) : editable ? (
                      <>
                        <InputNumber
                          size="small"
                          style={{ width: '100%' }}
                          value={displayed}
                          disabled={isSaving}
                          onChange={(v) => {
                            setDrafts((prev) => ({ ...prev, [key]: v === null || v === undefined ? null : Number(v) }))
                          }}
                          onBlur={() => saveCell(rk, ck, cell)}
                          // rc-input-number 把 onPressEnter 挂在根 div 上，currentTarget 是外层容器，
                          // 直接 blur() 不会让输入框失焦，下面的 onBlur 保存链路也就永不触发（回车录入无效）。
                          onPressEnter={(e) => e.currentTarget.querySelector('input')?.blur()}
                          onKeyDown={(e) => {
                            if (e.key === 'Escape') clearDraft(key)
                          }}
                        />
                        {isSaving && <Spin size="small" />}
                        {hasPending && (
                          <Tooltip title="该行有待审批的修改申请">
                            <span style={{ fontSize: 11, color: 'var(--cn-status-warning)' }}>待审批</span>
                          </Tooltip>
                        )}
                      </>
                    ) : (
                      <span style={{ fontSize: style.fontSize, color: displayed === null ? 'var(--cn-text-muted)' : 'var(--cn-text-primary)' }}>
                        {displayed === null ? '—' : displayed}
                      </span>
                    )}
                  </div>
                )
              })}
            </div>
          ))}
        </div>
      </div>
    )
  }

  // ── 原只读矩阵 ──
  // 无数据 → 引导空态（与看板语义一致）
  if (!rows.length) {
    return (
      <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <Empty description="这张表还没有数据，新增行后即可在矩阵中排布" />
      </div>
    )
  }

  // 行内总计数（行头徽章）；列内总计数（列头徽章）
  const rowTotals = new Map<string, number>()
  const colTotals = new Map<string, number>()
  for (const rk of grid.rowKeys) rowTotals.set(rk, 0)
  for (const ck of grid.columnKeys) colTotals.set(ck, 0)
  for (const [key, list] of grid.cells) {
    const [rk, ck] = key.split('::')
    rowTotals.set(rk, (rowTotals.get(rk) ?? 0) + list.length)
    colTotals.set(ck, (colTotals.get(ck) ?? 0) + list.length)
  }

  const gridTemplateColumns = `minmax(150px, 200px) repeat(${grid.columnKeys.length}, minmax(150px, 1fr))`

  return (
    <div
      data-testid="matrix-view"
      style={{
        flex: 1, minHeight: 0, overflow: 'auto',
        background: 'var(--cn-bg-container)', border: '1px solid var(--cn-border)', borderRadius: 8,
      }}
    >
      <div style={{ display: 'grid', gridTemplateColumns, minWidth: 'min-content' }}>
        {/* 左上角标注格：纵轴 / 横轴（中性底，对齐其他视图表头） */}
        <div
          data-testid="matrix-corner"
          style={{
            position: 'sticky', left: 0, top: 0, zIndex: 3,
            background: 'var(--cn-bg-subtle)',
            borderBottom: '1px solid var(--cn-border)', borderRight: '1px solid var(--cn-border)',
            padding: '10px 12px',
            display: 'flex', flexDirection: 'column', justifyContent: 'center', gap: 5,
          }}
        >
          <MatrixCornerAxis axis="行" name={rowDef?.name ?? rowField} />
          <MatrixCornerAxis axis="列" name={colDef?.name ?? columnField} />
        </div>

        {/* 横轴列头行 */}
        {grid.columnKeys.map((ck, ci) => (
          <div
            key={ck}
            data-testid="matrix-col-header"
            style={{
              position: 'sticky', top: 0, zIndex: 2,
              background: COL_HEADER_BG(axisColor(ci)), borderBottom: '1px solid var(--cn-border)',
              padding: '8px 10px',
            }}
          >
            <MatrixAxisHeader
              title={bucketTitle(ck, granularity)}
              color={axisColor(ci)}
              count={colTotals.get(ck)}
            />
          </div>
        ))}

        {/* 纵轴行 + 单元格网格 */}
        {grid.rowKeys.map((rk, ri) => (
          <div key={rk} style={{ display: 'contents' }}>
            <div
              data-testid="matrix-row-header"
              style={{
                position: 'sticky', left: 0, zIndex: 1,
                background: 'var(--cn-bg-subtle)',
                borderRight: '1px solid var(--cn-border)', borderBottom: '1px solid var(--cn-border)',
                padding: '10px 10px',
                display: 'flex', alignItems: 'center',
              }}
            >
              <MatrixAxisHeader title={rk} color={axisColor(ri)} count={rowTotals.get(rk)} />
            </div>
            {grid.columnKeys.map((ck, ci) => {
              const list = grid.cells.get(cellKey(rk, ck))
              return (
                <div
                  key={`${rk}::${ck}`}
                  data-testid="matrix-cell"
                  style={{
                    padding: style.cellPadding,
                    borderBottom: '1px solid var(--cn-border)',
                    display: 'flex', flexDirection: 'column', gap: style.cardGap,
                    // 列色相透明淡染贯通列头与数据格（空格同色，列带连贯）
                    background: CELL_BG(axisColor(ci)),
                  }}
                >
                  {(list ?? []).map((r) => (
                    <MatrixCellCard
                      key={String(r.id)}
                      row={r}
                      titleField={titleField}
                      fields={fields}
                      fontSize={style.fontSize}
                      onClick={onRowClick}
                    />
                  ))}
                </div>
              )
            })}
          </div>
        ))}
      </div>
    </div>
  )
}
