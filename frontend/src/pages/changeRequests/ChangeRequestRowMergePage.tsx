/** 行组冲突处理页 — 同一行多份 open 申请的冲突字段逐字段裁决后批量落库.
 *
 * 路由：/w/:wid/tables/:tid/change-requests/rows/:rowId/merge?ids=51,53
 * 数据源：
 * - changeRequestsApi.listGrouped(open) 取行组（row_values/conflict_fields/drift_fields/row_missing）；
 * - changeRequestsApi.get 取选中申请详情（items 提供字段写者 item_id 与基准值）；
 * 提交：changeRequestsApi.mergeRow（resolutions 逐字段裁决 + row_action 处理 delete 互斥）。
 * 参考 git merge：无冲突字段自动应用（只读汇总预览），冲突字段必须显式裁决，不静默覆盖。
 */

import { useMemo, useState } from 'react'
import {
  Alert, App as AntApp, Button, Card, Divider, Empty, Input, Radio, Space, Spin, Table, Tag, Typography,
} from 'antd'
import { ArrowLeftOutlined, CheckOutlined } from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { FieldDiffTable } from '@/components/DiffView'
import { changeRequestsApi, workspaceApi } from '@/api'
import type { ChangeItemDetail, CRResolution, ID, WorkspaceRole } from '@/api'

const { Text, Title, Paragraph } = Typography

type RowAction = 'keep' | 'delete'

interface Writer { request_id: ID; item_id: ID; value: unknown }

/** 值 → 可读文本（对象/数组走 JSON） */
function displayValue(v: unknown): string {
  if (v == null || v === '') return '（空）'
  if (typeof v === 'object') return JSON.stringify(v)
  return String(v)
}

export default function ChangeRequestRowMergePage() {
  const { wid = '', tid = '', rowId = '' } = useParams<{ wid: string; tid: string; rowId: string }>()
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const { message } = AntApp.useApp()
  const queryClient = useQueryClient()

  const requestIds = useMemo(
    () => (searchParams.get('ids') ?? '').split(',').map(s => s.trim()).filter(Boolean),
    [searchParams],
  )
  const idsKey = requestIds.join(',')

  const listUrl = `/w/${wid}/tables/${tid}/change-requests`

  const { data: groupPage, isLoading: groupLoading } = useQuery({
    queryKey: ['change-requests', wid, tid, 'open', 'row'],
    queryFn: () => changeRequestsApi.listGrouped(wid, tid, 'open'),
    enabled: !!wid && !!tid,
  })
  const group = groupPage?.groups.find(g => String(g.row_id) === rowId)

  const { data: details = [], isLoading: detailLoading } = useQuery({
    queryKey: ['change-request-row-merge', wid, tid, rowId, idsKey],
    queryFn: () => Promise.all(requestIds.map(id => changeRequestsApi.get(wid, tid, id))),
    enabled: !!wid && !!tid && requestIds.length > 0,
  })

  const { data: wsDetail } = useQuery({
    queryKey: ['workspace-detail', wid],
    queryFn: () => workspaceApi.get(wid),
    enabled: !!wid,
  })
  const myRole = (wsDetail?.current_user_role ?? null) as WorkspaceRole | null
  const canReview = myRole === 'owner' || myRole === 'editor'

  const conflictFields = useMemo(() => group?.conflict_fields ?? [], [group])
  const rowValues = useMemo(() => group?.row_values ?? {}, [group])

  /** 冲突字段 → 各写者（request_id, item_id, value）：来自选中申请详情的 update items */
  const writersByField = useMemo(() => {
    const acc: Record<string, Writer[]> = {}
    for (const detail of details) {
      for (const item of detail.items) {
        if (item.op !== 'update') continue
        for (const [f, v] of Object.entries(item.values)) {
          if (!conflictFields.includes(f)) continue
          if (!acc[f]) acc[f] = []
          acc[f].push({ request_id: detail.id, item_id: item.id, value: v })
        }
      }
    }
    return acc
  }, [details, conflictFields])

  /** 是否存在 delete 互斥（选中申请既有 delete 又有 update 项） */
  const hasDelete = details.some(d => d.items.some(it => it.op === 'delete'))
  const hasUpdate = details.some(d => d.items.some(it => it.op === 'update'))
  const rowOpConflict = hasDelete && hasUpdate

  const [resolutions, setResolutions] = useState<Record<string, CRResolution>>({})
  const [rowAction, setRowAction] = useState<RowAction>('keep')
  const [comment, setComment] = useState('')

  const setResolution = (field: string, res: CRResolution) =>
    setResolutions(prev => ({ ...prev, [field]: res }))

  /** 快捷：全部采用最新提交申请的值（每字段取 created_at 最新的写者） */
  const pickLatest = () => {
    const next: Record<string, CRResolution> = {}
    for (const f of conflictFields) {
      const writers = writersByField[f] ?? []
      if (writers.length === 0) continue
      const latest = writers
        .map(w => ({ w, detail: details.find(d => d.id === w.request_id) }))
        .sort((a, b) => (b.detail?.created_at ?? '').localeCompare(a.detail?.created_at ?? ''))[0].w
      next[f] = { strategy: 'item', item_id: latest.item_id }
    }
    setResolutions(next)
  }
  /** 快捷：全部保留当前值（冲突字段跳过写入） */
  const keepAll = () => {
    const next: Record<string, CRResolution> = {}
    for (const f of conflictFields) next[f] = { strategy: 'current' }
    setResolutions(next)
  }

  const merge = useMutation({
    mutationFn: () => changeRequestsApi.mergeRow(wid, tid, rowId, {
      request_ids: requestIds.map(Number),
      resolutions,
      row_action: rowOpConflict ? rowAction : undefined,
      comment: comment.trim() || undefined,
    }),
    onSuccess: (res) => {
      message.success(`批量合并完成：应用 ${res.applied} 项，跳过 ${res.skipped} 项`)
      queryClient.invalidateQueries({ queryKey: ['change-requests', wid, tid] })
      queryClient.invalidateQueries({ queryKey: ['pending-changes', `${wid}/${tid}`] })
      queryClient.invalidateQueries({ queryKey: ['table-records', `${wid}/${tid}`] })
      navigate(listUrl)
    },
    onError: (err) => message.error(err instanceof Error ? err.message : '批量合并失败'),
  })

  /** 提交前校验：冲突字段均已裁决 */
  const unresolved = conflictFields.filter(f => !resolutions[f])
  const canSubmit = canReview && unresolved.length === 0 && requestIds.length > 0 && !merge.isPending

  if (groupLoading || detailLoading) {
    return <div style={{ padding: 48, textAlign: 'center' }}><Spin /></div>
  }
  if (!group) {
    return <div style={{ padding: 24 }}><Empty description="未找到该行的待审申请" /></div>
  }

  /** 非冲突字段自动应用汇总（单一写者或写入值一致） */
  const autoFields = new Map<string, unknown>()
  for (const [f, writers] of Object.entries(writersByField)) {
    if (conflictFields.includes(f) && writers.length > 1) continue
    autoFields.set(f, writers[0].value)
  }

  return (
    <div style={{ padding: '16px 24px', maxWidth: 860, margin: '0 auto' }}>
      <Button type="text" icon={<ArrowLeftOutlined />} onClick={() => navigate(listUrl)} style={{ marginBottom: 8 }}>
        返回修改申请
      </Button>

      <Title level={4} style={{ marginBottom: 8 }}>冲突处理 · 行 #{group.row_id}</Title>
      {group.row_missing && (
        <Alert type="warning" showIcon style={{ marginBottom: 12 }} message="目标行已删除：本行变更可能无法落库，请确认后处理。" />
      )}
      {!canReview && (
        <Alert type="info" showIcon style={{ marginBottom: 12 }} message="仅 owner/editor 可处理并合并冲突，当前为只读预览。" />
      )}

      {/* 1. 行摘要（ours：当前值） */}
      <Card size="small" title="当前行值（当前基准）" style={{ marginBottom: 12 }}>
        <Table
          size="small"
          pagination={false}
          rowKey="field"
          dataSource={Object.entries(rowValues).map(([field, value]) => ({ field, value }))}
          columns={[
            { title: '字段', dataIndex: 'field', width: 180 },
            { title: '当前值', dataIndex: 'value', render: (v: unknown) => displayValue(v) },
          ]}
          locale={{ emptyText: '（行值不可用）' }}
        />
      </Card>

      {/* 2. 待合并申请（theirs） */}
      <Card size="small" title={`待合并申请（${details.length}）`} style={{ marginBottom: 12 }}>
        {details.map(d => (
          <div key={d.id} style={{ marginBottom: 8 }}>
            <Space size={8} wrap style={{ marginBottom: 4 }}>
              <Text strong>#{d.id}</Text>
              <Text strong>{d.title}</Text>
              <Text type="secondary">{d.created_at ?? ''}</Text>
            </Space>
            {d.items.map((item: ChangeItemDetail) => (
              <FieldDiffTable key={item.id} item={item} />
            ))}
          </div>
        ))}
      </Card>

      {/* 3. 冲突字段裁决表 */}
      <Card size="small" style={{ marginBottom: 12 }}
        title={<Space size={8}>冲突字段裁决{conflictFields.length > 0 && <Tag color="red">{conflictFields.length}</Tag>}</Space>}
        extra={canReview && conflictFields.length > 0 && (
          <Space size={8}>
            <Button size="small" onClick={pickLatest}>全部采用最新</Button>
            <Button size="small" onClick={keepAll}>全部保留当前</Button>
          </Space>
        )}
      >
        {conflictFields.length === 0 ? (
          <Text type="secondary">无字段级冲突，将自动合并。</Text>
        ) : conflictFields.map(f => (
          <div key={f} style={{ marginBottom: 12 }}>
            <Text strong>{f}</Text>
            <Text type="secondary"> · 当前值：{displayValue(rowValues[f])}</Text>
            <Radio.Group
              style={{ display: 'block', marginTop: 6 }}
              value={resolutions[f]
                ? (resolutions[f].strategy === 'current' ? 'current' : `item:${resolutions[f].item_id}`)
                : ''}
              onChange={(e) => {
                const val = String(e.target.value)
                if (val === 'current') setResolution(f, { strategy: 'current' })
                else setResolution(f, { strategy: 'item', item_id: Number(val.split(':')[1]) })
              }}
            >
              <Space direction="vertical" size={4}>
                {(writersByField[f] ?? []).map(w => (
                  <Radio key={w.item_id} value={`item:${w.item_id}`}>
                    <Text>采用 #{w.request_id} 的值：</Text>
                    <Text code>{displayValue(w.value)}</Text>
                  </Radio>
                ))}
                <Radio value="current">
                  <Text>保留当前值：{displayValue(rowValues[f])}</Text>
                </Radio>
              </Space>
            </Radio.Group>
          </div>
        ))}
      </Card>

      {/* 4. 非冲突字段自动应用预览 */}
      {autoFields.size > 0 && (
        <Card size="small" title="自动应用字段（无冲突）" style={{ marginBottom: 12 }}>
          {Array.from(autoFields.entries()).map(([f, v]) => (
            <div key={f}>
              <Text type="secondary">{f}：</Text> <Text code>{displayValue(v)}</Text>
            </div>
          ))}
        </Card>
      )}

      {/* 5. 行级 op 互斥裁决（delete vs 修改） */}
      {rowOpConflict && (
        <Card size="small" style={{ marginBottom: 12 }}
          title={<Space size={8}>行级操作裁决 <Tag color="red">删除与修改互斥</Tag></Space>}
        >
          <Radio.Group value={rowAction} onChange={(e) => setRowAction(e.target.value as RowAction)}>
            <Space direction="vertical">
              <Radio value="keep">保留行，应用修改（忽略删除）</Radio>
              <Radio value="delete">执行删除（忽略修改）</Radio>
            </Space>
          </Radio.Group>
        </Card>
      )}

      {/* 6. 备注 + 执行 */}
      <Divider />
      <Input.TextArea
        rows={2}
        value={comment}
        onChange={(e) => setComment(e.target.value)}
        placeholder="合并备注（可选，记录处理说明）"
        maxLength={2000}
      />
      {unresolved.length > 0 && (
        <Paragraph type="danger" style={{ marginTop: 8, marginBottom: 0 }}>
          请先裁决冲突字段：{unresolved.join('、')}
        </Paragraph>
      )}
      <Button
        type="primary"
        icon={<CheckOutlined />}
        style={{ marginTop: 8 }}
        disabled={!canSubmit}
        loading={merge.isPending}
        onClick={() => merge.mutate()}
      >
        执行批量合并
      </Button>
    </div>
  )
}
