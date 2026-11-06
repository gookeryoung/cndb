/** 修改申请详情页 — 对齐质量检查运行详情页：页头 + 概要条 + 左变更项 / 右审批与讨论.
 *
 * 数据源 changeRequestsApi.get（本体 + items[base_values/values/current_values/field_conflicts] + actions）。
 * 门控（前端仅隐藏入口，后端 403 兜底）：
 * - 合并/重开：工作区 owner/editor；
 * - 关闭：owner/editor 或提交人；
 * - update-base：提交人本人（stale 时刷新基准快照）。
 * queryKey 约定：['change-request', wid, tid, requestId]。
 */

import { useState } from 'react'
import type { ReactNode } from 'react'
import {
  Alert, App as AntApp, Button, Empty, Input, Segmented, Spin, Tag, Typography,
} from 'antd'
import {
  ArrowLeftOutlined, CheckOutlined, DeleteOutlined, EditOutlined, MessageOutlined,
  PlusCircleOutlined, PullRequestOutlined, RedoOutlined, SyncOutlined, TableOutlined,
} from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom'
import { FieldDiffTable } from '@/components/DiffView'
import { changeSummary } from '@/components/DiffView/FieldDiffTable'
import SectionBox from '@/components/SectionBox'
import { formatDateTime } from '@/utils/datetime'
import { changeRequestsApi, workspaceApi } from '@/api'
import { useTable } from '@/api/hooks'
import type { ChangeActionItem, ChangeItemDetail, ChangeOp, WorkspaceRole } from '@/api'
import { memberDisplayName, useMemberNameMap } from '@/hooks/useMemberNames'
import { useAuthStore } from '@/store'

const { Text, Paragraph } = Typography

type Decision = 'apply' | 'skip'

const OP_META: Record<ChangeOp, { label: string; icon: ReactNode; textType?: 'success' | 'danger' }> = {
  create: { label: '新增', icon: <PlusCircleOutlined />, textType: 'success' },
  update: { label: '修改', icon: <EditOutlined /> },
  delete: { label: '删除', icon: <DeleteOutlined />, textType: 'danger' },
}

const STATUS_META: Record<string, { label: string; color: string }> = {
  open: { label: '待审核', color: 'green' },
  merged: { label: '已合并', color: 'purple' },
  closed: { label: '已关闭', color: 'default' },
}

const ACTION_TEXT: Record<ChangeActionItem['action'], string> = {
  comment: '评论',
  merge: '合并了申请',
  close: '关闭了申请',
  reopen: '重开了申请',
  update_base: '刷新了基准快照',
}

/** 概要条单元格（与质量检查运行详情同款） */
function Stat({ label, value, tone }: { label: string; value: ReactNode; tone?: 'danger' | 'warning' }) {
  return (
    <div className="cn-qc-run-stat">
      <span className="cn-qc-run-stat-label">{label}</span>
      <Text strong type={tone} className="cn-qc-run-stat-value">{value}</Text>
    </div>
  )
}

export default function ChangeRequestDetailPage() {
  const { wid = '', tid = '', requestId = '' } = useParams<{ wid: string; tid: string; requestId: string }>()
  const navigate = useNavigate()
  const location = useLocation()
  const { message } = AntApp.useApp()
  const queryClient = useQueryClient()
  const user = useAuthStore(s => s.user)
  const nameById = useMemberNameMap(wid)
  const [commentDraft, setCommentDraft] = useState('')
  /** 逐项合并决策：itemId → apply/skip；仅记录用户显式选择，未选择的项在合并时默认 apply */
  const [decisions, setDecisions] = useState<Record<string, Decision>>({})
  const [mergeComment, setMergeComment] = useState('')

  const detailKey = ['change-request', wid, tid, requestId] as const

  const { data: cr, isLoading } = useQuery({
    queryKey: detailKey,
    queryFn: () => changeRequestsApi.get(wid, tid, requestId),
    enabled: !!wid && !!tid && !!requestId,
  })

  const { data: wsDetail } = useQuery({
    queryKey: ['workspace-detail', wid],
    queryFn: () => workspaceApi.get(wid),
    enabled: !!wid,
  })

  // 变更项的数据表引用：详情响应不含表名，复用表格页的 table 查询（queryKey 共享缓存）
  const { data: table } = useTable(wid, tid)

  const myRole = (wsDetail?.current_user_role ?? null) as WorkspaceRole | null
  const canReview = myRole === 'owner' || myRole === 'editor'
  const isSubmitter = !!user && cr?.submitted_by_id != null && String(cr.submitted_by_id) === String(user.id)

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: detailKey })
    queryClient.invalidateQueries({ queryKey: ['change-requests', wid, tid] })
    queryClient.invalidateQueries({ queryKey: ['pending-changes', `${wid}/${tid}`] })
    queryClient.invalidateQueries({ queryKey: ['table-records', `${wid}/${tid}`] })
  }

  const merge = useMutation({
    // 决策载荷以 cr.items 为准构建，用户显式选择（decisions）覆盖其上，未选择的项默认 apply
    mutationFn: () => changeRequestsApi.merge(wid, tid, requestId, {
      items: (cr?.items ?? []).map(it => ({
        item_id: it.id,
        action: decisions[String(it.id)] ?? 'apply' as Decision,
      })),
      comment: mergeComment.trim() || undefined,
    }),
    onSuccess: (res) => {
      message.success(`合并完成：应用 ${res.applied} 项，跳过 ${res.skipped} 项`)
      queryClient.setQueryData(detailKey, res.request)
      setMergeComment('')
      invalidate()
    },
    onError: (err) => message.error(err instanceof Error ? err.message : '合并失败'),
  })

  const close = useMutation({
    mutationFn: () => changeRequestsApi.close(wid, tid, requestId),
    onSuccess: (d) => {
      message.success('申请已关闭')
      queryClient.setQueryData(detailKey, d)
      invalidate()
    },
    onError: (err) => message.error(err instanceof Error ? err.message : '关闭失败'),
  })

  const reopen = useMutation({
    mutationFn: () => changeRequestsApi.reopen(wid, tid, requestId),
    onSuccess: (d) => {
      message.success('申请已重开')
      queryClient.setQueryData(detailKey, d)
      invalidate()
    },
    onError: (err) => message.error(err instanceof Error ? err.message : '重开失败'),
  })

  const updateBase = useMutation({
    mutationFn: () => changeRequestsApi.updateBase(wid, tid, requestId),
    onSuccess: (d) => {
      message.success('基准快照已刷新')
      queryClient.setQueryData(detailKey, d)
      invalidate()
    },
    onError: (err) => message.error(err instanceof Error ? err.message : '刷新基准失败'),
  })

  const addComment = useMutation({
    mutationFn: (content: string) => changeRequestsApi.addComment(wid, tid, requestId, content),
    onSuccess: () => {
      setCommentDraft('')
      invalidate()
    },
    onError: (err) => message.error(err instanceof Error ? err.message : '发表评论失败'),
  })

  const submitComment = () => {
    const content = commentDraft.trim()
    if (!content) return
    addComment.mutate(content)
  }

  const handleMerge = () => merge.mutate()

  if (isLoading) {
    return <div className="cn-page cn-state"><Spin /></div>
  }
  if (!cr) {
    return (
      <div className="cn-page cn-state">
        <Empty description="未找到该修改申请" />
      </div>
    )
  }

  const canMergeNow = canReview && cr.status === 'open'
  const showUpdateBase = isSubmitter && cr.status === 'open' && cr.stale
  const statusMeta = STATUS_META[cr.status] ?? { label: cr.status, color: 'default' }
  const tableName = table?.name || cr.table_name || `表 #${cr.table_id}`

  // 概要计数：操作类型分布 / 漂移字段（按字段去重）/ 讨论条数
  const driftFields = Array.from(new Set(cr.items.flatMap(it => it.field_conflicts)))
  const rowMissing = cr.items.some(it => it.row_missing)
  const opCount = (op: ChangeOp) => cr.items.filter(it => it.op === op).length

  // 非 open 时的处理信息：优先取审批字段，回退到最近一条处理动作
  const lastHandled = [...cr.actions]
    .reverse()
    .find(a => a.action === 'merge' || a.action === 'close' || a.action === 'reopen')
  const handledById = cr.reviewed_by_id ?? lastHandled?.acted_by_id ?? null
  const handledAt = cr.reviewed_at ?? lastHandled?.created_at ?? null
  const handledComment = cr.review_comment ?? lastHandled?.comment ?? null

  return (
    <div className="cn-page cn-qc-run-page" data-testid="change-request-detail">
      {/* ── 页头：申请标题 + 状态 / 元信息 + 操作（与运行详情页同款紧凑页头） ── */}
      <header className="cn-page-head">
        <div className="cn-page-head-main">
          <span className="cn-page-head-icon" aria-hidden><PullRequestOutlined /></span>
          <div className="cn-page-head-text">
            <h1 className="cn-page-head-title">{cr.title}</h1>
            <div className="cn-page-head-sub">
              <Tag color={statusMeta.color} style={{ marginInlineEnd: 0 }}>{statusMeta.label}</Tag>
              {cr.stale && <Tag color="warning" style={{ marginInlineEnd: 0 }}>基准已过期</Tag>}
              <span className="cn-page-head-meta">
                #{cr.id} · {memberDisplayName(nameById, cr.submitted_by_id, '未知')} 提交于 {formatDateTime(cr.created_at)}
              </span>
            </div>
          </div>
        </div>
        <div className="cn-page-head-actions">
          <Button
            icon={<ArrowLeftOutlined />}
            // 来源为工作区级分栏列表（需求 0107）时回到工作区列表，否则回单表列表
            onClick={() => navigate(
              (location.state as { from?: string } | null)?.from === 'workspace'
                ? `/w/${wid}/tables/change-requests`
                : `/w/${wid}/tables/${tid}/change-requests`,
            )}
          >
            返回修改申请
          </Button>
          {showUpdateBase && (
            <Button icon={<SyncOutlined />} loading={updateBase.isPending} onClick={() => updateBase.mutate()}>
              刷新基准快照
            </Button>
          )}
          {(canReview || isSubmitter) && cr.status === 'open' && (
            <Button onClick={() => close.mutate()} loading={close.isPending}>关闭申请</Button>
          )}
          {canReview && cr.status === 'closed' && (
            <Button icon={<RedoOutlined />} loading={reopen.isPending} onClick={() => reopen.mutate()}>
              重开申请
            </Button>
          )}
        </div>
      </header>

      {/* ── 告警区：基准过期 / 字段漂移 / 目标行缺失，运行式叠放 ── */}
      {cr.stale && (
        <Alert
          type="warning"
          showIcon
          title="基准已过期：提交后表内数据已变化，合并前请确认差异。"
        />
      )}
      {driftFields.length > 0 && (
        <Alert
          type="warning"
          showIcon
          title={`基准漂移字段：${driftFields.join('、')}`}
          description="这些字段的当前值与提交时基准不一致，合并将以当前值为准或按项跳过。"
        />
      )}
      {rowMissing && (
        <Alert
          type="error"
          showIcon
          title="存在目标行已删除的变更项"
          description="对应变更项落库时可能被跳过，请确认后处理。"
        />
      )}

      {/* ── 概要计数条：变更项 / 新增 / 修改 / 删除 / 漂移字段 / 讨论 ── */}
      <section className="cn-qc-run-summary" aria-label="申请概要" data-testid="cr-summary">
        <Stat label="变更项" value={cr.items.length} />
        <Stat label="新增" value={opCount('create')} />
        <Stat label="修改" value={opCount('update')} />
        <Stat label="删除" value={opCount('delete')} />
        <Stat label="漂移字段" value={driftFields.length} tone={driftFields.length ? 'warning' : undefined} />
        <Stat label="讨论" value={cr.actions.length} />
      </section>

      {/* ── 双栏：左=变更项（字段级 diff + 逐项决策），右=审批 + 讨论与动态 ── */}
      <div className="cn-cr-detail-split">
        <SectionBox
          title="变更项"
          icon={<PullRequestOutlined />}
          extra={(
            <span className="cn-cr-items-extra">
              <Link
                className="cn-cr-table-ref"
                to={`/w/${wid}/tables/${tid}`}
                title={`打开数据表：${tableName}`}
              >
                <TableOutlined aria-hidden />{tableName}
              </Link>
              <span>共 {cr.items.length} 项</span>
            </span>
          )}
          flush
          testId="cr-items-box"
        >
          {cr.description && (
            <Paragraph type="secondary" className="cn-cr-desc">{cr.description}</Paragraph>
          )}
          {cr.items.length === 0 ? (
            <div className="cn-qc-empty">
              <Empty description="没有变更项" />
            </div>
          ) : (
            cr.items.map((item: ChangeItemDetail) => (
              <div key={item.id} className="cn-cr-change-item">
                <div className="cn-cr-change-head">
                  <Text
                    type={OP_META[item.op].textType}
                    className={`cn-cr-op cn-cr-op--${item.op}`}
                  >
                    {OP_META[item.op].icon}
                    {OP_META[item.op].label}
                  </Text>
                  <Text type="secondary">
                    {item.row_id != null ? `行 #${item.row_id}` : '新增行'}
                  </Text>
                  <Text
                    type="secondary"
                    className="cn-cr-change-fields"
                    title={changeSummary(item)}
                  >
                    {changeSummary(item)}
                  </Text>
                  {item.row_missing && <Tag>行已删除</Tag>}
                  {item.field_conflicts.length > 0 && (
                    <Text type="danger" className="cn-cr-change-drift">
                      {item.field_conflicts.length} 个字段基准已漂移
                    </Text>
                  )}
                  <span className="cn-cr-change-decision">
                    {canMergeNow && (
                      <Segmented
                        size="small"
                        value={decisions[String(item.id)] ?? 'apply'}
                        onChange={(v) => setDecisions(prev => ({ ...prev, [String(item.id)]: v as Decision }))}
                        options={[
                          { label: '应用', value: 'apply' },
                          { label: '跳过', value: 'skip' },
                        ]}
                      />
                    )}
                  </span>
                </div>
                <div className="cn-cr-change-body">
                  <FieldDiffTable item={item} />
                </div>
              </div>
            ))
          )}
        </SectionBox>

        <div className="cn-cr-detail-side">
          <SectionBox
            title="审批"
            icon={<CheckOutlined />}
            testId="cr-approval-box"
          >
            {canMergeNow ? (
              <div className="cn-cr-approval-form">
                <Input.TextArea
                  rows={3}
                  value={mergeComment}
                  onChange={(e) => setMergeComment(e.target.value)}
                  placeholder="合并备注（可选，记录处理说明）"
                  maxLength={2000}
                />
                <Button
                  type="primary"
                  icon={<CheckOutlined />}
                  loading={merge.isPending}
                  onClick={handleMerge}
                >
                  执行合并
                </Button>
              </div>
            ) : cr.status === 'open' ? (
              <Text type="secondary">当前为只读预览，仅 owner/editor 可审批合并。</Text>
            ) : (
              <div className="cn-cr-approval-meta">
                <div className="cn-cr-approval-line">
                  <Text type="secondary">处理人</Text>
                  <Text>{handledById != null ? memberDisplayName(nameById, handledById, '未知') : '—'}</Text>
                </div>
                <div className="cn-cr-approval-line">
                  <Text type="secondary">处理时间</Text>
                  <Text>{handledAt ? formatDateTime(handledAt) : '—'}</Text>
                </div>
                <div className="cn-cr-approval-line">
                  <Text type="secondary">处理备注</Text>
                  <Text>{handledComment || '—'}</Text>
                </div>
              </div>
            )}
          </SectionBox>

          <SectionBox
            title="讨论与动态"
            icon={<MessageOutlined />}
            extra={<span>{cr.actions.length} 条</span>}
            flush
            testId="cr-discussion-box"
          >
            {cr.actions.length === 0 ? (
              <div className="cn-qc-empty">
                <Empty description="暂无动态" />
              </div>
            ) : (
              cr.actions.map((a: ChangeActionItem) => (
                <div key={a.id} className="cn-cr-action">
                  <Text type="secondary" className="cn-cr-action-meta">
                    <Text strong>{memberDisplayName(nameById, a.acted_by_id)}</Text>
                    {' '}{ACTION_TEXT[a.action] ?? a.action}
                    {a.comment && <>：<Text>{a.comment}</Text></>}
                    {' '}· {formatDateTime(a.created_at)}
                  </Text>
                </div>
              ))
            )}
            <div className="cn-cr-composer">
              <Input.TextArea
                rows={3}
                value={commentDraft}
                onChange={(e) => setCommentDraft(e.target.value)}
                placeholder="写下评论…"
                maxLength={2000}
              />
              <Button
                type="primary"
                disabled={!commentDraft.trim()}
                loading={addComment.isPending}
                onClick={submitComment}
              >
                发表评论
              </Button>
            </div>
          </SectionBox>
        </div>
      </div>
    </div>
  )
}
