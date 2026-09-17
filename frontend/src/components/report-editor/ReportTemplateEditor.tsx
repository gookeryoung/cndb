import { useEffect, useMemo, useRef, useState } from 'react'
import {
  DndContext,
  closestCenter,
  useSensor,
  useSensors,
  PointerSensor,
  KeyboardSensor,
  useDroppable,
  type DragEndEvent,
  type DragStartEvent,
} from '@dnd-kit/core'
import { SortableContext, verticalListSortingStrategy } from '@dnd-kit/sortable'
import TemplateEditor, { type TemplateEditorHandle } from './TemplateEditor'
import FieldPanel, { type TableFieldGroup } from './FieldPanel'
import type { Field } from '@/api'

interface ReportTemplateEditorProps {
  value: string
  onChange: (value: string) => void
  /** 单表字段（向后兼容） */
  fields?: Field[]
  /** 多表字段分组（多表模式，优先使用） */
  tableGroups?: TableFieldGroup[]
  editorRef?: React.RefObject<TemplateEditorHandle | null>
}

/** 编辑器 dropzone —— 用 useDroppable 正确注册 */
function EditorDropzone({
  value,
  onChange,
  editorRef,
  isDragActive,
}: {
  value: string
  onChange: (v: string) => void
  editorRef: React.RefObject<TemplateEditorHandle>
  isDragActive: boolean
}) {
  const { setNodeRef, isOver } = useDroppable({ id: 'template-editor-dropzone' })

  const dropzoneActive = isDragActive && isOver

  return (
    <div
      ref={setNodeRef}
      style={{ flex: 1, minWidth: 0, minHeight: 0, height: '100%', position: 'relative', overflow: 'hidden' }}
      data-dropzone="true"
    >
      <TemplateEditor
        ref={editorRef}
        value={value}
        onChange={onChange}
        isDragActive={dropzoneActive}
      />
      {/* dropzone 提示 overlay */}
      {dropzoneActive && (
        <div
          style={{
            position: 'absolute',
            inset: 0,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            background: 'rgba(22, 119, 255, 0.08)',
            color: '#1677ff',
            fontSize: 14,
            pointerEvents: 'none',
            borderRadius: 6,
          }}
        >
          松开以插入字段
        </div>
      )}
    </div>
  )
}

export default function ReportTemplateEditor({
  value,
  onChange,
  fields,
  tableGroups,
  editorRef,
}: ReportTemplateEditorProps) {
  const internalRef = useRef<TemplateEditorHandle>(null)
  const [isDragActive, setIsDragActive] = useState(false)

  // 如果外部传了 editorRef，把 internalRef 的值同步过去
  useEffect(() => {
    if (editorRef && typeof editorRef === 'object') {
      ; (editorRef as React.MutableRefObject<TemplateEditorHandle | null>).current = internalRef.current
    }
  })

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
    useSensor(KeyboardSensor),
  )

  // 展平所有字段（tableGroups 优先）生成 SortableContext items
  const { fieldIds, fieldMap } = useMemo(() => {
    const ids: string[] = []
    const map = new Map<string, { field: Field; group?: TableFieldGroup }>()

    if (tableGroups && tableGroups.length > 0) {
      for (const group of tableGroups) {
        for (const f of group.fields) {
          const id = `field-${f.id}`
          ids.push(id)
          map.set(id, { field: f, group })
        }
      }
    } else {
      for (const f of fields || []) {
        const id = `field-${f.id}`
        ids.push(id)
        map.set(id, { field: f })
      }
    }

    return { fieldIds: ids, fieldMap: map }
  }, [tableGroups, fields])

  // 构造要插入的模板代码（多表模式自动加 records_by_table 前缀）
  const buildInsertText = (item: { field: Field; group?: TableFieldGroup }): string => {
    const { field, group } = item
    if (group && !group.isPrimary) {
      return `{{ records_by_table['${group.tableName}'][0].${field.name} }}`
    }
    return `{{ ${field.name} }}`
  }

  const handleDragStart = (_event: DragStartEvent) => {
    setIsDragActive(true)
  }

  const handleDragEnd = (event: DragEndEvent) => {
    setIsDragActive(false)
    const { active, over } = event
    if (!over) return

    // over 是某个字段项自身（field- 前缀）→ 用户在 FieldPanel 内排序，跳过 insert
    if (String(over.id).startsWith('field-')) return

    // 确认目标是编辑器 dropzone
    if (over.id !== 'template-editor-dropzone') return

    // 从 dnd-kit 的 data 中获取字段 id；若找不到，尝试从 active.id 反查
    const data = active.data.current as { type?: string; fieldId?: string; fieldName?: string } | undefined
    const fieldId = data?.fieldId ?? String(active.id)
    const item = fieldMap.get(fieldId)

    if (item) {
      internalRef.current?.insertText(buildInsertText(item))
    } else if (data?.fieldName) {
      // fallback：仅插入简单语法
      internalRef.current?.insertText(`{{ ${data.fieldName} }}`)
    }
  }

  // 点击插入（FieldPanel onInsert 回调）
  const handleFieldInsert = (fieldName: string) => {
    internalRef.current?.insertText(`{{ ${fieldName} }}`)
  }

  return (
    <div className="report-template-editor">
      <DndContext
        sensors={sensors}
        collisionDetection={closestCenter}
        onDragStart={handleDragStart}
        onDragEnd={handleDragEnd}
      >
        <SortableContext items={fieldIds} strategy={verticalListSortingStrategy}>
          <FieldPanel
            fields={fields}
            tableGroups={tableGroups}
            onInsert={handleFieldInsert}
          />
        </SortableContext>

        <EditorDropzone
          value={value}
          onChange={onChange}
          editorRef={internalRef}
          isDragActive={isDragActive}
        />
      </DndContext>
    </div>
  )
}
