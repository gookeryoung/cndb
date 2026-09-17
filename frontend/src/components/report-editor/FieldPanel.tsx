import { useEffect, useMemo, useState } from 'react'
import { Input, Tag, Empty, Typography, Tabs } from 'antd'
import { SearchOutlined } from '@ant-design/icons'
import { useSortable } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import type { Field, FieldType } from '@/api'

/** 多表字段分组：主表 + 额外表 */
export interface TableFieldGroup {
  tableId: number
  tableName: string
  fields: Field[]
  /** 是否为主表（默认选中） */
  isPrimary?: boolean
}

export interface FieldPanelProps {
  /** 关联表的全部字段（单一表模式，向后兼容） */
  fields?: Field[]
  /** 多表字段分组（多表模式，优先使用） */
  tableGroups?: TableFieldGroup[]
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

export default function FieldPanel({ fields, tableGroups, onInsert }: FieldPanelProps) {
  const [search, setSearch] = useState('')

  // 确定是多表模式还是单表模式
  const isMultiTable = !!tableGroups && tableGroups.length > 1

  // 多表模式：用 state 追踪当前选中的表 ID
  const defaultGroupId = useMemo(() => {
    if (!tableGroups || tableGroups.length === 0) return null
    const primary = tableGroups.find(g => g.isPrimary)
    return primary ? primary.tableId : tableGroups[0].tableId
  }, [tableGroups])

  const [activeTableId, setActiveTableId] = useState<number | null>(defaultGroupId)

  // tableGroups 变化时同步 activeTableId（用 useEffect 而不是 useMemo）
  useEffect(() => {
    if (defaultGroupId !== null && defaultGroupId !== activeTableId) {
      setActiveTableId(defaultGroupId)
    }
  }, [defaultGroupId])

  // 当前激活的分组
  const activeGroup = useMemo(() => {
    if (!tableGroups || tableGroups.length === 0) return null
    const found = tableGroups.find(g => g.tableId === activeTableId)
    return found || tableGroups[0]
  }, [tableGroups, activeTableId])

  // 当前显示的字段列表
  const currentFields: Field[] = useMemo(() => {
    if (isMultiTable && activeGroup) return activeGroup.fields
    return fields || []
  }, [isMultiTable, activeGroup, fields])

  const filtered = useMemo(() => {
    if (!search.trim()) return currentFields
    const q = search.toLowerCase()
    return currentFields.filter(f => f.name.toLowerCase().includes(q))
  }, [currentFields, search])

  const showSearch = currentFields.length > 10

  // 点击插入时：多表模式自动加上 records_by_table 前缀；单表模式不加
  const handleInsert = (fieldName: string) => {
    if (isMultiTable && activeGroup && !activeGroup.isPrimary) {
      // 额外表字段用 records_by_table 语法
      onInsert(`{{ records_by_table['${activeGroup.tableName}'][0].${fieldName} }}`)
    } else {
      // 主表/单表：简化语法
      onInsert(fieldName)
    }
  }

  if (isMultiTable && tableGroups) {
    return (
      <div className="report-field-panel">
        <div className="report-field-panel-header">
          <Typography.Text strong style={{ fontSize: 13 }}>
            字段（多表）
          </Typography.Text>
        </div>

        <Tabs
          size="small"
          activeKey={activeGroup ? String(activeGroup.tableId) : undefined}
          style={{ marginBottom: 4 }}
          items={tableGroups.map(g => ({
            key: String(g.tableId),
            label: (
              <span style={{ fontSize: 12 }}>
                {g.tableName}
                {g.isPrimary && <Tag color="blue" style={{ marginLeft: 4, fontSize: 10, lineHeight: '14px' }}>主</Tag>}
              </span>
            ),
          }))}
          onChange={(key) => setActiveTableId(Number(key))}
        />

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
              <DraggableFieldItem key={field.id} field={field} onInsert={handleInsert} />
            ))
          )}
        </div>

        <div className="report-field-panel-footer">
          <Typography.Text type="secondary" style={{ fontSize: 11 }}>
            {isMultiTable && activeGroup && !activeGroup.isPrimary
              ? `额外表 → 插入 records_by_table['${activeGroup.tableName}'] 语法`
              : '点击或拖拽字段到编辑器'}
          </Typography.Text>
        </div>
      </div>
    )
  }

  // ── 单表模式（向后兼容） ──
  return (
    <div className="report-field-panel">
      <div className="report-field-panel-header">
        <Typography.Text strong style={{ fontSize: 13 }}>
          字段 ({(fields || []).length})
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
            <DraggableFieldItem key={field.id} field={field} onInsert={handleInsert} />
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
