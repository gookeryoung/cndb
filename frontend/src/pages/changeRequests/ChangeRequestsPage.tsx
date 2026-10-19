/** 修改申请列表页 — scope 筛选（待审核/已合并/全部/我的）+ 视图切换（同行合并/平铺）+ 批量审批 + 写模式权限标注.
 *
 * 数据源 changeRequestsApi：
 * - 同行合并视图（scope=open 时默认）：listGrouped（group_by=row），按目标行聚合行组，组间/组内按时间倒序；
 *   reviewer 可勾选组内多份申请后「批量审批」——无冲突直接批量 merge，有冲突跳转冲突处理页。
 * - 平铺视图：list（scope 查询参数），维持旧契约（历史留痕用，merged/closed 视图恒为平铺）。
 * 响应附带 write_mode（direct/change_request/denied，与写路径双轨分派同源）。
 * queryKey 约定：平铺 ['change-requests', wid, tid, scope]；分组 ['change-requests', wid, tid, scope, 'row']。
 */

import { useMemo, useState } from 'react'
import {
  Alert, App as AntApp, Badge, Button, Card, Checkbox, Empty, List, Segmented, Space, Spin, Tag, Typography,
} from 'antd'
import { CheckOutlined, PlusOutlined } from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate, useParams } from 'react-router-dom'
import { formatDateTime } from '@/utils/datetime'
import { changeRequestsApi, workspaceApi } from '@/api'
import type { ChangeRequest, ChangeRowGroup, TableWriteMode, WorkspaceRole } from '@/api'
import { memberDisplayName, useMemberNameMap } from '@/hooks/useMemberNames'

const { Text } = Typography

type Scope = 'open' | 'merged' | 'all' | 'mine'
type View = 'grouped' | 'flat'

const SCOPE_OPTIONS: Array<{ label: string; value: Scope }> = [
  { label: '待审核', value: 'open' },
  { label: '已合并', value: 'merged' },
  { label: '全部', value: 'all' },
  { label: '我的', value: 'mine' },
]

const VIEW_OPTIONS: Array<{ label: string; value: View }> = [
  { label: '同行合并', value: 'grouped' },
  { label: '平铺', value: 'flat' },
]

const STATUS_META: Record<ChangeRequest['status'], { label: string; color: string }> = {
  open: { label: '待审核', color: 'green' },
  merged: { label: '已合并', color: 'purple' },
  closed: { label: '已关闭', color: 'default' },
}

/** 写模式 → 列表头部权限标注（type 直接复用 AntD Alert 语义色） */
const WRITE_MODE_BANNER: Record<TableWriteMode, { type: 'success' | 'info' | 'warning'; label: string; message: string }> = {
  direct: {
    type: 'success',
    label: '直编模式',
    message: '当前账号可直接在表格中修改数据：编辑立即生效，不会自动生成修改申请。',
  },
  change_request: {
    type: 'info',
    label: '申请模式',
    message: '在表格中编辑数据会自动生成修改申请，经审批合并后生效。',
  },
  denied: {
    type: 'warning',
    label: '只读',
    message: '当前账号对该表无编辑权限，写操作将被拒绝。',
  },
}

/** 新建修改申请按钮的引导文案（按写模式适配，消除提示与实际行为矛盾） */
function newRequestHint(writeMode: TableWriteMode): string {
  if (writeMode === 'direct') {
    return '当前账号具备直接修改权限：在表格中编辑会直接生效，不会自动生成修改申请。'
  }
  if (writeMode === 'denied') {
    return '当前账号对该表只读，无法提交数据变更。'
  }
  return '请直接在表格中编辑数据，系统会自动生成修改申请'
}

/** 行值预览：取前若干字段拼为紧凑文本（避免整行值溢出卡片标题） */
function rowPreview(values: Record<string, unknown>, max = 3): string {
  const entries = Object.entries(values).filter(([, v]) => v != null && v !== '')
  if (entries.length === 0) return ''
  return entries.slice(0, max).map(([k, v]) => `${k}: ${String(v)}`).join(' · ')
}

/** 单条申请行（组内/平铺共用渲染） */
function RequestLine({
  item, nameById, showStatus, selected, onToggleSelect, onClick,
}: {
  item: ChangeRequest
  nameById: Map<string, string>
  showStatus: boolean
  selected?: boolean
  onToggleSelect?: (checked: boolean) => void
  onClick: () => void
}) {
  return (
    <List.Item
      style={{ cursor: 'pointer', paddingInline: 8 }}
      onClick={onClick}
      extra={onToggleSelect ? (
        // 阻止勾选冒泡触发整行导航
        <span onClick={(e) => e.stopPropagation()}>
          <Checkbox checked={!!selected} onChange={(e) => onToggleSelect(e.target.checked)} />
        </span>
      ) : undefined}
    >
      <List.Item.Meta
        title={(
          <Space size={8} wrap>
            {showStatus && (
              <Tag color={STATUS_META[item.status].color} style={{ marginInlineEnd: 0 }}>
                {STATUS_META[item.status].label}
              </Tag>
            )}
            <Text strong>{item.title}</Text>
            {item.stale && <Tag color="warning" style={{ marginInlineEnd: 0 }}>基准已过期</Tag>}
            {(item.conflicts_count ?? 0) > 0 && (
              <Tag color="orange" style={{ marginInlineEnd: 0 }}>与 {item.conflicts_count} 行待审批申请冲突</Tag>
            )}
          </Space>
        )}
        description={(
          <Text type="secondary">
            #{item.id} · {memberDisplayName(nameById, item.submitted_by_id, '未知')} 提交于 {formatDateTime(item.created_at)}
          </Text>
        )}
      />
    </List.Item>
  )
}

export default function ChangeRequestsPage() {
  const { wid = '', tid = '' } = useParams<{ wid: string; tid: string }>()
  const navigate = useNavigate()
  const { message, modal } = AntApp.useApp()
  const queryClient = useQueryClient()
  const [scope, setScope] = useState<Scope>('open')
  const [view, setView] = useState<View>('grouped')
  const nameById = useMemberNameMap(wid)

  // 分组视图仅在「待审核」且选择同行合并时启用（历史/我的/全部维持平铺）
  const groupedMode = scope === 'open' && view === 'grouped'

  const flatQuery = useQuery({
    queryKey: ['change-requests', wid, tid, scope],
    queryFn: () => changeRequestsApi.list(wid, tid, scope),
    enabled: !!wid && !!tid && !groupedMode,
  })

  const groupedQuery = useQuery({
    queryKey: ['change-requests', wid, tid, scope, 'row'],
    queryFn: () => changeRequestsApi.listGrouped(wid, tid, scope),
    enabled: !!wid && !!tid && groupedMode,
  })

  const { data: wsDetail } = useQuery({
    queryKey: ['workspace-detail', wid],
    queryFn: () => workspaceApi.get(wid),
    enabled: !!wid,
  })
  const myRole = (wsDetail?.current_user_role ?? null) as WorkspaceRole | null
  const canReview = myRole === 'owner' || myRole === 'editor'

  /** 行组勾选：rowId → 选中的申请 id 集合 */
  const [selected, setSelected] = useState<Record<string, Set<string>>>({})

  const toggleSelect = (rowId: string, requestId: string, checked: boolean) => {
    setSelected(prev => {
      const next = { ...prev }
      const set = new Set(next[rowId] ?? [])
      if (checked) set.add(requestId)
      else set.delete(requestId)
      if (set.size === 0) delete next[rowId]
      else next[rowId] = set
      return next
    })
  }

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['change-requests', wid, tid] })
    queryClient.invalidateQueries({ queryKey: ['pending-changes', `${wid}/${tid}`] })
    queryClient.invalidateQueries({ queryKey: ['table-records', `${wid}/${tid}`] })
  }

  const mergeRow = useMutation({
    mutationFn: (vars: { rowId: string; requestIds: string[] }) =>
      changeRequestsApi.mergeRow(wid, tid, vars.rowId, { request_ids: vars.requestIds.map(Number) }),
    onSuccess: (res) => {
      message.success(`批量审批完成：应用 ${res.applied} 项，跳过 ${res.skipped} 项`)
      setSelected({})
      invalidate()
    },
    onError: (err) => message.error(err instanceof Error ? err.message : '批量审批失败'),
  })

  /** 批量审批：无冲突直接合并；有冲突跳转冲突处理页（携带选中申请 id） */
  const handleBatchApprove = (group: ChangeRowGroup) => {
    const requestIds = Array.from(selected[String(group.row_id)] ?? [])
    if (requestIds.length === 0) return
    if (group.has_conflict || group.row_missing) {
      navigate(`/w/${wid}/tables/${tid}/change-requests/rows/${group.row_id}/merge?ids=${requestIds.join(',')}`)
      return
    }
    modal.confirm({
      title: '批量审批',
      content: `确认合并行 #${group.row_id} 的 ${requestIds.length} 份申请？无冲突字段将自动应用。`,
      okText: '确认合并',
      cancelText: '取消',
      onOk: () => mergeRow.mutate({ rowId: String(group.row_id), requestIds }),
    })
  }

  const openNewDialog = () => {
    // 新建修改申请入口：写路径（单元格/行详情/批量删除）已按双轨自动分派，
    // 提示按当前写模式适配 —— 直编用户明确告知"编辑直接生效、不会生成申请"
    message.info(newRequestHint(writeMode))
  }

  // 旧响应无 write_mode 时按申请模式兜底（与 viewer 工况一致）
  const writeMode: TableWriteMode =
    (groupedMode ? groupedQuery.data?.write_mode : flatQuery.data?.write_mode) ?? 'change_request'
  const banner = WRITE_MODE_BANNER[writeMode]

  const isLoading = groupedMode ? groupedQuery.isLoading : flatQuery.isLoading

  const groups = groupedQuery.data?.groups ?? []
  const ungrouped = groupedQuery.data?.ungrouped ?? []
  const flatItems = flatQuery.data?.items ?? []
  const isEmpty = groupedMode ? groups.length === 0 && ungrouped.length === 0 : flatItems.length === 0

  const goDetail = (reqId: ChangeRequest['id']) =>
    navigate(`/w/${wid}/tables/${tid}/change-requests/${reqId}`)

  const selectedCountByRow = useMemo(() => {
    const m: Record<string, number> = {}
    for (const [rowId, set] of Object.entries(selected)) m[rowId] = set.size
    return m
  }, [selected])

  return (
    <div style={{ padding: '16px 24px', maxWidth: 860, margin: '0 auto' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16, gap: 12, flexWrap: 'wrap' }}>
        <Space size={12} wrap>
          <Segmented options={SCOPE_OPTIONS} value={scope} onChange={(v) => { setScope(v as Scope); setSelected({}) }} />
          {scope === 'open' && (
            <Segmented options={VIEW_OPTIONS} value={view} onChange={(v) => { setView(v as View); setSelected({}) }} />
          )}
        </Space>
        <Button type="primary" icon={<PlusOutlined />} onClick={openNewDialog}>新建修改申请</Button>
      </div>

      <Alert
        type={banner.type}
        showIcon
        style={{ marginBottom: 16 }}
        message={(
          <Space size={8} wrap>
            <Tag color={banner.type === 'success' ? 'green' : banner.type === 'warning' ? 'default' : 'blue'} style={{ marginInlineEnd: 0 }}>
              {banner.label}
            </Tag>
            <Text type="secondary">{banner.message}</Text>
          </Space>
        )}
      />

      <Spin spinning={isLoading}>
        {isEmpty ? (
          <Empty description="暂无修改申请" style={{ padding: 48 }} />
        ) : groupedMode ? (
          <Space direction="vertical" size={12} style={{ display: 'flex' }}>
            {groups.map((group: ChangeRowGroup) => {
              const rowId = String(group.row_id)
              const count = selectedCountByRow[rowId] ?? 0
              const preview = rowPreview(group.row_values)
              return (
                <Card
                  key={rowId}
                  size="small"
                  title={(
                    <Space size={8} wrap>
                      <Text strong>行 #{group.row_id}</Text>
                      {preview && <Text type="secondary" style={{ fontWeight: 'normal' }}>{preview}</Text>}
                      <Badge count={group.requests.length} color="blue" title="待审申请数" />
                      {group.has_conflict && <Tag color="red" style={{ marginInlineEnd: 0 }}>冲突</Tag>}
                      {group.has_drift && <Tag color="orange" style={{ marginInlineEnd: 0 }}>基准漂移</Tag>}
                      {group.row_missing && <Tag color="default" style={{ marginInlineEnd: 0 }}>行已删除</Tag>}
                    </Space>
                  )}
                  extra={canReview && (
                    <Button
                      type="primary"
                      size="small"
                      icon={<CheckOutlined />}
                      disabled={count === 0}
                      loading={mergeRow.isPending && count > 0}
                      onClick={() => handleBatchApprove(group)}
                    >
                      批量审批{count > 0 ? `（${count}）` : ''}
                    </Button>
                  )}
                >
                  {(group.conflict_fields.length > 0 || group.drift_fields.length > 0) && (
                    <div style={{ marginBottom: 8 }}>
                      {group.conflict_fields.length > 0 && (
                        <Text type="danger" style={{ fontSize: 12, display: 'block' }}>
                          冲突字段：{group.conflict_fields.join('、')}
                        </Text>
                      )}
                      {group.drift_fields.length > 0 && (
                        <Text type="warning" style={{ fontSize: 12, display: 'block' }}>
                          基准漂移字段：{group.drift_fields.join('、')}
                        </Text>
                      )}
                    </div>
                  )}
                  <List
                    size="small"
                    dataSource={group.requests}
                    renderItem={(item: ChangeRequest) => (
                      <RequestLine
                        item={item}
                        nameById={nameById}
                        showStatus={false}
                        selected={selected[rowId]?.has(String(item.id))}
                        onToggleSelect={canReview ? (checked) => toggleSelect(rowId, String(item.id), checked) : undefined}
                        onClick={() => goDetail(item.id)}
                      />
                    )}
                  />
                </Card>
              )
            })}
            {ungrouped.length > 0 && (
              <Card size="small" title={<Text strong>新增行申请</Text>}>
                <List
                  size="small"
                  dataSource={ungrouped}
                  renderItem={(item: ChangeRequest) => (
                    <RequestLine item={item} nameById={nameById} showStatus={false} onClick={() => goDetail(item.id)} />
                  )}
                />
              </Card>
            )}
          </Space>
        ) : (
          <List
            dataSource={flatItems}
            renderItem={(item: ChangeRequest) => (
              <RequestLine
                item={item}
                nameById={nameById}
                showStatus={scope !== 'open'}
                onClick={() => goDetail(item.id)}
              />
            )}
          />
        )}
      </Spin>
    </div>
  )
}
