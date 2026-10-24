/** 导入预览左侧贴底：选中字段的 select options 编辑区.
 *
 * 从 FileImportPreview 的 renderSelectedFieldEditor 闭包抽出。
 */

import { Button, Tag } from 'antd'
import { PlusOutlined, SwapOutlined } from '@ant-design/icons'

import type { AnalyzeColumn, ColumnOverride } from './importPreviewTypes'

export default function SelectedFieldEditor({
  effectiveColumns,
  overrides,
  selectedField,
  updateOptions,
}: {
  effectiveColumns: AnalyzeColumn[]
  overrides: Record<string, ColumnOverride>
  selectedField: string | null
  updateOptions: (name: string, options: string[]) => void
}) {
    if (!selectedField) return null
    const col = effectiveColumns.find(c => c.name === selectedField)
    if (!col) return null

    const isSelect = col.field_type === 'select' || col.field_type === 'multiselect'
    if (!isSelect) return null

    const options = overrides[col.name]?.options ?? col.options ?? []

    return (
      <div style={{ marginTop: 8, padding: 12, background: 'var(--cn-bg-warning-subtle)', border: '1px solid var(--cn-mix-amber-45-transparent)', borderRadius: 6 }}>
        <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--cn-mix-amber-70-text-primary)', marginBottom: 8 }}>
          <SwapOutlined /> 编辑 {col.name} 的选项（{options.length} 个）
        </div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, alignItems: 'center' }}>
          {options.map((opt, i) => (
            <Tag
              key={i}
              closable
              style={{ padding: '2px 8px', fontSize: 12 }}
              onClose={() => updateOptions(col.name, options.filter((_, idx) => idx !== i))}
            >
              {opt}
            </Tag>
          ))}
          <Button
            size="small"
            type="dashed"
            icon={<PlusOutlined />}
            onClick={() => {
              const v = window.prompt('输入新选项值')
              if (v && v.trim() && !options.includes(v.trim())) {
                updateOptions(col.name, [...options, v.trim()])
              }
            }}
          >
            添加
          </Button>
        </div>
      </div>
    )
}
