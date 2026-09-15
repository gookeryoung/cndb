import { useMemo, useState } from 'react'
import { Input, Tag, Empty, Typography } from 'antd'
import { SearchOutlined } from '@ant-design/icons'
import { useSortable } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import type { Field, FieldType } from '@/api'

export interface FieldPanelProps {
  /** 关联表的全部字段 */
  fields: Field[]
  /** 点击或拖拽字段时的回调（传入字段名） */
  onInsert: (fieldName: string) => void
  /** 拖拽开始时触发（用于编辑器显示 dropzone 高亮） */
  onDragStart?: () => void
  /** 拖拽结束时触发 */
  onDragEnd?: () => void
}

/** FieldType → Ant Design Tag 颜色映射（复用 grid 页风格） */
const FIELD_TYPE_COLOR: Record<string, string> = {
  text: 'blue',
  longtext: 'cyan',
  number: 'green',
  float: 'green',
  boolean: 'purple',
  date: 'orange',
  datetime: 'orange',
  timestamp: 'orange',
  select: 'gold',
  multiselect: 'gold',
  email: 'geekblue',
  url: 'geekblue',
  phone: 'geekblue',
  link: 'magenta',
  attachment: 'volcano',
  percentage: 'lime',
}

function FieldTag({ type }: { type: FieldType }) {
  const color = FIELD_TYPE_COLOR[type] || 'default'
  const labelMap: Record<string, string> = {
    text: '文本', longtext: '长文本', number: '整数', float: '小数',
    boolean: '布尔', date: '日期', datetime: '时间', timestamp: '时间戳',
    select: '单选', multiselect: '多选', email: '邮箱', url: '链接',
    phone: '电话', link: '关联', attachment: '附件', percentage: '百分比',
  }
  return <Tag color={color} style={{ marginLeft: 4, fontSize: 11 }}>{labelMap[type] || type}</Tag>
}

/** 单个可拖拽字段项 */
function DraggableFieldItem({
  field,
  onInsert,
}: {
  field: Field
  onInsert: (name: string) => void
}) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: `field-${field.id}`,
    data: { type: 'field', fieldName: field.name },
  })
  const style: React.CSSProperties = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.4 : 1,
  }

  return (
    <div
      ref={setNodeRef}
      style={style}
      {...attributes}
      {...listeners}
      onClick={() => onInsert(field.name)}
      title={`${field.name} — 点击插入，拖拽到编辑器`}
      className="report-field-item"
    >
      <span className="report-field-name">{field.name}</span>
      <FieldTag type={field.field_type} />
    </div>
  )
}

export default function FieldPanel({ fields, onInsert }: FieldPanelProps) {
  const [search, setSearch] = useState('')

  const filtered = useMemo(() => {
    if (!search.trim()) return fields
    const q = search.toLowerCase()
    return fields.filter(f => f.name.toLowerCase().includes(q))
  }, [fields, search])

  const showSearch = fields.length > 10

  return (
    <div className="report-field-panel">
      <div className="report-field-panel-header">
        <Typography.Text strong style={{ fontSize: 13 }}>
          字段 ({fields.length})
        </Typography.Text>
      </div>

      {showSearch && (
        <Input
          size="small"
          prefix={<SearchOutlined style={{ color: '#bfbfbf' }} />}
          placeholder="搜索字段"
          value={search}
          onChange={e => setSearch(e.target.value)}
          className="report-field-search"
          allowClear
        />
      )}

      <div className="report-field-list">
        {filtered.length === 0 ? (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description={<span style={{ fontSize: 12 }}>{search ? '未找到匹配字段' : '该表暂无字段'}</span>}
          />
        ) : (
          filtered.map(field => (
            <DraggableFieldItem key={field.id} field={field} onInsert={onInsert} />
          ))
        )}
      </div>

      <div className="report-field-panel-footer">
        <Typography.Text type="secondary" style={{ fontSize: 11 }}>
          点击或拖拽字段到编辑器
        </Typography.Text>
      </div>
    </div>
  )
}
