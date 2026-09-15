/** 按 field_type 分发渲染组件.
 *
 * 对齐 backend FieldType: text / longtext / number / float / boolean
 * / date / datetime / select / multiselect / link
 */
import { View, Text } from '@tarojs/components'

interface Field {
  id: number | string
  name: string
  field_type: string
  config?: Record<string, unknown> | null
  hidden?: boolean
}

/** 安全渲染字段值，处理 null/undefined/空字符串. */
function fallback(): JSX.Element {
  return <Text className='cell-empty'>—</Text>
}

function CellText({ value }: { value: string }) {
  return <Text className='cell-text'>{value}</Text>
}

function CellNumber({ value }: { value: number }) {
  const formatted = Number.isInteger(value) ? String(value) : value.toFixed(2)
  return <Text className='cell-number'>{formatted}</Text>
}

function CellBoolean({ value }: { value: boolean }) {
  return value ? <Text className='cell-bool-true'>✓</Text> : fallback()
}

function CellDate({ value }: { value: string }) {
  // 取日期部分 YYYY-MM-DD
  const date = value.split('T')[0] || value.slice(0, 10)
  return <Text className='cell-date'>{date}</Text>
}

function CellDateTime({ value }: { value: string }) {
  // 取日期 + HH:mm
  const parts = value.replace('T', ' ').slice(0, 16)
  return <Text className='cell-date'>{parts}</Text>
}

function CellSelect({ value }: { value: string }) {
  return <Text className='cell-select'>{value}</Text>
}

function CellMultiSelect({ value }: { value: unknown }) {
  const items = Array.isArray(value) ? value as string[] : []
  return (
    <View className='cell-multiselect'>
      {items.map((v, i) => (
        <Text key={i} className='cell-select'>{v}</Text>
      ))}
    </View>
  )
}

function CellLink({ value }: { value: string }) {
  return <Text className='cell-link'>{value}</Text>
}

export default function FieldRenderer({ field, value }: {
  field: Field
  value: unknown
}) {
  if (value === null || value === undefined || value === '') return fallback()

  switch (field.field_type) {
    case 'text':
    case 'longtext':
      return <CellText value={String(value)} />

    case 'number':
    case 'float':
      return <CellNumber value={Number(value)} />

    case 'boolean':
      return <CellBoolean value={Boolean(value)} />

    case 'date':
      return <CellDate value={String(value)} />

    case 'datetime':
      return <CellDateTime value={String(value)} />

    case 'select':
      return <CellSelect value={String(value)} />

    case 'multiselect':
      return <CellMultiSelect value={value} />

    case 'link':
      return <CellLink value={String(value)} />

    default:
      return <Text>{String(value)}</Text>
  }
}
