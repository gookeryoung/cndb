/** 新增行自动编号单元格 —— 默认只读展示后端推算的编号，点击编辑图标后可手动改号.
 *
 * 手动值写入行草稿；未编辑或清空时草稿为空，建行仍由后端自动生成编号。
 */

import { useState } from 'react'
import type { CSSProperties } from 'react'
import { Button, Input } from 'antd'
import { EditOutlined } from '@ant-design/icons'
import type { Field } from '@/api'

interface Props {
  field: Field
  /** 行草稿中该字段的值（未手动编辑时为空） */
  value: unknown
  /** 后端按库内已有数据推算的下一个编号 */
  previewValue?: string
  /** 只读（自动填充锁定 / 无编辑权限） */
  readOnly?: boolean
  /** 手动修改时写回行草稿 */
  onChange: (value: string) => void
}

/** 只读态的展示样式：编号本身足够，不附加说明文案 */
const DISPLAY_STYLE: CSSProperties = {
  display: 'inline-flex',
  alignItems: 'center',
  gap: 2,
  color: '#64748b',
  fontSize: 12,
  whiteSpace: 'nowrap',
}

export default function AutoIncrementCell({ field, value, previewValue, readOnly = false, onChange }: Props) {
  const [editing, setEditing] = useState(false)
  // 编辑态初值：已有手动值优先，否则用当前预览编号（仅本地展示，用户不改动则不提交）
  const [text, setText] = useState('')
  const manual = value === null || value === undefined ? '' : String(value)
  const shown = manual !== '' ? manual : (previewValue ?? '自动')

  if (readOnly) {
    return <span data-testid={`cell-auto-increment-${field.id}`} style={DISPLAY_STYLE}>{shown}</span>
  }

  if (editing) {
    return (
      <Input
        size="small"
        data-testid={`auto-increment-input-${field.id}`}
        value={text}
        onChange={e => {
          setText(e.target.value)
          onChange(e.target.value)
        }}
      />
    )
  }

  return (
    <span data-testid={`cell-auto-increment-${field.id}`} style={DISPLAY_STYLE}>
      {shown}
      <Button
        type="text"
        size="small"
        icon={<EditOutlined />}
        aria-label="手动修改编号"
        data-testid={`auto-increment-edit-${field.id}`}
        style={{ padding: 0, height: 16, minWidth: 16 }}
        onClick={() => {
          setText(manual !== '' ? manual : (previewValue ?? ''))
          setEditing(true)
        }}
      />
    </span>
  )
}
