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

/** 字段分组信息（用于构造插入语法） */
export interface FieldGroupInfo {
  tableName: string
  isPrimary: boolean
}

/**
 * 构造字段插入文本 —— 插入语法的单一来源.
 *
 * 主表/无分组：`{{ name }}`；额外表：`{{ records_by_table['表名'][0].name }}`
 * （[0] 首行语义，与 FieldPanel 页脚提示一致）。
 */
export function buildFieldInsertText(
  field: Pick<Field, 'name'>,
  group?: FieldGroupInfo,
): string {
  if (group && !group.isPrimary) {
    return `{{ records_by_table['${group.tableName}'][0].${field.name} }}`
  }
  return `{{ ${field.name} }}`
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
    const map = new Map<string, { field: Field; group?: FieldGroupInfo }>()

    if (tableGroups && tableGroups.length > 0) {
      for (const group of tableGroups) {
        for (const f of group.fields) {
          const id = `field-${f.id}`
          ids.push(id)
          map.set(id, { field: f, group: { tableName: group.tableName, isPrimary: !!group.isPrimary } })
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
      internalRef.current?.insertText(buildFieldInsertText(item.field, item.group))
    } else if (data?.fieldName) {
      // fallback：仅插入简单语法
      internalRef.current?.insertText(`{{ ${data.fieldName} }}`)
    }
  }

  // 点击插入（FieldPanel onInsert 回调）—— 与拖拽共用同一语法构造，避免双包裹
  const handleFieldInsert = (field: Field, group?: FieldGroupInfo) => {
    internalRef.current?.insertText(buildFieldInsertText(field, group))
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
