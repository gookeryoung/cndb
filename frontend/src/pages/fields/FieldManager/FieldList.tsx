/** 字段列表 + 工具栏 + 可拖拽行卡片.
 *
 * 从 FieldManager 拆出（原 1300 行单体的列表区块）；
 * fieldNoteText / formatIncrementExample 同时供 DefaultValueInput 与测试使用.
 */
import type { ReactNode } from 'react'
import { Button, Empty, Popconfirm, Tag, Tooltip } from 'antd'
import {
  DeleteOutlined, EditOutlined, HolderOutlined, ImportOutlined, PlusOutlined, TagOutlined,
  FontSizeOutlined, AlignLeftOutlined, CheckSquareOutlined, FieldNumberOutlined, PercentageOutlined,
  CalendarOutlined, ClockCircleOutlined, FieldTimeOutlined, TagsOutlined, MailOutlined,
  LinkOutlined, PhoneOutlined, ApartmentOutlined, PaperClipOutlined,
} from '@ant-design/icons'
import {
  DndContext,
  closestCenter,
  PointerSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
} from '@dnd-kit/core'
import {
  SortableContext,
  useSortable,
  verticalListSortingStrategy,
  arrayMove,
} from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import type { Field, FieldType } from '@/api'
import { getFieldTypeColor, getFieldTypeLabel } from '@/utils/fieldTypeMeta'

/** 字段类型 → 图标（字段行卡片等场景共用；历史别名类型走 TagOutlined 兜底） */
export const FIELD_TYPE_ICONS: Partial<Record<FieldType, ReactNode>> = {
  text: <FontSizeOutlined />,
  longtext: <AlignLeftOutlined />,
  boolean: <CheckSquareOutlined />,
  number: <FieldNumberOutlined />,
  float: <FieldNumberOutlined />,
  percentage: <PercentageOutlined />,
  date: <CalendarOutlined />,
  datetime: <ClockCircleOutlined />,
  timestamp: <FieldTimeOutlined />,
  select: <TagOutlined />,
  multiselect: <TagsOutlined />,
  email: <MailOutlined />,
  url: <LinkOutlined />,
  phone: <PhoneOutlined />,
  link: <ApartmentOutlined />,
  attachment: <PaperClipOutlined />,
}

/** 字段行的备注文字：必填/唯一状态 + 默认值/自动编号 + 自动填充规则（备注风格，无任何状态则返回空串不渲染） */
export function fieldNoteText(f: Field): string {
  const parts: string[] = []
  if (f.required) parts.push('必填')
  if (f.is_unique) parts.push('唯一')
  const defaultMode = (f.config?.default_mode as string) ?? ''
  if (f.field_type === 'text' && defaultMode === 'auto_increment') {
    parts.push(`自动编号：${formatIncrementExample(f.config)} 起`)
  } else if (f.default_value !== null && f.default_value !== undefined && f.default_value !== '') {
    parts.push(`默认值：${String(f.default_value)}`)
  }
  const autoFill = (f.config?.auto_fill as string) ?? ''
  if ((f.field_type === 'date' || f.field_type === 'datetime') && autoFill) {
    parts.push(autoFill === 'on_create' ? '创建时自动填充' : '更新时自动填充')
  }
  return parts.join(' · ')
}

/** 由自动编号 config 拼出示例编号（如 PRJ-0001），供备注与默认值编辑器共用 */
export function formatIncrementExample(config: Record<string, unknown> | undefined): string {
  const prefix = String(config?.increment_prefix ?? '')
  const paddingNum = Number(config?.increment_padding ?? 4)
  const padding = Number.isFinite(paddingNum) ? Math.max(0, Math.min(10, Math.trunc(paddingNum))) : 4
  const startNum = Number(config?.increment_start ?? 1)
  const start = Number.isFinite(startNum) ? Math.max(0, Math.trunc(startNum)) : 1
  return `${prefix}${String(start).padStart(padding, '0')}`
}

interface FieldListProps {
  /** 已按 order 排序的字段列表 */
  fields: Field[]
  isReordering: boolean
  onEdit: (field: Field) => void
  onRemove: (field: Field) => void
  /** 拖拽结束后提交新顺序的字段 id 列表 */
  onReorder: (ids: Array<number | string>) => void
  onOpenImport: () => void
  onCreate: () => void
}

/** 字段列表 + 工具栏（Modal 与嵌入模式共用的内容区） */
export default function FieldList({ fields, isReordering, onEdit, onRemove, onReorder, onOpenImport, onCreate }: FieldListProps) {
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 4 } }))
  const handleFieldDragEnd = (event: DragEndEvent) => {
    const { active, over } = event
    if (!over || active.id === over.id) return
    const oldIndex = fields.findIndex(f => String(f.id) === String(active.id))
    const newIndex = fields.findIndex(f => String(f.id) === String(over.id))
    if (oldIndex < 0 || newIndex < 0) return
    const reordered = arrayMove(fields, oldIndex, newIndex)
    onReorder(reordered.map(f => f.id))
  }

  return (
    <>
      <div className="fm-toolbar">
        <span style={{ color: 'var(--cn-text-secondary)', fontSize: 13 }}>共 {fields.length} 个字段 · 拖拽手柄可调整顺序</span>
        <div style={{ display: 'flex', gap: 8 }}>
          <Button icon={<ImportOutlined />} onClick={onOpenImport}>
            从其他表引入
          </Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={onCreate}>
            新建字段
          </Button>
        </div>
      </div>

      {fields.length === 0 ? (
        <Empty description="暂无字段，点击右上角「新建字段」创建" style={{ padding: 32 }} />
      ) : (
        <div style={{ maxHeight: 480, overflowY: 'auto' }}>
          <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleFieldDragEnd}>
            <SortableContext items={fields.map(f => String(f.id))} strategy={verticalListSortingStrategy}>
              {fields.map((r) => (
                <SortableFieldRow
                  key={String(r.id)}
                  field={r}
                  onEdit={() => onEdit(r)}
                  onRemove={() => onRemove(r)}
                  isReordering={isReordering}
                />
              ))}
            </SortableContext>
          </DndContext>
        </div>
      )}
    </>
  )
}

// ─────────────── 可拖拽字段行 ───────────────

interface SortableFieldRowProps {
  field: Field
  onEdit: () => void
  onRemove: () => void
  isReordering: boolean
}

/** 字段行卡片 —— 带左侧拖拽手柄，配合 DndContext + SortableContext 使用. */
function SortableFieldRow({ field, onEdit, onRemove, isReordering }: SortableFieldRowProps) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: String(field.id),
  })

  const style: React.CSSProperties = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
    cursor: isDragging ? 'grabbing' : 'default',
  }

  return (
    <div ref={setNodeRef} style={style} className="fm-row">
      <span
        className="fm-row-drag-handle"
        title="拖拽调整字段顺序"
        {...attributes}
        {...listeners}
        style={{ cursor: isReordering ? 'grabbing' : 'grab', color: 'var(--cn-text-muted)', marginRight: 4 }}
      >
        <HolderOutlined />
      </span>
      <span className="fm-row-icon" title={getFieldTypeLabel(field.field_type)}>
        {FIELD_TYPE_ICONS[field.field_type] ?? <TagOutlined />}
      </span>
      <span className="fm-row-name">{field.name}</span>
      {fieldNoteText(field) && (
        <span className="fm-row-note" title={fieldNoteText(field)}>{fieldNoteText(field)}</span>
      )}
      <span className="fm-row-tags">
        {field.is_primary && <Tag color="gold" style={{ marginInlineEnd: 0 }}>PK</Tag>}
        <Tag color={getFieldTypeColor(field.field_type)} style={{ marginInlineEnd: 0 }} title={field.field_type}>
          {getFieldTypeLabel(field.field_type)}
        </Tag>
        {field.hidden && <Tag style={{ marginInlineEnd: 0 }}>隐藏</Tag>}
      </span>
      <span className="fm-row-actions">
        <Tooltip title="编辑字段类型与配置">
          <Button size="small" type="text" icon={<EditOutlined />} onClick={onEdit} />
        </Tooltip>
        {!field.is_primary && (
          <Popconfirm title="确认删除？" onConfirm={onRemove}>
            <Tooltip title="删除字段（列及其数据将从表中移除）">
              <Button size="small" type="text" danger icon={<DeleteOutlined />} />
            </Tooltip>
          </Popconfirm>
        )}
      </span>
    </div>
  )
}
