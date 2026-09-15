import { useEffect, useRef, useState } from 'react'
import { DndContext, closestCenter, useSensor, useSensors, PointerSensor, KeyboardSensor, useDroppable, type DragEndEvent, type DragStartEvent } from '@dnd-kit/core'
import { SortableContext, verticalListSortingStrategy } from '@dnd-kit/sortable'
import TemplateEditor, { type TemplateEditorHandle } from './TemplateEditor'
import FieldPanel from './FieldPanel'
import type { Field } from '@/api'

interface ReportTemplateEditorProps {
  value: string
  onChange: (value: string) => void
  fields: Field[]
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
      style={{ flex: 1, minWidth: 0, position: 'relative' }}
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
          松开以插入 {'{{ field_name }}'}
        </div>
      )}
    </div>
  )
}

export default function ReportTemplateEditor({
  value,
  onChange,
  fields,
  editorRef,
}: ReportTemplateEditorProps) {
  const internalRef = useRef<TemplateEditorHandle>(null)
  const [isDragActive, setIsDragActive] = useState(false)

  // 如果外部传了 editorRef，把 internalRef 的值同步过去
  useEffect(() => {
    if (editorRef && typeof editorRef === 'object') {
      ;(editorRef as React.MutableRefObject<TemplateEditorHandle | null>).current = internalRef.current
    }
  })

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
    useSensor(KeyboardSensor),
  )

  const handleDragStart = (_event: DragStartEvent) => {
    setIsDragActive(true)
  }

  const handleDragEnd = (event: DragEndEvent) => {
    setIsDragActive(false)
    const { active, over } = event
    if (!over) return
    if (over.id !== 'template-editor-dropzone') return

    const data = active.data.current as { type: string; fieldName?: string } | undefined
    if (data?.type === 'field' && data.fieldName) {
      internalRef.current?.insertText(`{{ ${data.fieldName} }}`)
    }
  }

  const handleFieldInsert = (fieldName: string) => {
    internalRef.current?.insertText(`{{ ${fieldName} }}`)
  }

  const fieldIds = fields.map(f => `field-${f.id}`)

  return (
    <DndContext
      sensors={sensors}
      collisionDetection={closestCenter}
      onDragStart={handleDragStart}
      onDragEnd={handleDragEnd}
    >
      <SortableContext items={fieldIds} strategy={verticalListSortingStrategy}>
        <FieldPanel fields={fields} onInsert={handleFieldInsert} />
      </SortableContext>

      <EditorDropzone
        value={value}
        onChange={onChange}
        editorRef={internalRef}
        isDragActive={isDragActive}
      />
    </DndContext>
  )
}
