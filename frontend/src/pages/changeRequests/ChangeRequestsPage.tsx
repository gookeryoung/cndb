/** 修改申请列表页 — 对齐质量检查页的 GitHub 式双栏与方盒语言.
 *
 * 数据源 changeRequestsApi：
 * - 工作区级（无 :tid，数据表模块「修改申请」页签）：左右分栏（需求 0107）——左栏为涉及的
 *   工作表清单（按 table_id 分组 + 申请计数），右栏为选中表的修改项列表；每条修改项支持展开，
 *   懒加载详情（items 的 base_values/values/current_values 三态 + 当前行上下文），只读展示，
 *   审批入口仍跳详情页。
 * - 单表视图（有 :tid）：同行合并视图（scope=open 时默认）listGrouped（group_by=row），
 *   左栏按目标行聚合为「行分组」，右栏展示选中分组的申请清单；reviewer 可勾选组内多份申请后
 *   「批量审批」——无冲突直接批量 merge，有冲突跳转冲突处理页。平铺视图（list）维持旧契约，
 *   历史留痕用；merged/closed 视图恒为平铺。
 * - 页面骨架与质量检查页同款：cn-page 紧凑页头 + SectionBox 双栏 + cn-qc-row 行态；
 *   详情页沿用同一套页头 / 方盒语言。
 * 响应附带 write_mode（direct/change_request/denied，与写路径双轨分派同源）。
 * queryKey 约定：平铺 ['change-requests', wid, tid, scope]；分组 ['change-requests', wid, tid, scope, 'row']；
 * 展开详情复用详情页 queryKey ['change-request', wid, tid, requestId]。
 */

import { useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import {
  Alert, App as AntApp, Badge, Button, Checkbox, Empty, Segmented, Space, Spin, Tag, Typography,
} from 'antd'
import {
  CheckOutlined, PlusOutlined, PullRequestOutlined, RightOutlined, TableOutlined, UnorderedListOutlined,
} from '@ant-design/icons'
import { FieldDiffTable } from '@/components/DiffView'
import { changeSummary, formatValue } from '@/components/DiffView/FieldDiffTable'
import SectionBox from '@/components/SectionBox'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate, useParams } from 'react-router-dom'
import { formatDateTime } from '@/utils/datetime'
import { changeRequestsApi, workspaceApi } from '@/api'
import type {
  ChangeItemDetail, ChangeRequest, ChangeRowGroup, ID, TableWriteMode, WorkspaceRole,
} from '@/api'
import { memberDisplayName, useMemberNameMap } from '@/hooks/useMemberNames'

const { Text, Paragraph } = Typography

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

/** 变更项操作类型 → 标签（与详情页口径一致） */
const OP_META: Record<ChangeItemDetail['op'], { label: string; color: string }> = {
  create: { label: '新增', color: 'green' },
  update: { label: '修改', color: 'blue' },
  delete: { label: '删除', color: 'red' },
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

/** 行值预览：取前若干字段拼为紧凑文本（避免整行值溢出左侧分组行） */
function rowPreview(values: Record<string, unknown>, max = 3): string {
  const entries = Object.entries(values).filter(([, v]) => v != null && v !== '')
  if (entries.length === 0) return ''
  return entries.slice(0, max).map(([k, v]) => `${k}: ${String(v)}`).join(' · ')
}

/** 申请行的标签 / 元信息摘要（列表与分组视图共用） */
function RequestTags({
  item, showStatus, tableName,
}: {
  item: ChangeRequest
  showStatus: boolean
  tableName?: string
}) {
  return (
    <span className="cn-cr-tags">
      {showStatus && (
        <Tag color={STATUS_META[item.status].color}>{STATUS_META[item.status].label}</Tag>
      )}
      {tableName && <Tag color="blue">表：{tableName}</Tag>}
      <Text strong className="cn-cr-item-title">{item.title}</Text>
      {item.stale && <Tag color="warning">基准已过期</Tag>}
      {(item.conflicts_count ?? 0) > 0 && (
        <Tag color="orange">与 {item.conflicts_count} 行待审批申请冲突</Tag>
      )}
      {item.item_count != null && item.item_count > 1 && (
        <Tag>{item.item_count} 个变更项</Tag>
      )}
    </span>
  )
}

/** 单条申请行（工作区级 / 分组 / 平铺共用） */
function RequestRow({
  item, nameById, showStatus, selected, onToggleSelect, onClick, tableName,
  expanded, onToggleExpand, children,
}: {
  item: ChangeRequest
  nameById: Map<string, string>
  showStatus: boolean
  selected?: boolean
  onToggleSelect?: (checked: boolean) => void
  onClick: () => void
  /** 工作区级 / 平铺列表：标明申请所属数据表 */
  tableName?: string
  /** 工作区级列表：行尾展开 caret 与展开区 */
  expanded?: boolean
  onToggleExpand?: () => void
  children?: ReactNode
}) {
  return (
    <div className="cn-cr-item-wrap">
      <div className="cn-list-item cn-cr-item" onClick={onClick}>
        {onToggleSelect ? (
          // 阻止勾选冒泡触发整行导航
          <div className="cn-list-item-actions" onClick={(e) => e.stopPropagation()}>
            <Checkbox
              checked={!!selected}
              aria-label={`选择申请 #${item.id}`}
              onChange={(e) => onToggleSelect(e.target.checked)}
            />
          </div>
        ) : undefined}
        <div className="cn-cr-item-main">
          <div className="cn-cr-item-line">
            <RequestTags item={item} showStatus={showStatus} tableName={tableName} />
            <span
              className="cn-cr-item-meta"
              title={`#${item.id} · ${memberDisplayName(nameById, item.submitted_by_id, '未知')} 提交于 ${formatDateTime(item.created_at)}`}
            >
              #{item.id} · {memberDisplayName(nameById, item.submitted_by_id, '未知')} 提交于 {formatDateTime(item.created_at)}
              {item.fields && item.fields.length > 0 ? ` · 涉及字段：${item.fields.join('、')}` : ''}
            </span>
          </div>
        </div>
        {onToggleExpand ? (
          <button
            type="button"
            className="cn-qc-run-caret-btn"
            aria-expanded={expanded}
            aria-label={expanded ? '收起详情' : '展开详情'}
            onClick={(event) => {
              event.stopPropagation()
              onToggleExpand()
            }}
          >
            <RightOutlined className={`cn-qc-run-caret${expanded ? ' is-open' : ''}`} aria-hidden />
          </button>
        ) : undefined}
      </div>
      {expanded ? children : null}
    </div>
  )
}

/** 当前行上下文：列出整行所有字段值（修改涉及的字段加粗），便于理解行全貌 */
function RowContextValues({ item }: { item: ChangeItemDetail }) {
  const entries = Object.entries(item.current_values ?? {})
  if (entries.length === 0) return null
  const involved = new Set([...Object.keys(item.base_values), ...Object.keys(item.values)])
  return (
    <div className="cn-cr-rowcontext">
      <Text type="secondary" className="cn-cr-rowcontext-label">当前行上下文（{entries.length} 个字段）：</Text>
      <div className="cn-cr-rowcontext-grid">
        {entries.map(([k, v]) => (
          <span key={k} className={involved.has(k) ? 'cn-cr-rowcontext-field cn-cr-rowcontext-involved' : 'cn-cr-rowcontext-field'}>
            {k}: {formatValue(v)}
          </span>
        ))}
      </div>
    </div>
  )
}

/** 展开后的只读上下文面板：懒加载详情（items 三态 diff + 行上下文），无审批入口 */
function RequestContext({ wid, tableId, requestId }: { wid: string; tableId: ID; requestId: ID }) {
  const { data, isLoading } = useQuery({
    queryKey: ['change-request', wid, tableId, String(requestId)],
    queryFn: () => changeRequestsApi.get(wid, tableId, requestId),
  })
  if (isLoading) return <div className="cn-cr-context"><Spin size="small" /></div>
  if (!data) return <div className="cn-cr-context"><Text type="secondary">上下文加载失败，可点击标题进入详情查看</Text></div>
  return (
    <div className="cn-cr-context">
      {data.description && (
        <Paragraph type="secondary" className="cn-cr-context-desc">{data.description}</Paragraph>
      )}
      {data.items.length === 0 && <Text type="secondary">（无变更项）</Text>}
      {data.items.map((item: ChangeItemDetail) => (
        <div key={item.id} className="cn-cr-context-item">
          <Space size={8} wrap className="cn-cr-context-tags">
            <Tag color={OP_META[item.op].color}>{OP_META[item.op].label}</Tag>
            {item.row_id != null && <Text type="secondary">行 #{item.row_id}</Text>}
            <Text type="secondary" className="cn-cr-change-fields" title={changeSummary(item)}>
              {changeSummary(item)}
            </Text>
            {item.row_missing && <Tag>行已删除</Tag>}
            {item.field_conflicts.length > 0 && (
              <Text type="danger" className="cn-cr-context-hint">{item.field_conflicts.length} 个字段基准已漂移</Text>
            )}
          </Space>
          <FieldDiffTable item={item} />
          {item.row_id != null && !item.row_missing && <RowContextValues item={item} />}
        </div>
      ))}
    </div>
  )
}

// ── 工作区级左右分栏（需求 0107） ──────────────────────

/** 左栏工作表分组：table_id → 表名 + 该表申请清单 */
interface TableGroup {
  tableId: ID
  name: string
  items: ChangeRequest[]
}

/** 工作区级左右分栏视图：左栏工作表清单（计数 + 选中态），右栏选中表的修改项（支持展开看行上下文） */
function WorkspaceSplitView({ wid, items, nameById, showStatus, goDetail, isLoading }: {
  wid: string
  items: ChangeRequest[]
  nameById: Map<string, string>
  showStatus: boolean
  goDetail: (item: ChangeRequest) => void
  isLoading: boolean
}) {
  const [selected, setSelected] = useState<ID | null>(null)
  /** 展开的申请（同页可多开） */
  const [expanded, setExpanded] = useState<Set<string>>(new Set())

  const groups = useMemo<TableGroup[]>(() => {
    const map = new Map<string, TableGroup>()
    for (const it of items) {
      const key = String(it.table_id)
      let g = map.get(key)
      if (!g) {
        g = { tableId: it.table_id, name: it.table_name || `表 #${it.table_id}`, items: [] }
        map.set(key, g)
      }
      g.items.push(it)
    }
    return Array.from(map.values())
  }, [items])

  // 默认选中：申请数最多的表；并列取最新一条申请时间更近者（列表本身已按时间倒序，取组内首条比较即可）
  const defaultTableId = useMemo<ID | null>(() => {
    let best: TableGroup | null = null
    for (const g of groups) {
      if (
        !best
        || g.items.length > best.items.length
        || (g.items.length === best.items.length
          && String(g.items[0]?.created_at ?? '') > String(best.items[0]?.created_at ?? ''))
      ) best = g
    }
    return best?.tableId ?? null
  }, [groups])

  const activeTableId = groups.some(g => g.tableId === selected) ? selected : defaultTableId
  const activeGroup = groups.find(g => g.tableId === activeTableId) ?? null

  const toggleExpand = (id: ID) => {
    setExpanded(prev => {
      const next = new Set(prev)
      const key = String(id)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  return (
    <div className="cn-qc-split" data-testid="cr-workspace-split">
      {/* 左栏：涉及的工作表清单（窄屏由 cn-qc-split 收为纵向堆叠） */}
      <SectionBox
        title="涉及的工作表"
        icon={<TableOutlined />}
        extra={<span>共 {groups.length} 张表</span>}
        flush
        testId="cr-tables-box"
      >
        <Spin spinning={isLoading}>
          {groups.length === 0 ? (
            <div className="cn-qc-empty">
              <Empty description="暂无修改申请" />
            </div>
          ) : (
            <div role="listbox" aria-label="涉及的工作表" className="cn-cr-side-list">
              {groups.map(g => (
                <button
                  key={String(g.tableId)}
                  type="button"
                  role="option"
                  aria-selected={g.tableId === activeTableId}
                  className={[
                    'cn-cr-side-item',
                    'cn-qc-row',
                    'cn-qc-row--selectable',
                    g.tableId === activeTableId ? 'cn-qc-row--active' : '',
                  ].filter(Boolean).join(' ')}
                  onClick={() => setSelected(g.tableId)}
                >
                  <span className="cn-cr-side-name">{g.name}</span>
                  <Badge count={g.items.length} color="blue" title="申请数" />
                </button>
              ))}
            </div>
          )}
        </Spin>
      </SectionBox>
      {/* 右栏：选中表的修改项列表，每条支持展开看行上下文 */}
      <SectionBox
        title="修改项"
        icon={<UnorderedListOutlined />}
        extra={<span>共 {activeGroup?.items.length ?? 0} 条</span>}
        flush
        testId="cr-requests-box"
      >
        <Spin spinning={isLoading}>
          {!activeGroup ? (
            <div className="cn-qc-empty">
              <Empty description="选择左侧工作表查看修改项" />
            </div>
          ) : (
            activeGroup.items.map(item => {
              const isOpen = expanded.has(String(item.id))
              return (
                <RequestRow
                  key={item.id}
                  item={item}
                  nameById={nameById}
                  showStatus={showStatus}
                  onClick={() => goDetail(item)}
                  expanded={isOpen}
                  onToggleExpand={() => toggleExpand(item.id)}
                >
                  <RequestContext wid={wid} tableId={item.table_id} requestId={item.id} />
                </RequestRow>
              )
            })
          )}
        </Spin>
      </SectionBox>
    </div>
  )
}

// ── 单表同行合并（左行分组 / 右申请清单） ──────────────────────

/** 单表同行合并：左栏行分组，右栏选中分组的申请与批量审批 */
function TableGroupedView({ wid, tid, groups, ungrouped, nameById, canReview, goDetail, isLoading }: {
  wid: string
  tid: string
  groups: ChangeRowGroup[]
  ungrouped: ChangeRequest[]
  nameById: Map<string, string>
  canReview: boolean
  goDetail: (item: ChangeRequest) => void
  isLoading: boolean
}) {
  const { message, modal } = AntApp.useApp()
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  /** 行组勾选：rowId → 选中的申请 id 集合 */
  const [selected, setSelected] = useState<Record<string, Set<string>>>({})
  const [selectedKey, setSelectedKey] = useState<string | null>(null)

  const keys = useMemo(() => [
    ...groups.map(g => String(g.row_id)),
    ...(ungrouped.length > 0 ? ['ungrouped'] : []),
  ], [groups, ungrouped])

  const activeKey = selectedKey != null && keys.includes(selectedKey) ? selectedKey : (keys[0] ?? null)
  const activeGroup = groups.find(g => String(g.row_id) === activeKey) ?? null
  const activeUngrouped = activeKey === 'ungrouped'
  const activeRequests = activeUngrouped ? ungrouped : activeGroup?.requests ?? []
  const activeRowId = activeGroup ? String(activeGroup.row_id) : ''
  const activeSelected = activeRowId ? selected[activeRowId] ?? new Set<string>() : new Set<string>()

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
    queryClient.invalidateQueries({ queryKey: ['change-requests', wid] })
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

  return (
    <div className="cn-qc-split" data-testid="cr-grouped-split">
      {/* 左栏：行分组（按目标行聚合） */}
      <SectionBox
        title="行分组"
        icon={<UnorderedListOutlined />}
        extra={<span>共 {groups.length} 组</span>}
        flush
        testId="cr-groups-box"
      >
        <Spin spinning={isLoading}>
          {keys.length === 0 ? (
            <div className="cn-qc-empty">
              <Empty description="暂无待审申请" />
            </div>
          ) : (
            <div role="listbox" aria-label="行分组" className="cn-cr-side-list">
              {groups.map(group => {
                const key = String(group.row_id)
                const preview = rowPreview(group.row_values)
                return (
                  <button
                    key={key}
                    type="button"
                    role="option"
                    aria-selected={key === activeKey}
                    className={[
                      'cn-cr-side-item',
                      'cn-cr-group-item',
                      'cn-qc-row',
                      'cn-qc-row--selectable',
                      key === activeKey ? 'cn-qc-row--active' : '',
                    ].filter(Boolean).join(' ')}
                    onClick={() => setSelectedKey(key)}
                  >
                    <span className="cn-cr-side-main">
                      <span className="cn-cr-side-title">
                        <Text strong>行 #{group.row_id}</Text>
                        <Badge count={group.requests.length} color="blue" title="待审申请数" />
                      </span>
                      <span className="cn-cr-side-preview" title={preview || undefined}>{preview || '（行值不可用）'}</span>
                      <span className="cn-cr-tags">
                        {group.has_conflict && <Tag color="red">冲突</Tag>}
                        {group.has_drift && <Tag color="orange">基准漂移</Tag>}
                        {group.row_missing && <Tag>行已删除</Tag>}
                      </span>
                    </span>
                  </button>
                )
              })}
              {ungrouped.length > 0 && (
                <button
                  type="button"
                  role="option"
                  aria-selected={activeUngrouped}
                  className={[
                    'cn-cr-side-item',
                    'cn-cr-group-item',
                    'cn-qc-row',
                    'cn-qc-row--selectable',
                    activeUngrouped ? 'cn-qc-row--active' : '',
                  ].filter(Boolean).join(' ')}
                  onClick={() => setSelectedKey('ungrouped')}
                >
                  <span className="cn-cr-side-main">
                    <span className="cn-cr-side-title">
                      <Text strong>新增行申请</Text>
                      <Badge count={ungrouped.length} color="blue" title="待审申请数" />
                    </span>
                    <span className="cn-cr-side-preview">无目标行（新增行）</span>
                  </span>
                </button>
              )}
            </div>
          )}
        </Spin>
      </SectionBox>

      {/* 右栏：选中分组的申请清单 + 批量审批 */}
      <SectionBox
        title={activeUngrouped
          ? '新增行申请 · 申请清单'
          : activeGroup ? `行 #${activeGroup.row_id} · 申请` : '申请清单'}
        icon={<PullRequestOutlined />}
        extra={(
          <Space size={8} wrap>
            <span>共 {activeRequests.length} 份</span>
            {canReview && activeGroup && (
              <Button
                type="primary"
                size="small"
                icon={<CheckOutlined />}
                disabled={activeSelected.size === 0}
                loading={mergeRow.isPending && activeSelected.size > 0}
                onClick={() => handleBatchApprove(activeGroup)}
              >
                批量审批{activeSelected.size > 0 ? `（${activeSelected.size}）` : ''}
              </Button>
            )}
          </Space>
        )}
        flush
        testId="cr-group-requests-box"
      >
        <Spin spinning={isLoading}>
          {activeRequests.length === 0 ? (
            <div className="cn-qc-empty">
              <Empty description="暂无申请" />
            </div>
          ) : (
            <>
              {activeGroup && (activeGroup.conflict_fields.length > 0 || activeGroup.drift_fields.length > 0) && (
                <div className="cn-cr-groupnote">
                  {activeGroup.conflict_fields.length > 0 && (
                    <Text type="danger" className="cn-cr-groupnote-line">
                      冲突字段：{activeGroup.conflict_fields.join('、')}
                    </Text>
                  )}
                  {activeGroup.drift_fields.length > 0 && (
                    <Text type="warning" className="cn-cr-groupnote-line">
                      基准漂移字段：{activeGroup.drift_fields.join('、')}
                    </Text>
                  )}
                </div>
              )}
              {activeRequests.map(item => (
                <RequestRow
                  key={item.id}
                  item={item}
                  nameById={nameById}
                  showStatus={false}
                  selected={activeRowId ? activeSelected.has(String(item.id)) : undefined}
                  onToggleSelect={canReview && activeGroup
                    ? (checked) => toggleSelect(activeRowId, String(item.id), checked)
                    : undefined}
                  onClick={() => goDetail(item)}
                />
              ))}
            </>
          )}
        </Spin>
      </SectionBox>
    </div>
  )
}

export default function ChangeRequestsPage() {
  const { wid = '', tid = '' } = useParams<{ wid: string; tid?: string }>()
  // 无 :tid = 工作区级（数据表模块「修改申请」页签）；有 :tid = 单表视图
  const workspaceMode = !tid
  const navigate = useNavigate()
  const { message } = AntApp.useApp()
  const [scope, setScope] = useState<Scope>('open')
  const [view, setView] = useState<View>('grouped')
  const nameById = useMemberNameMap(wid)

  // 分组视图仅在「待审核」且选择同行合并时启用（历史/我的/全部维持平铺）
  const groupedMode = !workspaceMode && scope === 'open' && view === 'grouped'

  const flatQuery = useQuery({
    queryKey: workspaceMode
      ? ['change-requests', wid, 'workspace', scope]
      : ['change-requests', wid, tid, scope],
    queryFn: () => (
      workspaceMode ? changeRequestsApi.listWorkspace(wid, scope) : changeRequestsApi.list(wid, tid, scope)
    ),
    enabled: !!wid && (workspaceMode || !!tid) && !groupedMode,
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

  const openNewDialog = () => {
    // 新建修改申请入口：写路径（单元格/行详情/批量删除）已按双轨自动分派，
    // 提示按当前写模式适配 —— 直编用户明确告知"编辑直接生效、不会生成申请"
    if (workspaceMode) {
      message.info('修改申请由具体数据表中的编辑自动生成：打开目标表编辑数据后即可在此审批')
      return
    }
    message.info(newRequestHint(writeMode))
  }

  // 旧响应无 write_mode 时按申请模式兜底（与 viewer 工况一致）；工作区级跨表无法用单一写模式
  const writeMode: TableWriteMode =
    (groupedMode ? groupedQuery.data?.write_mode : flatQuery.data?.write_mode) ?? 'change_request'
  const banner = workspaceMode ? null : WRITE_MODE_BANNER[writeMode]

  const isLoading = groupedMode ? groupedQuery.isLoading : flatQuery.isLoading

  const groups = groupedQuery.data?.groups ?? []
  const ungrouped = groupedQuery.data?.ungrouped ?? []
  const flatItems = flatQuery.data?.items ?? []

  // 工作区级入口跳详情携带 from=workspace，详情页「返回修改申请」据此回到工作区列表（需求 0107）
  const goDetail = (item: ChangeRequest) =>
    navigate(`/w/${wid}/tables/${item.table_id}/change-requests/${item.id}`, workspaceMode ? { state: { from: 'workspace' } } : undefined)

  return (
    <div className="cn-page cn-qc-page cn-cr-page" data-testid="change-requests-page">
      {/* ── 页头：标题 + 口径说明 + 筛选 / 新建入口（与质量检查页同款紧凑页头） ── */}
      <header className="cn-page-head">
        <div className="cn-page-head-main">
          <span className="cn-page-head-icon" aria-hidden><PullRequestOutlined /></span>
          <div className="cn-page-head-text">
            <h1 className="cn-page-head-title">修改申请</h1>
            <div className="cn-page-head-sub">
              <span className="cn-page-head-meta">
                {workspaceMode
                  ? '左侧为涉及的工作表，右侧为选中表的修改项；点击申请查看详情并审批。'
                  : '同行合并视图按目标行聚合待审核申请，可勾选批量审批；历史申请按平铺列表展示。'}
              </span>
            </div>
          </div>
        </div>
        <div className="cn-page-head-actions">
          <Segmented options={SCOPE_OPTIONS} value={scope} onChange={(v) => setScope(v as Scope)} />
          {!workspaceMode && scope === 'open' && (
            <Segmented options={VIEW_OPTIONS} value={view} onChange={(v) => setView(v as View)} />
          )}
          <Button type="primary" icon={<PlusOutlined />} onClick={openNewDialog}>新建修改申请</Button>
        </div>
      </header>

      {banner && (
        <Alert
          type={banner.type}
          showIcon
          title={(
            <Space size={8} wrap>
              <Tag color={banner.type === 'success' ? 'green' : banner.type === 'warning' ? 'default' : 'blue'}>
                {banner.label}
              </Tag>
              <Text type="secondary">{banner.message}</Text>
            </Space>
          )}
        />
      )}

      {workspaceMode ? (
        <WorkspaceSplitView
          wid={wid}
          items={flatItems}
          nameById={nameById}
          showStatus={scope !== 'open'}
          goDetail={goDetail}
          isLoading={isLoading}
        />
      ) : groupedMode ? (
        <TableGroupedView
          wid={wid}
          tid={tid}
          groups={groups}
          ungrouped={ungrouped}
          nameById={nameById}
          canReview={canReview}
          goDetail={goDetail}
          isLoading={isLoading}
        />
      ) : (
        <SectionBox
          title="修改申请"
          icon={<UnorderedListOutlined />}
          extra={<span>共 {flatItems.length} 条</span>}
          flush
          testId="cr-requests-box"
        >
          <Spin spinning={isLoading}>
            {flatItems.length === 0 ? (
              <div className="cn-qc-empty">
                <Empty description="暂无修改申请" />
              </div>
            ) : (
              flatItems.map(item => (
                <RequestRow
                  key={item.id}
                  item={item}
                  nameById={nameById}
                  showStatus={scope !== 'open'}
                  tableName={item.table_name}
                  onClick={() => goDetail(item)}
                />
              ))
            )}
          </Spin>
        </SectionBox>
      )}
    </div>
  )
}
