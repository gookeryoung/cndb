/** Grid 列构建函数 — 根据 fields 和 view 状态生成 AntD Table ColumnsType. */

import { Space, Tooltip } from 'antd'
import { Button } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { FilterOutlined, SortAscendingOutlined, SortDescendingOutlined, SaveOutlined, CloseOutlined, EditOutlined, LinkOutlined, KeyOutlined, BulbOutlined } from '@ant-design/icons'
import type { ReactNode, CSSProperties } from 'react'
import type { RowResponse, Field, RowValues, ID } from '@/api'
import GridCell from './GridCell'
import ColumnFilterDropdown from '../layout/ColumnFilterDropdown'

/** 表头状态标识配色（与 FIELD_TYPE_META 色系对齐、避免冲突） */
const HEADER_FLAG = {
  required: '#ff4d4f',   // 必填 — 红（antd error）
  unique: '#fa8c16',     // 唯一 — 金橙
  link: '#eb2f96',       // 关联 — 品红（与 FIELD_TYPE_META.link.color=magenta 对齐）
  lookup: '#722ed1',     // 引用 — 紫（区别于 link）
} as const

/** 行内编辑（新增行/整行编辑）注入单元格所需的能力 */
export interface InlineEditCellProps {
  editing: boolean
  /** 当前行各字段的草稿值（key 为字段名） */
  values: RowValues
  onFieldChange: (fieldName: string, value: unknown) => void
  /** 单元格回车提交（行级编辑通常为 noop，由行操作列统一保存） */
  onFieldCommit: (fieldName: string) => void
  onFieldCancel: () => void
  /** 自动填充锁定时，预填字段名集合 —— 这些字段在受控编辑态下只读 */
  lockedFields?: Set<string>
}

/** 字段类型 → 基础列宽（px）。未命中类型回退 DEFAULT_COLUMN_WIDTH */
const TYPE_BASE_WIDTH: Record<string, number> = {
  longtext: 240,
  text: 180,
  link: 180,
  lookup: 180,
  multiselect: 190,
  select: 150,
  number: 130,
  decimal: 140,
  float: 140,
  percentage: 130,
  date: 140,
  datetime: 180,
  timestamp: 180,
  boolean: 110,
}

const DEFAULT_COLUMN_WIDTH = 160
/** 列宽拖拽约束（与 GridTableSection resize 手柄共用语义） */
export const MIN_COLUMN_WIDTH = 60
export const MAX_COLUMN_WIDTH = 600

/** 按字段类型估算默认列宽.
 *
 * 规则：TYPE_BASE_WIDTH 命中取基础宽度，否则 160；
 * 表头字符数修正 —— 超过 4 字每字 +14px，最多 +60px（保证长字段名完整可读）。
 */
export function estimateColumnWidth(field: Pick<Field, 'name' | 'field_type'>): number {
  const base = TYPE_BASE_WIDTH[field.field_type] ?? DEFAULT_COLUMN_WIDTH
  const overflow = Math.max(0, field.name.length - 4)
  return base + Math.min(overflow * 14, 60)
}

/** 视图级列序与列宽覆盖 */
export interface ColumnOptions {
  /** key 为字段 id 字符串的视图级宽度覆盖 */
  columnWidths?: Record<string, number>
  /** 视图级列序（字段 id 字符串数组）；缺项按 Field.order 追加归位 */
  fieldOrder?: string[]
  /** 拖宽结束时回调（宽度已夹取到 [MIN, MAX]） */
  onColumnResize?: (fieldId: string, width: number) => void
  /** 拖拽列 A 落到列 B 时回调；目标为操作列时由 GridTableSection 屏蔽 */
  onColumnOrderMove?: (fieldId: string, targetFieldId: string) => void
}

/** 按视图级 field_order 重排字段顺序.
 *
 * fieldOrder 中存在且匹配的字段排前（保持数组顺序），其余字段按原有 Field.order 追加；
 * fieldOrder 里的未知 id 忽略。fieldOrder 缺省/为空时原样返回。
 */
export function applyFieldOrder(fields: Field[], fieldOrder: string[] | undefined): Field[] {
  if (!fieldOrder || fieldOrder.length === 0) return fields
  const byId = new Map(fields.map(f => [String(f.id), f]))
  const ordered: Field[] = []
  for (const id of fieldOrder) {
    const f = byId.get(id)
    if (f) {
      ordered.push(f)
      byId.delete(id)
    }
  }
  // 剩余未出现在 fieldOrder 的字段（新建字段）按 Field.order 追加
  ordered.push(...[...byId.values()].sort((a, b) => (a.order ?? 0) - (b.order ?? 0)))
  return ordered
}

/** 行内编辑操作列回调 —— 新增行 / 整行编辑共用的操作挂载点 */
export interface RowInlineOps {
  /** 为指定行返回行内编辑能力；null 表示该行普通展示 */
  getInlineEdit: (record: RowResponse) => InlineEditCellProps | null
  /** 进入该行的整行编辑态 */
  onEdit: (recordId: ID) => void
  /** 保存该行（新增行建立 / 整行编辑提交） */
  onSave: (recordId: ID) => void
  /** 取消该行编辑 / 放弃新增 */
  onCancel: (recordId: ID) => void
}

/** 视图级列宽覆盖读取：非法值（非有限数）返回 undefined 走估算宽度 */
function clampColumnWidth(raw: unknown): number | undefined {
  const n = Number(raw)
  if (!Number.isFinite(n)) return undefined
  return Math.min(Math.max(n, MIN_COLUMN_WIDTH), MAX_COLUMN_WIDTH)
}

/** 构建 Grid 列定义 */
export function buildColumns(
  fields: Field[],
  wid: number | string | undefined,
  viewSortings: Array<{ field_name: string; direction: 'asc' | 'desc' }>,
  viewFilters: Array<{ field_name: string; op: string; value?: unknown }>,
  onFilterApply: (fieldName: string, op: string, value: unknown) => void,
  onFilterReset: (fieldName: string) => void,
  onCellSave?: (rowId: number | string, fieldName: string, value: unknown) => Promise<unknown>,
  /** 可选：行内编辑能力（新增行/整行编辑）。提供后追加一个固定右侧的操作列 */
  inlineOps?: RowInlineOps,
  /** 可选：视图级列宽覆盖与列序（见 ColumnOptions） */
  options?: ColumnOptions,
): ColumnsType<RowResponse> {
  const cols: NonNullable<ColumnsType<RowResponse>>[number][] = applyFieldOrder(
    fields.filter(f => !f.hidden).sort((a, b) => (a.order ?? 0) - (b.order ?? 0)),
    options?.fieldOrder,
  )
    .map<NonNullable<ColumnsType<RowResponse>>[number]>(f => {
      const sortRule = viewSortings.find(s => s.field_name === f.name)
      // 所有有排序规则的列都受控 sortOrder，保证 AntD 内部状态与 viewSortings 同步
      // 这样任何排序列都能正确经历 ascend → descend → null 循环
      // 关键点：始终受控（null 表示无排序），避免受控/非受控切换导致 AntD 内部状态丢失
      const sortOrder: 'ascend' | 'descend' | null = sortRule
        ? (sortRule.direction === 'asc' ? 'ascend' : 'descend')
        : null
      // 表头图标：任何有排序规则的列都显示箭头（视觉提示）
      const hasSortIndicator = !!sortRule
      const filterRule = viewFilters.find(fr => fr.field_name === f.name)
      const currentFilter = filterRule
        ? { op: filterRule.op, value: filterRule.value }
        : undefined
      // 字段类型标识：link → 关联，lookup → 引用（配不同线型底边框）
      const isLinkField = f.field_type === 'link'
      const isLookupField = f.field_type === 'lookup'
      const nameBorderStyle: CSSProperties = isLookupField
        ? { borderBottom: `1px dashed ${HEADER_FLAG.lookup}` }
        : isLinkField
          ? { borderBottom: `1px solid ${HEADER_FLAG.link}` }
          : {}

      /** 生成带 Tooltip 的状态图标 —— 紧凑、11px 字号 */
      const flagIcon = (icon: ReactNode, tooltip: string, _color: string) => (
        <Tooltip title={tooltip}>
          <span style={{ display: 'inline-flex', alignItems: 'center' }} data-testid={`header-flag-${tooltip}`}>
            {icon}
          </span>
        </Tooltip>
      )

      return {
        key: String(f.id),
        title: (
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 3 }}>
            {/* 字段名 —— link 实线底、lookup 虚线底 */}
            <span style={nameBorderStyle}>{f.name}</span>

            {/* 必填 —— 红 * 号 */}
            {f.required && (
              <Tooltip title="必填">
                <span style={{ color: HEADER_FLAG.required, fontWeight: 600, lineHeight: 1 }} data-testid="header-flag-required">*</span>
              </Tooltip>
            )}

            {/* 唯一约束 —— 金橙 KeyOutlined */}
            {f.is_unique && flagIcon(
              <KeyOutlined style={{ fontSize: 11, color: HEADER_FLAG.unique }} />, '唯一', HEADER_FLAG.unique,
            )}

            {/* 关联字段 —— 品红 LinkOutlined */}
            {isLinkField && flagIcon(
              <LinkOutlined style={{ fontSize: 11, color: HEADER_FLAG.link }} />, '关联', HEADER_FLAG.link,
            )}

            {/* 引用字段 —— 紫 BulbOutlined（虚线底已施加到字段名） */}
            {isLookupField && flagIcon(
              <BulbOutlined style={{ fontSize: 11, color: HEADER_FLAG.lookup }} />, '引用', HEADER_FLAG.lookup,
            )}

            {/* 排序箭头 / 过滤图标 —— 保留原有逻辑 */}
            {hasSortIndicator && (
              sortRule!.direction === 'asc'
                ? <SortAscendingOutlined style={{ fontSize: 12, color: '#1677ff' }} />
                : <SortDescendingOutlined style={{ fontSize: 12, color: '#1677ff' }} />
            )}
            {currentFilter && (
              <FilterOutlined style={{ fontSize: 11, color: '#1677ff' }} />
            )}
          </span>
        ),
        dataIndex: f.name,
        ellipsis: true,
        // 视图级覆盖优先，否则按字段类型估算（拖拽 resize 期间的实时预览也走此受控 width）
        width: clampColumnWidth(options?.columnWidths?.[String(f.id)]) ?? estimateColumnWidth(f),
        sorter: true,
        sortOrder,
        filterDropdown: ({ confirm, clearFilters }) => (
          <ColumnFilterDropdown
            field={f}
            currentFilter={currentFilter}
            onApply={(op, value) => { onFilterApply(f.name, op, value); confirm?.() }}
            onReset={() => { onFilterReset(f.name); clearFilters?.(); confirm?.() }}
          />
        ),
        filterIcon: (filtered) => (
          <FilterOutlined style={{ color: filtered || currentFilter ? '#1677ff' : undefined }} />
        ),
        render: (v: unknown, record: RowResponse) => {
          // 行内编辑 override：优先渲染受控编辑态，非编辑行回退到普通 GridCell
          const inline = inlineOps?.getInlineEdit(record)
          if (inline) {
            const locked = inline.lockedFields?.has(f.name) ?? false
            return (
              <GridCell
                value={inline.values[f.name]}
                field={f}
                rowId={record.id}
                wid={wid}
                editing={inline.editing}
                onDraftChange={(val) => inline.onFieldChange(f.name, val)}
                onDraftCommit={inline.onFieldCommit}
                onDraftCancel={inline.onFieldCancel}
                showActionButtons={false}
                readOnly={locked}
              />
            )
          }
          return (
            <GridCell
              value={v}
              field={f}
              rowId={record.id}
              wid={wid}
              onSave={onCellSave ? (fieldName, value) => onCellSave(record.id, fieldName, value) : undefined}
            />
          )
        },
      }
    })

  // 行内编辑能力存在时追加操作列（编辑 / 保存 / 取消）
  if (inlineOps) {
    cols.push({
      key: '__row_ops__',
      width: 112,
      align: 'center',
      title: '',
      render: (_v: unknown, record: RowResponse) => {
        const inline = inlineOps.getInlineEdit(record)
        if (inline) {
          return (
            <Space size={4}>
              <Button size="small" type="primary" icon={<SaveOutlined />} data-testid="row-save-btn" onClick={() => inlineOps.onSave(record.id)}>保存</Button>
              <Tooltip title="取消编辑：恢复为修改前的内容（不会丢失其他行）">
                <Button size="small" icon={<CloseOutlined />} data-testid="row-cancel-btn" onClick={() => inlineOps.onCancel(record.id)} />
              </Tooltip>
            </Space>
          )
        }
        return (
          <Button size="small" icon={<EditOutlined />} data-testid="row-edit-btn" onClick={() => inlineOps.onEdit(record.id)}>编辑</Button>
        )
      },
    })
  }

  return cols
}