/** 表权限编辑器 — 嵌入在 Modal 内 */

import { useState } from 'react'
import { Form, Input } from 'antd'
import type { Field, TablePermission } from '@/api'

interface PermissionEditorProps {
  fields: Field[]
  data?: TablePermission
}

/** 把后端 hidden_fields（dict: 角色名 → 隐藏字段列表）展平成一个 Set.
 *  后端 schema: hidden_fields: dict[str, Any] = { "admin": ["name"], "editor": [...] }
 *  历史遗留：早期设计为数组，后端改为按角色分桶后前端没跟进，需要兼容两种形态.
 */
function buildHiddenSet(hidden: unknown): Set<string> {
  const set = new Set<string>()
  if (!hidden) return set
  if (Array.isArray(hidden)) {
    hidden.forEach(v => set.add(String(v)))
  } else if (typeof hidden === 'object') {
    // 角色 → 列表 的 dict，把所有角色的 hidden fields 合并
    Object.values(hidden as Record<string, unknown>).forEach(v => {
      if (Array.isArray(v)) v.forEach(x => set.add(String(x)))
      else if (v != null) set.add(String(v))
    })
  }
  return set
}

/** 内嵌在权限 Modal 内的编辑 UI */
export default function PermissionEditor({ fields, data }: PermissionEditorProps) {
  const [comment, setComment] = useState(data?.comment_role || '')
  // hidden_fields 在后端是 dict（按角色分桶），这里做兼容展平
  const hiddenSet = buildHiddenSet(data?.hidden_fields as unknown)

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
