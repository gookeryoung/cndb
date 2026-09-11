import React, { useState } from 'react'
import { Drawer, Form, Input, Button, Typography, Timeline, Tag, message } from 'antd'
import { SaveOutlined, CommentOutlined, HistoryOutlined } from '@ant-design/icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { recordApi } from '@/api'
import type { RowResponse, Field, AuditLog, Comment as ApiComment } from '@/api'

const { Title } = Typography

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

  const { data: audit = [] } = useQuery<AuditLog[]>({
    queryKey: ['row-audit', wid, tid, row?.id],
    queryFn: () => recordApi.audit(wid, tid, { limit: 20 }),
    enabled: open && !!row,
  })

  const { data: comments = [] } = useQuery<ApiComment[]>({
    queryKey: ['row-comments', wid, tid],
    queryFn: () => recordApi.comments(wid, tid),
    enabled: open && !!row,
  })

  const updateRow = useMutation({
    mutationFn: () => recordApi.update(wid, tid, row!.id, { values }),
    onSuccess: () => {
      message.success('已保存')
      queryClient.invalidateQueries({ queryKey: ['table-records', `${wid}/${tid}`] })
    },
  })

  const addComment = useMutation({
    mutationFn: () => recordApi.addComment(wid, tid, commentText),
    onSuccess: () => {
      message.success('已评论')
      setCommentText('')
      queryClient.invalidateQueries({ queryKey: ['row-comments', wid, tid] })
    },
  })

  React.useEffect(() => {
    if (row) setValues(row || {})
  }, [row])

  if (!row) return null

  return (
    <Drawer
      title={`行详情 #${row.id}`} width={560} open={open} onClose={onClose}
      extra={
        <Button type="primary" icon={<SaveOutlined />} onClick={() => updateRow.mutate()} loading={updateRow.isPending}>保存</Button>
      }
    >
      <Title level={5}>字段值</Title>
      <Form layout="vertical">
        {fields.map(f => {
          const col = f.name
          return (
            <Form.Item key={String(f.id)} label={f.name} style={{ marginBottom: 12 }}>
              <Input
                value={String(values?.[col] ?? '')}
                onChange={(e) => setValues(v => ({ ...v, [col]: e.target.value }))}
              />
            </Form.Item>
          )
        })}
      </Form>

      <hr style={{ border: 'none', borderTop: '1px solid #f1f5f9', margin: '16px 0' }} />
      <Title level={5}><CommentOutlined /> 评论</Title>
      <Input.TextArea rows={2} placeholder="写点什么..." value={commentText}
        onChange={e => setCommentText(e.target.value)} />
      <div style={{ marginTop: 8, textAlign: 'right' }}>
        <Button type="primary" onClick={() => addComment.mutate()} loading={addComment.isPending}>发表</Button>
      </div>
      <div style={{ marginTop: 12 }}>
        {comments.map((c: ApiComment) => (
          <div key={c.id} style={{ padding: '8px 0', borderBottom: '1px solid #f1f5f9' }}>
            <strong>{c.author_name || '匿名'}</strong>
            <span style={{ color: '#94a3b8', marginLeft: 8, fontSize: 12 }}>{c.created_at || ''}</span>
            <div>{c.content}</div>
          </div>
        ))}
      </div>

      <hr style={{ border: 'none', borderTop: '1px solid #f1f5f9', margin: '16px 0' }} />
      <Title level={5}><HistoryOutlined /> 操作历史</Title>
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
    </Drawer>
  )
}
