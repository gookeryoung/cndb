/** 表权限编辑器 — 嵌入在 Modal 内 */

import { useState } from 'react'
import { Form, Input } from 'antd'
import type { Field, TablePermission } from '@/api'

interface PermissionEditorProps {
  fields: Field[]
  data?: TablePermission
}

/** 内嵌在权限 Modal 内的编辑 UI */
export default function PermissionEditor({ fields, data }: PermissionEditorProps) {
  const [comment, setComment] = useState(data?.comment || '')
  const hiddenSet = new Set(data?.hidden_fields || [])

  return (
    <div style={{ marginTop: 12 }}>
      <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8 }}>隐藏字段（勾选后用户不可见）</div>
      <Form>
        {fields.filter(f => !f.hidden).map(f => (
          <Form.Item key={f.id} style={{ marginBottom: 4 }}>
            <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13 }}>
              <input
                type="checkbox"
                value={f.name}
                defaultChecked={hiddenSet.has(f.name)}
                data-perm-hidden
              />
              {f.name} <span style={{ color: '#9ca3af', fontSize: 11 }}>({f.field_type})</span>
            </label>
          </Form.Item>
        ))}
      </Form>
      <div style={{ marginTop: 16, fontSize: 13, fontWeight: 600, marginBottom: 8 }}>备注</div>
      <Input.TextArea
        rows={3}
        placeholder="权限备注"
        value={comment}
        onChange={e => setComment(e.target.value)}
        data-perm-comment
      />
    </div>
  )
}
