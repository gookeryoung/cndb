/** 行详情抽屉 — 编辑字段值 / 评论 / 历史 / 反向引用. */

import React, { useState } from 'react'
import { Drawer, Form, Input, Button, Typography, Timeline, Tag, message, Select, DatePicker, InputNumber, Switch, Descriptions, Empty } from 'antd'
import { SaveOutlined, CommentOutlined, HistoryOutlined, LinkOutlined } from '@ant-design/icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { commentApi, auditApi, recordApi, tableApi } from '@/api'
import type { RowResponse, Field, AuditLog, Comment as ApiComment, Reference } from '@/api'

const { Title, Text } = Typography

interface Props {
  open: boolean
  row: RowResponse | null
  fields: Field[]
  wid: string
  tid: string
  onClose: () => void
}

export default function RowDetailDrawer({ open, row, fields, wid, tid, onClose }: Props) {
  const queryClient = useQueryClient()
  const [values, setValues] = useState<Record<string, unknown>>(row || {})
  const [commentText, setCommentText] = useState('')

  // 行特定的审计日志（新增 rowId 参数）
  const { data: audit = [] } = useQuery<AuditLog[]>({
    queryKey: ['row-audit', wid, tid, row?.id],
    queryFn: () => auditApi.list(wid, tid, undefined, 20, row?.id),
    enabled: open && !!row,
  })

  // 评论
  const { data: comments = [] } = useQuery<ApiComment[]>({
    queryKey: ['row-comments', wid, tid, row?.id],
    queryFn: () => commentApi.list(wid, tid, row!.id),
    enabled: open && !!row,
  })

  // 反向 link 引用（哪些其他表的行引用了当前行）
  const { data: references = [] } = useQuery<Reference[]>({
    queryKey: ['row-references', wid, tid, row?.id],
    queryFn: () => tableApi.references(wid, tid, row!.id),
    enabled: open && !!row,
  })

  const updateRow = useMutation({
    mutationFn: () => recordApi.update(wid, tid, row!.id, { values }),
    onSuccess: () => {
      message.success('已保存')
      queryClient.invalidateQueries({ queryKey: ['table-records', `${wid}/${tid}`] })
      queryClient.invalidateQueries({ queryKey: ['row-audit', wid, tid, row?.id] })
    },
  })

  const addComment = useMutation({
    mutationFn: () => commentApi.create(wid, tid, row!.id, commentText),
    onSuccess: () => {
      message.success('已评论')
      setCommentText('')
      queryClient.invalidateQueries({ queryKey: ['row-comments', wid, tid, row?.id] })
    },
  })

  React.useEffect(() => {
    if (row) setValues(row || {})
  }, [row])

  if (!row) return null

  return (
    <Drawer
      title={`行详情 #${row.id}`} width={600} open={open} onClose={onClose}
      extra={
        <Button type="primary" icon={<SaveOutlined />} onClick={() => updateRow.mutate()} loading={updateRow.isPending}>保存</Button>
      }
    >
      {/* 字段值编辑 */}
      <Title level={5}>字段值</Title>
      <Form layout="vertical">
        {fields.map(f => (
          <Form.Item key={String(f.id)} label={f.name} style={{ marginBottom: 12 }}>
            <FieldEditor
              field={f}
              value={values?.[f.name]}
              onChange={(v) => setValues(prev => ({ ...prev, [f.name]: v }))}
            />
          </Form.Item>
        ))}
      </Form>

      {/* 反向引用 */}
      {references.length > 0 && (
        <>
          <hr style={{ border: 'none', borderTop: '1px solid #f1f5f9', margin: '16px 0' }} />
          <Title level={5}><LinkOutlined /> 被引用 ({references.length})</Title>
          <div style={{ maxHeight: 200, overflowY: 'auto' }}>
            {references.map(ref => (
              <div key={`${ref.table_id}-${ref.row_id}`} style={{ padding: '6px 0', borderBottom: '1px solid #f8fafc' }}>
                <Tag color="blue">{ref.table_name || `表 #${ref.table_id}`}</Tag>
                <Text>{ref.row_summary || `行 #${ref.row_id}`}</Text>
              </div>
            ))}
          </div>
        </>
      )}

      {/* 评论 */}
      <hr style={{ border: 'none', borderTop: '1px solid #f1f5f9', margin: '16px 0' }} />
      <Title level={5}><CommentOutlined /> 评论</Title>
      <Input.TextArea rows={2} placeholder="写点什么..." value={commentText}
        onChange={e => setCommentText(e.target.value)} />
      <div style={{ marginTop: 8, textAlign: 'right' }}>
        <Button type="primary" onClick={() => addComment.mutate()} loading={addComment.isPending}>发表</Button>
      </div>
      <div style={{ marginTop: 12 }}>
        {comments.length === 0 ? (
          <Text type="secondary" italic>暂无评论</Text>
        ) : comments.map(c => (
          <div key={c.id} style={{ padding: '8px 0', borderBottom: '1px solid #f1f5f9' }}>
            <strong>{c.author_name || '匿名'}</strong>
            <span style={{ color: '#94a3b8', marginLeft: 8, fontSize: 12 }}>{c.created_at || ''}</span>
            <div>{c.content}</div>
          </div>
        ))}
      </div>

      {/* 操作历史 */}
      <hr style={{ border: 'none', borderTop: '1px solid #f1f5f9', margin: '16px 0' }} />
      <Title level={5}><HistoryOutlined /> 操作历史</Title>
      {audit.length === 0 ? (
        <Text type="secondary" italic>暂无历史记录</Text>
      ) : (
        <Timeline
          items={audit.map(a => ({
            color: a.action.includes('delete') ? 'red' : a.action.includes('create') ? 'green' : 'blue',
            children: (
              <div>
                <Tag>{a.action}</Tag>
                <span style={{ color: '#94a3b8', fontSize: 12 }}>{a.actor_name || '系统'} · {a.created_at || ''}</span>
              </div>
            ),
          }))}
        />
      )}
    </Drawer>
  )
}

/** 根据字段类型渲染合适的编辑控件. */
function FieldEditor({
  field, value, onChange,
}: {
  field: Field
  value: unknown
  onChange: (v: unknown) => void
}) {
  const ft = field.field_type

  switch (ft) {
    case 'number':
    case 'decimal':
      return <InputNumber style={{ width: '100%' }} value={value as number | undefined} onChange={onChange} placeholder="数字" />
    case 'boolean':
      return <Switch checked={!!value} onChange={onChange} />
    case 'date':
      return <DatePicker style={{ width: '100%' }} value={value as any} onChange={onChange} placeholder="日期" />
    case 'datetime':
      return <DatePicker showTime style={{ width: '100%' }} value={value as any} onChange={onChange} placeholder="日期时间" />
    case 'select':
    case 'multi_select': {
      const options = extractSelectOptions(field.config)
      return (
        <Select
          mode={ft === 'multi_select' ? 'multiple' : undefined}
          style={{ width: '100%' }}
          options={options}
          value={value as any}
          onChange={onChange}
          placeholder="请选择"
          allowClear
        />
      )
    }
    case 'long_text':
      return <Input.TextArea rows={3} value={value as string} onChange={e => onChange(e.target.value)} placeholder="请输入..." />
    case 'email':
      return <Input type="email" value={value as string} onChange={e => onChange(e.target.value)} placeholder="email@example.com" />
    case 'url':
      return <Input type="url" value={value as string} onChange={e => onChange(e.target.value)} placeholder="https://..." />
    case 'phone':
      return <Input value={value as string} onChange={e => onChange(e.target.value)} placeholder="手机号" />
    case 'json':
      return <Input.TextArea rows={3} value={typeof value === 'string' ? value : JSON.stringify(value ?? '', null, 2)} onChange={e => onChange(e.target.value)} placeholder="JSON" />
    default:
      return <Input value={value as string} onChange={e => onChange(e.target.value)} placeholder="请输入..." />
  }
}

function extractSelectOptions(config: unknown): Array<{ value: string; label: string }> {
  if (!config || typeof config !== 'object') return []
  const c = config as { options?: Array<{ value: string; label?: string }> | string[] }
  const opts = c.options || []
  if (opts.length === 0) return []
  if (typeof opts[0] === 'string') return (opts as string[]).map(v => ({ value: v, label: v }))
  return (opts as Array<{ value: string; label?: string }>).map(o => ({ value: o.value, label: o.label || o.value }))
}
