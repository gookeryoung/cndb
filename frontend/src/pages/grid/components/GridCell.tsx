import React, { useMemo } from 'react'
import { Tag, Tooltip, Typography } from 'antd'
import dayjs from 'dayjs'
import type { Field } from '@/api'

interface Props {
  value: unknown
  field: Field
  rowId: number | string
}

export default function GridCell({ value, field, rowId }: Props) {
  return useMemo(() => renderByFieldType(value, field, rowId), [value, field, rowId])
}

function renderByFieldType(value: unknown, field: Field, rowId: number | string): React.ReactNode {
  if (value === null || value === undefined || value === '') {
    return <span style={{ color: '#cbd5e1' }}>—</span>
  }
  const ft = field.field_type
  switch (ft) {
    case 'boolean': {
      const v = Boolean(value)
      return <Tag color={v ? 'green' : 'default'}>{v ? '是' : '否'}</Tag>
    }
    case 'number':
    case 'decimal':
      return <span style={{ fontFamily: 'ui-monospace, monospace' }}>{String(value)}</span>
    case 'date':
      return <span>{dayjs(String(value)).format('YYYY-MM-DD')}</span>
    case 'datetime':
      return <span>{dayjs(String(value)).format('YYYY-MM-DD HH:mm')}</span>
    case 'select':
      return <Tag color="blue">{String(value)}</Tag>
    case 'multi_select': {
      const arr = Array.isArray(value) ? value : String(value).split(',').map(s => s.trim()).filter(Boolean)
      return <>{arr.map((v, i) => <Tag key={i}>{String(v)}</Tag>)}</>
    }
    case 'email':
      return <Typography.Link href={`mailto:${value}`}>{String(value)}</Typography.Link>
    case 'url':
      return <Typography.Link href={String(value)} target="_blank" rel="noreferrer">{String(value)}</Typography.Link>
    case 'link': {
      if (Array.isArray(value)) {
        return <span>{value.map((v: Record<string, unknown>, i: number) => <Tag key={i}>{String(v?.value ?? v?.id ?? v)}</Tag>)}</span>
      }
      if (value && typeof value === 'object') {
        const o = value as Record<string, unknown>
        return <Tooltip title={`row ${o.id ?? rowId}`}><Tag>{String(o.value ?? o.id ?? value)}</Tag></Tooltip>
      }
      return <Tag>{String(value)}</Tag>
    }
    case 'attachment':
      return <span>📎 {String(value)}</span>
    case 'auto_id':
    case 'created_time':
    case 'updated_time':
    case 'created_by':
    case 'updated_by':
      return <span style={{ color: '#64748b' }}>{String(value)}</span>
    case 'long_text': {
      const s = String(value)
      return <Tooltip title={s}><span>{s.length > 40 ? s.slice(0, 40) + '…' : s}</span></Tooltip>
    }
    case 'phone':
      return <span>{String(value)}</span>
    default:
      return <span>{String(value)}</span>
  }
}
