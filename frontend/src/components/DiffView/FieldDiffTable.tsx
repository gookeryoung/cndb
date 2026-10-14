/**
 * 数据表变更项的字段级差异表格。
 *
 * 三种变更按同一视觉语言渲染：
 * - `create`：字段 → 新增值（绿色 +）；
 * - `delete`：字段 → 删除前原值（红色 −，整行快照）；
 * - `update`：字段 / 修改前 / 修改后 三列；存在基准漂移时追加「当前值」列，
 *   并在字段名旁以红 Tag + Tooltip 提示行内已变更的值。
 *
 * 与导入预览（ImportDiffTable）保持一致的「红 − / 绿 +」配色，避免同类信息两套视觉。
 */

import { Tag, Tooltip, Typography } from 'antd'

import type { ChangeItemDetail } from '@/api'

const { Text } = Typography

/** 任意 JSON 值的紧凑展示（diff 单元格用）；空值统一显示为「空」，避免出现空白单元格 */
export function formatValue(v: unknown): string {
  if (v === null || v === undefined || v === '') return '空'
  if (typeof v === 'object') return JSON.stringify(v)
  return String(v)
}

/** update 项的 diff 字段清单：基准与新值的键并集 */
export function diffFields(item: ChangeItemDetail): string[] {
  return Array.from(new Set([...Object.keys(item.base_values), ...Object.keys(item.values)]))
}

/** 表格行模型：before / after 为 null 表示该侧不适用（新增无 before、删除无 after） */
interface FieldRow {
  field: string
  before: string | null
  after: string | null
  current: string
  conflict: boolean
}

function buildRows(item: ChangeItemDetail): FieldRow[] {
  if (item.op === 'create') {
    return Object.entries(item.values).map(([field, value]) => ({
      field,
      before: null,
      after: formatValue(value),
      current: '',
      conflict: false,
    }))
  }
  if (item.op === 'delete') {
    return Object.entries(item.base_values).map(([field, value]) => ({
      field,
      before: formatValue(value),
      after: null,
      current: '',
      conflict: false,
    }))
  }
  return diffFields(item).map((field) => ({
    field,
    before: formatValue(item.base_values[field]),
    after: formatValue(item.values[field]),
    current: formatValue(item.current_values[field]),
    conflict: item.field_conflicts.includes(field),
  }))
}

/** 值为空时用静音斜体，避免「空」与真实文本混淆 */
function valueClass(base: string, value: string | null): string {
  return value === '空' ? `${base} cn-fielddiff-empty` : base
}

export default function FieldDiffTable({ item }: { item: ChangeItemDetail }) {
  const rows = buildRows(item)
  const hasConflict = rows.some((r) => r.conflict)

  if (rows.length === 0) {
    return <Text type="secondary">（无字段变更）</Text>
  }

  return (
    <div className="cn-fielddiff-wrap">
      {item.op === 'delete' && (
        <div className="cn-fielddiff-note">
          <Text type="secondary">整行删除：以下为该行删除前的字段快照</Text>
        </div>
      )}
      <table className="cn-fielddiff">
        <thead>
          <tr>
            <th className="cn-fielddiff-col-field">字段</th>
            {item.op === 'update' ? (
              <>
                <th>修改前</th>
                <th>修改后</th>
                {hasConflict && <th>当前值（行内已变更）</th>}
              </>
            ) : (
              <th>{item.op === 'create' ? '新增值' : '原值'}</th>
            )}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.field}>
              <td className="cn-fielddiff-col-field">
                <span className="cn-fielddiff-field">{row.field}</span>
                {row.conflict && (
                  <Tooltip title={`当前行该字段已变为：${row.current}，合并将覆盖为申请值`}>
                    <Tag color="red" className="cn-fielddiff-conflict">
                      基准已漂移
                    </Tag>
                  </Tooltip>
                )}
              </td>
              {item.op === 'update' ? (
                <>
                  <td>
                    <span className={valueClass('cn-fielddiff-before', row.before)}>{row.before}</span>
                  </td>
                  <td>
                    <span className={valueClass('cn-fielddiff-after', row.after)}>{row.after}</span>
                  </td>
                  {hasConflict && (
                    <td>
                      {row.conflict ? (
                        <span className="cn-fielddiff-current">{row.current}</span>
                      ) : (
                        <span className="cn-fielddiff-empty">—</span>
                      )}
                    </td>
                  )}
                </>
              ) : (
                <td>
                  <span className={item.op === 'create' ? 'cn-fielddiff-sign-add' : 'cn-fielddiff-sign-del'}>
                    {item.op === 'create' ? '+' : '−'}
                  </span>
                  <span
                    className={
                      item.op === 'create'
                        ? valueClass('cn-fielddiff-after', row.after)
                        : `${valueClass('cn-fielddiff-before', row.before)} cn-fielddiff-strike`
                    }
                  >
                    {item.op === 'create' ? row.after : row.before}
                  </span>
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
