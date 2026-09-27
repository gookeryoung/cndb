/** 矩阵视图组件 — 二维分类网格：纵轴 × 横轴，单元格填入同时符合两类别的行卡片.
 *
 * 视觉采用「左侧彩色竖条 + 区域标题加粗」组合模式：
 * - 纵轴行头与横轴列头复用 MatrixAxisHeader —— 4px 圆角彩色竖条 + 加粗标题 + 数量徽章；
 *   竖条颜色按索引从 antd v5 官方预设主色循环取色（行列各算一组）。
 * - 轴区（角格 + 行头列 + 列头行）纵横双色淡染（color-mix 混入 bg-page，不透明）：
 *   纵轴复用 --cn-brand-color、横轴用 --cn-axis-col-color，角格 16% 上下双色分段、行列头 12% 各随其轴，
 *   与数据区（container 白底 / 空格 page 弱底）形成明确对比；轴区分界线为轴色 25% 混入边框色；
 *   「未分组」兜底桶用轴色 35% 虚线边界，数据列间另加中性淡竖线。
 * - 左上角标注格展示「纵轴/横轴」主题色徽章 + 加粗字段名。
 * - 布局为 CSS Grid：首列行头 sticky left、首行列头 sticky top，左上角标注格双向 sticky；
 *   网格区域独立滚动，行头/列头在滚动时保持可见。
 * - 单元格高度随内容自适应（无硬上限），行轨道高度由该行最高单元格决定。
 *
 * view_options 契约见 .trae/designs/matrix-view.md：
 * - row_field（必填）/ column_field（必填）/ date_granularity（默认 month）/ title_field（可选）
 */

import { useMemo } from 'react'
import { Empty, Tooltip } from 'antd'
import type { RowResponse, Field, View } from '@/api'
import type { Density } from '@/theme/tableSettings'
import { resolveOpts, MATRIX_OPTIONS } from '../view-config/viewOptionSchema'
import { formatFieldDisplayValue } from '../cells/fieldValueFormat'
import {
  buildMatrixGrid,
  bucketTitle,
  cellKey,
  UNGROUPED_LABEL,
  type MatrixDateGranularity,
} from './matrixBoard'

// ── 配色与密度 ────────────────────────────────────────

/** 轴头竖条色板 —— antd v5 官方预设主色（daybreak 系），按索引循环；不与主题变量绑定（语义为数据分类着色，同 tagColors 策略） */
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

// 轴区双色契约：纵轴复用品牌色，横轴用独立轴色 --cn-axis-col-color（index.css 每主题定义）；
// 淡染底不透明（color-mix 混入 bg-page）保证 sticky 滚动不透底；层次自角向外衰减
// （角格 16%、行列头 12%、数据区 0——档位须高于感知阈值，4% 级别色差 ΔRGB<5 视觉不可辨）
const ROW_AXIS = 'var(--cn-brand-color)'
const COL_AXIS = 'var(--cn-axis-col-color)'
// 轴色低比例混入页面底色 → 淡染底
const axisTint = (axis: string, pct: number) =>
  `color-mix(in srgb, ${axis} ${pct}%, var(--cn-bg-page))`
// 轴色低比例混入边框色 → 轴区分界线（与淡染同色相，随所在轴着色）
const axisZoneBorder = (axis: string) =>
  `color-mix(in srgb, ${axis} 25%, var(--cn-border))`
// 轴色中比例混入边框色 → 「未分组」兜底桶虚线边界
const axisBucketDash = (axis: string) =>
  `color-mix(in srgb, ${axis} 35%, var(--cn-border))`
// 数据列间淡竖线（非轴结构，中性极淡）
const COL_SEP = 'color-mix(in srgb, var(--cn-text) 7%, transparent)'

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
  const primaryField = fields.find((f) => f.is_primary)
  const text =
    (fieldDef && formatFieldDisplayValue(fieldDef, row[titleField!])) ||
    (primaryField && formatFieldDisplayValue(primaryField, row[primaryField.name])) ||
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
      <span style={{ fontWeight: bold ? 600 : 500, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
        {title}
      </span>
      {count !== undefined && (
        <span style={{ flexShrink: 0, fontSize: 11, color: 'var(--cn-text-secondary)' }}>{count}</span>
      )}
    </div>
  )
}

/** 左上角标注格轴标签：主题色「纵轴/横轴」徽章 + 加粗字段名 */
function MatrixCornerAxis({ axis, name }: { axis: '纵轴' | '横轴'; name: string }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6, minWidth: 0 }}>
      <span
        style={{
          flexShrink: 0, fontSize: 11, fontWeight: 600, lineHeight: '18px',
          padding: '0 6px', borderRadius: 4,
          color: 'var(--cn-brand-color)',
          background: 'color-mix(in srgb, var(--cn-brand-color) 12%, var(--cn-bg-container))',
        }}
      >
        {axis}
      </span>
      <span
        style={{
          fontSize: 12.5, fontWeight: 600, color: 'var(--cn-text-primary)',
          overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
        }}
      >
        {name}
      </span>
    </div>
  )
}

export default function MatrixView({ rows, fields, view, density, onRowClick }: MatrixViewProps) {
  const opts = useMemo(
    () => resolveOpts(view?.view_options as Record<string, unknown> | undefined, MATRIX_OPTIONS),
    [view?.view_options],
  )
  const rowField = (opts.row_field as string) || ''
  const columnField = (opts.column_field as string) || ''
  const granularity = (opts.date_granularity as MatrixDateGranularity) || 'month'
  const titleField = (opts.title_field as string) || undefined
  const style = densityCardStyle(density)

  const grid = useMemo(
    () => buildMatrixGrid(rows, fields, rowField, columnField, granularity),
    [rows, fields, rowField, columnField, granularity],
  )

  // 未配置轴字段 → 引导空态（后端校验挡新视图，这里兜底历史数据）
  if (!rowField || !columnField) {
    return (
      <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <Empty description="矩阵视图需配置纵轴字段与横轴字段（视图设置）" />
      </div>
    )
  }

  // 无数据 → 引导空态（与看板语义一致）
  if (!rows.length) {
    return (
      <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <Empty description="这张表还没有数据，新增行后即可在矩阵中排布" />
      </div>
    )
  }

  const rowDef = fields.find((f) => f.name === rowField)
  const colDef = fields.find((f) => f.name === columnField)

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
        {/* 左上角标注格：纵轴 / 横轴（上下双色分段，各随其轴） */}
        <div
          data-testid="matrix-corner"
          style={{
            position: 'sticky', left: 0, top: 0, zIndex: 3,
            backgroundImage: `linear-gradient(to bottom, ${axisTint(ROW_AXIS, 16)} 0 50%, ${axisTint(COL_AXIS, 16)} 50% 100%)`,
            borderBottom: `1px solid ${axisZoneBorder(COL_AXIS)}`, borderRight: `1px solid ${axisZoneBorder(ROW_AXIS)}`,
            padding: '10px 12px',
            display: 'flex', flexDirection: 'column', justifyContent: 'center', gap: 5,
          }}
        >
          <MatrixCornerAxis axis="纵轴" name={rowDef?.name ?? rowField} />
          <MatrixCornerAxis axis="横轴" name={colDef?.name ?? columnField} />
        </div>

        {/* 横轴列头行 */}
        {grid.columnKeys.map((ck, ci) => (
          <div
            key={ck}
            data-testid="matrix-col-header"
            style={{
              position: 'sticky', top: 0, zIndex: 2,
              background: axisTint(COL_AXIS, 12), borderBottom: `1px solid ${axisZoneBorder(COL_AXIS)}`,
              borderLeft: ck === UNGROUPED_LABEL ? `1px dashed ${axisBucketDash(COL_AXIS)}` : undefined,
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
                background: axisTint(ROW_AXIS, 12), borderRight: `1px solid ${axisZoneBorder(ROW_AXIS)}`,
                borderTop: rk === UNGROUPED_LABEL ? `1px dashed ${axisBucketDash(ROW_AXIS)}` : undefined,
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
                    // 列间淡竖线（首列由行头右缘分界线覆盖）；「未分组」列虚线；「未分组」行上缘虚线
                    borderLeft: ci === 0
                      ? undefined
                      : ck === UNGROUPED_LABEL
                        ? `1px dashed ${axisBucketDash(COL_AXIS)}`
                        : `1px solid ${COL_SEP}`,
                    borderTop: rk === UNGROUPED_LABEL ? `1px dashed ${axisBucketDash(ROW_AXIS)}` : undefined,
                    display: 'flex', flexDirection: 'column', gap: style.cardGap,
                    // 数据区显式 container 白底与轴区淡染对比；空单元格中性弱底
                    background: list?.length ? 'var(--cn-bg-container)' : 'var(--cn-bg-page)',
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
