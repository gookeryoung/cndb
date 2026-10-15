/** Grid 单元格组件 — 展示态与编辑态的统一入口（支持 inline 编辑）.
 *
 * 取值归一化工具与两态渲染分别在 ./cellValueUtils、./DisplayCell、./EditCell；
 * 本模块保留历史导出面（finalizeCellValue / normalizeCellValueForEdit /
 * isBlankCellValue / isEditableInlineField）供 GridPage 直接复用。
 */

import { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Tooltip, App as AntApp } from 'antd'
import { LockOutlined } from '@ant-design/icons'
import type { Field } from '@/api'
import { isChangeRequestResponse } from '@/api'
import { EditCell } from './EditCell'
import { DisplayCell } from './DisplayCell'
import { finalizeValueFromEdit, isReadonlyField, normalizeValueForEdit } from './cellValueUtils'

// 历史导出面：GridPage 行内新增/整行编辑直接复用这些归一化工具
export {
  finalizeCellValue,
  isBlankCellValue,
  isEditableInlineField,
  normalizeCellValueForEdit,
} from './cellValueUtils'

interface Props {
  value: unknown
  field: Field
  rowId: number | string
  wid?: number | string
  /** 当前表 id：附件上传登记归属用 */
  tableId?: number | string
  /** 传统按单元格编辑：双击进入编辑态，回车/失焦调用该回调保存单个字段 */
  onSave?: (fieldName: string, value: unknown) => Promise<unknown>
  /** 稳定引用版行级保存回调（onSave 的替代）：GridCell 内部组合 rowId 调用，供 memo 生效 */
  onCellSave?: (rowId: number | string, fieldName: string, value: unknown) => Promise<unknown>
  /** 受控编辑模式：为 true 时强制渲染编辑态，value 作为受控草稿值，供"行内新增/整行编辑"复用 */
  editing?: boolean
  /** 受控模式下草稿变化回调 */
  onDraftChange?: (value: unknown) => void
  /** 受控模式下回车确认（行级编辑时通常为 noop，父级统一保存） */
  onDraftCommit?: (fieldName: string, value: unknown) => void
  /** 受控模式下取消 */
  onDraftCancel?: () => void
  /** 是否渲染单元格底部自带的"保存/取消"按钮（行级编辑时由行操作列统一承载，置 false） */
  showActionButtons?: boolean
  /** 受控模式下的只读字段标记 —— 自动填充锁定开启时，预填字段不允许修改 */
  readOnly?: boolean
  /** 编辑中锁定：该行处于编辑中状态，展示原值且双击不进入编辑 */
  locked?: boolean
}

/**
 * 可编辑单元格。
 * - 传统模式（无 editing prop）：双击切到编辑态，回车/失焦通过 onSave 保存单个字段。
 * - 受控模式（editing 为布尔值）：由父级把控编辑态与草稿值，value 即当前草稿。
 */
function GridCell({ value, field, rowId, wid, tableId, onSave, onCellSave, editing: controlledEditing, onDraftChange, onDraftCommit, onDraftCancel, showActionButtons, readOnly, locked }: Props) {
  const { message } = AntApp.useApp()
  // 稳定引用版回调：父级传 onCellSave 时在内部组合 rowId，避免每次渲染新建闭包破坏 memo
  const effectiveOnSave = useMemo(
    () => (onCellSave
      ? (fieldName: string, val: unknown) => onCellSave(rowId, fieldName, val)
      : onSave),
    [onCellSave, onSave, rowId],
  )
  // 说明：prop `editing`（受控模式）与内部 state `editing`（传统模式）同名，
  // 这里在解构时把 prop 重命名为 `controlledEditing`，内部 state 沿用 `editing` 变量名（传统模式）。
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState<unknown>(value)
  const [saving, setSaving] = useState(false)
  const inputRef = useRef<HTMLElement | null>(null)

  // 受控模式：编辑态与草稿值完全交由父级
  const controlled = typeof controlledEditing === 'boolean'
  // 受控模式下编辑态由 prop 决定，否则用内部 state
  const isEditing = controlled ? controlledEditing : editing

  // 外部 value 变化时同步 draft（仅传统模式用）
  useEffect(() => {
    if (!controlled) setDraft(value)
  }, [value, controlled])

  // 切到编辑态时自动聚焦。受控模式（行级新增/整行编辑）由父级统一聚焦第一个可编辑单元格，
  // 避免一行内多个 GridCell 同时进入编辑态时互相争抢焦点。
  useEffect(() => {
    if (controlled) return
    if (isEditing && inputRef.current) {
      const el = inputRef.current
      if ('focus' in el && typeof (el as HTMLElement).focus === 'function') {
        setTimeout(() => (el as HTMLElement).focus(), 30)
      }
    }
  }, [isEditing, controlled])

  const handleStartEdit = useCallback(() => {
    // 受控模式由父级把控首个焦点，无需在此处理
    if (controlled) return
    if (isReadonlyField(field)) return
    setDraft(normalizeValueForEdit(value, field))
    setEditing(true)
  }, [controlled, value, field])

  const handleSave = useCallback(async () => {
    if (!effectiveOnSave) { setEditing(false); return }
    setSaving(true)
    try {
      const finalize = finalizeValueFromEdit(draft, field)
      const res = await effectiveOnSave(field.name, finalize)
      setEditing(false)
      // 查看者/关闭直编时后端返回 202 修改申请载荷：值未落库，申请处理后生效
      message.success(isChangeRequestResponse(res) ? '已提交修改申请，处理后生效' : '已保存')
    } catch (err) {
      message.error(err instanceof Error ? err.message : '保存失败')
    } finally {
      setSaving(false)
    }
  }, [draft, field, effectiveOnSave, message])

  const handleCancel = useCallback(() => {
    setDraft(value)
    setEditing(false)
  }, [value])

  // 只读字段直接展示
  if (isReadonlyField(field)) {
    return <DisplayCell value={value} field={field} rowId={rowId} wid={wid} />
  }

  // 修改审批中锁定：待处理行展示原值，双击不进入编辑
  if (locked) {
    return (
      <Tooltip title="该行有修改申请待审批，审批完成后可继续操作">
        <div style={{ padding: '2px 4px', minHeight: 22 }} data-testid="cell-locked">
          <DisplayCell value={value} field={field} rowId={rowId} wid={wid} />
        </div>
      </Tooltip>
    )
  }

  // 受控模式：编辑态与草稿值由父级决定
  if (controlled) {
    // 自动填充锁定开启时，预填字段只读 —— 直接展示 DisplayCell 并加锁图标/提示
    if (readOnly) {
      return (
        <Tooltip title="此字段为自动预填，已锁定（可在个人设置 > 表格 > 操作风格中关闭）">
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 2, width: '100%' }}>
            <DisplayCell value={value} field={field} rowId={rowId} wid={wid} />
            <LockOutlined style={{ fontSize: 10, color: '#bfbfbf', marginLeft: 2 }} />
          </span>
        </Tooltip>
      )
    }
    // 草稿值即 value（父级传入的当前值）；回车提交走 onDraftCommit（行级保存统一由父级处理）
    return (
      <EditCell
        tableId={tableId}
        field={field}
        draft={value}
        onChange={onDraftChange ?? (() => { })}
        inputRef={inputRef}
        onSave={() => onDraftCommit?.(field.name, finalizeValueFromEdit(value, field))}
        onCancel={() => onDraftCancel?.()}
        saving={false}
        wid={wid}
        showActions={!!showActionButtons}
        enableAutoFocus={false}
      />
    )
  }

  if (!editing) {
    // 双击进入编辑态时阻断冒泡：行级 onDoubleClick（打开行详情 Drawer）不再同时触发；
    // 无保存回调（只读场景）时不挂双击事件，让冒泡到行以打开 Drawer
    const editable = !!effectiveOnSave
    return (
      <div
        onDoubleClick={editable
          ? (e) => { e.stopPropagation(); handleStartEdit() }
          : undefined}
        style={{ padding: '2px 4px', cursor: editable ? 'pointer' : 'default', minHeight: 22 }}
        title={editable ? '双击编辑' : undefined}
      >
        <DisplayCell value={value} field={field} rowId={rowId} wid={wid} />
      </div>
    )
  }

  // 编辑态同样阻断双击冒泡：编辑中再双击控件不应弹出行详情 Drawer
  return (
    <div onDoubleClick={(e) => e.stopPropagation()}>
      <EditCell
        field={field}
        draft={isEditing ? draft : value}
        onChange={setDraft}
        inputRef={inputRef}
        onSave={handleSave}
        onCancel={handleCancel}
        saving={saving}
        wid={wid}
      />
    </div>
  )
}

// memo 化：父级（buildColumns 普通分支）传稳定引用的 onCellSave 时，
// 表格重渲染仅重绘值发生变化的单元格
export default memo(GridCell)
