/** 质量检查（流水线）页 —— GitHub 双栏（ADR 0080 D4），视觉口径对齐数据分析页.
 *
 * 同一页面按域复用：`/pipelines`（数据表检查）与 `/documents/pipelines`（文档检查）。
 * 规则清单 / 检查动作目录 / 运行历史均带 `domain` 查询参数，两个模块各看各的；
 * 跨域编排的流水线同时属于多个域，两边都可管理（不丢规则）。
 *
 * 左栏：流水线规则清单（「全部」置顶且默认激活，其下为启用开关 / 运行 / 编辑 / 删除，
 * 点击规则选中 / 再点取消回「全部」）；
 * 右栏：运行历史——默认展示当前域全部规则的运行（行内带规则名），
 * 选中某条规则后只展示其对应的运行，再点一次、点「全部」或点「查看全部」回到全部。
 * 手动运行后停留在本页并刷新历史（不自动跳详情，点运行行才进运行详情）；
 * 运行期间右栏每 1.5s 轮询、状态标签带转圈图标并显示「已用时」（GitHub 的 in-progress 口径）。
 * 两栏均为「带边框列表」：SectionBox 承担外框，flush 内容区里的行自带分隔线与
 * hover / 选中态，与数据分析页的分区方盒同一套语言。
 * 检查动作目录按已启用模块 + 当前域过滤；目录为空时页面给提示。
 * 编辑抽屉对 YAML 做防抖实时编译校验，保存前要求校验通过；新建模板按域给出本域动作。
 * queryKey 约定：['pipelines', wid, domain]。
 */

import { useEffect, useRef, useState } from 'react'
import {
  Alert, App as AntApp, Button, Drawer, Dropdown, Empty, Popconfirm, Space, Spin,
  Switch, Tag, Tooltip, Typography, type MenuProps,
} from 'antd'
import {
  AppstoreOutlined, DeleteOutlined, EditOutlined, HistoryOutlined, PlayCircleOutlined, PlusOutlined,
  RightOutlined, SafetyCertificateOutlined, SyncOutlined, UnorderedListOutlined,
} from '@ant-design/icons'
import CnListMeta from '@/components/CnListMeta'
import SectionBox from '@/components/SectionBox'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate, useParams } from 'react-router-dom'
import { formatDateTime } from '@/utils/datetime'
import { pipelinesApi } from '@/api'
import type { PipelineCheckDomain, PipelineRun, PipelineValidateResult, PipelineWorkflow } from '@/api'
import {
  CHECK_CATEGORY_LABEL, PIPELINE_STATUS_META, PIPELINE_TRIGGER_LABEL, buildStepSnippet,
  defaultWorkflowContent, describeTriggers, formatElapsed, isActiveRun,
} from './checkCatalog'
import PipelineDslEditor, { type PipelineDslEditorHandle } from './PipelineDslEditor'

const { Text } = Typography

/** 检查域 → 页面文案（标题后缀 / 作用域说明 / 空目录提示） */
const DOMAIN_META: Record<PipelineCheckDomain, {
  scope: string
  emptyRules: string
  emptyChecks: string
}> = {
  table: {
    scope: '仅数据表检查动作与规则；可手动运行，也可订阅记录变更与同步完成事件',
    emptyRules: '还没有数据表检查规则，点右上角「新建流水线」开始',
    emptyChecks: '当前工作区还没有数据表检查动作；仍可创建流水线，待后续版本提供更多检查动作后即可运行。',
  },
  document: {
    scope: '仅文档检查动作与规则；可手动运行，也可订阅文档保存事件',
    emptyRules: '还没有文档检查规则，点右上角「新建流水线」开始',
    emptyChecks: '当前工作区还没有文档检查动作；仍可创建流水线，待后续版本提供更多检查动作后即可运行。',
  },
}

/** 校验失败时统一兜底文案（网络错误等非 4xx 场景） */
function validateErrorText(err: unknown): string {
  return err instanceof Error ? err.message : '校验请求失败'
}

/** 运行摘要：发现物计数与耗时（均为可选，后端未产出时留空） */
function runSummary(run: PipelineRun): string {
  const findings = run.stats.findings ?? {}
  return [
    findings.error ? `错误 ${findings.error}` : '',
    findings.warn ? `告警 ${findings.warn}` : '',
    typeof run.stats.duration_ms === 'number' ? `耗时 ${run.stats.duration_ms} ms` : '',
  ].filter(Boolean).join(' · ')
}

/** 运行状态标签：活跃运行带转圈图标（GitHub 的 in-progress 口径，列表与规则行共用） */
function RunStatusTag({ status }: { status: PipelineRun['status'] }) {
  const meta = PIPELINE_STATUS_META[status] ?? { label: status, color: 'default' }
  return (
    <Tag
      color={meta.color}
      style={{ marginInlineEnd: 0 }}
      icon={isActiveRun(status) ? <SyncOutlined spin /> : undefined}
    >
      {meta.label}
    </Tag>
  )
}

/** 运行行 —— 右栏单条历史记录（全部规则模式下带规则名；活跃运行轮询提示交给详情页） */
function RunItem({ run, showWorkflow, onOpen }: {
  run: PipelineRun
  showWorkflow: boolean
  onOpen: () => void
}) {
  const active = isActiveRun(run.status)
  const summary = runSummary(run)
  const startedAt = Date.parse(run.created_at)
  // 活跃运行没有后端耗时（stats.duration_ms 终态才写），按开始时间算「已用时」；
  // 列表在运行期间每 1.5s 轮询，文案随轮询刷新
  const elapsed = active && !Number.isNaN(startedAt)
    ? `已用时 ${formatElapsed(Date.now() - startedAt)}`
    : ''
  return (
    <div
      className="cn-list-item cn-qc-row cn-qc-row--selectable"
      data-testid={`run-item-${run.id}`}
      onClick={onOpen}
    >
      <div className="cn-list-item-main">
        {/* 单行（GitHub 运行列表口径）：状态 / #id / 规则名（省略）/ 触发·时间·摘要右对齐 */}
        <div className={`cn-qc-run-item${active ? ' cn-qc-run-item--active' : ''}`}>
          <RunStatusTag status={run.status} />
          <Text strong className="cn-qc-run-item-id">#{run.id}</Text>
          {showWorkflow && <span className="cn-qc-run-item-name">{run.workflow_name}</span>}
          <span className="cn-qc-run-item-meta">
            {PIPELINE_TRIGGER_LABEL[run.trigger] ?? run.trigger}触发 · {formatDateTime(run.created_at)}
            {active ? ` · ${elapsed}` : summary ? ` · ${summary}` : ''}
          </span>
        </div>
      </div>
      <div className="cn-list-item-actions">
        <RightOutlined style={{ color: 'var(--cn-text-muted)' }} aria-hidden />
      </div>
    </div>
  )
}

export default function PipelinesPage({ domain = 'table' }: { domain?: PipelineCheckDomain }) {
  const { wid = '' } = useParams<{ wid: string }>()
  const navigate = useNavigate()
  const { message } = AntApp.useApp()
  const queryClient = useQueryClient()
  const meta = DOMAIN_META[domain]

  const [editorOpen, setEditorOpen] = useState(false)
  const [editing, setEditing] = useState<PipelineWorkflow | null>(null)
  const [content, setContent] = useState('')
  const [validation, setValidation] = useState<PipelineValidateResult | null>(null)
  const [validating, setValidating] = useState(false)
  /** 检查动作目录「插入」按钮经编辑器实例插到光标处（需求 0111 C7） */
  const editorRef = useRef<PipelineDslEditorHandle>(null)
  /** 左栏当前选中的流水线（null = 全部规则，决定右栏展示哪些运行历史） */
  const [selectedId, setSelectedId] = useState<string | number | null>(null)

  const { data: workflows = [], isLoading } = useQuery({
    queryKey: ['pipelines', wid, domain],
    queryFn: () => pipelinesApi.list(wid, domain),
    enabled: !!wid,
    // 有运行处于排队 / 执行中时轮询，左栏「最近运行」状态与右栏历史同步推进
    refetchInterval: (query) => (
      (query.state.data ?? []).some(flow => flow.last_run && isActiveRun(flow.last_run.status))
        ? 2000
        : false
    ),
  })

  const { data: checks = [] } = useQuery({
    queryKey: ['pipelines', wid, domain, 'checks'],
    queryFn: () => pipelinesApi.checks(wid, domain),
    enabled: !!wid,
  })

  const selected = workflows.find(w => w.id === selectedId) ?? null
  const enabledWorkflows = workflows.filter(workflow => workflow.enabled)

  // 右栏运行历史：默认拉取当前域全部规则的运行，选中规则后按 workflow_id 过滤；
  // 活跃运行（pending/running）1.5s 轮询推进状态（与运行详情页一致，GitHub 式实时刷新）
  const { data: runPage, isLoading: runsLoading } = useQuery({
    queryKey: ['pipelines', wid, domain, 'runs', selectedId ?? 'all'],
    queryFn: () => pipelinesApi.listWorkspaceRuns(wid, {
      domain,
      limit: 20,
      ...(selectedId != null ? { workflow_id: selectedId } : {}),
    }),
    enabled: !!wid,
    refetchInterval: (query) => {
      const runs = query.state.data?.items ?? []
      return runs.some(r => isActiveRun(r.status)) ? 1500 : false
    },
  })

  // 选中项被删除后回落到未选中态
  useEffect(() => {
    if (selectedId != null && !isLoading && workflows.length > 0
      && !workflows.some(w => w.id === selectedId)) {
      setSelectedId(null)
    }
  }, [workflows, isLoading, selectedId])

  // 防抖校验：编辑期间内容变化 400ms 后请求 /validate（组件卸载 / 抽屉关闭作废）
  useEffect(() => {
    if (!editorOpen || !content.trim()) {
      setValidation(null)
      return
    }
    let cancelled = false
    setValidating(true)
    const timer = setTimeout(() => {
      pipelinesApi.validate(wid, { content })
        .then((result) => { if (!cancelled) setValidation(result) })
        .catch((err) => {
          if (!cancelled) {
            setValidation({ ok: false, error: validateErrorText(err), name: '', job_count: 0, step_count: 0 })
          }
        })
        .finally(() => { if (!cancelled) setValidating(false) })
    }, 400)
    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [content, editorOpen, wid])

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['pipelines', wid] })

  /** 运行详情按当前域留在同一上下文：文档检查不跳回数据表质量检查页 */
  const runDetailPath = (runId: number | string) => (
    domain === 'document'
      ? `/w/${wid}/documents/pipelines/${runId}`
      : `/w/${wid}/pipelines/${runId}`
  )

  const save = useMutation({
    mutationFn: () => editing
      ? pipelinesApi.update(wid, editing.id, { content })
      : pipelinesApi.create(wid, { content }),
    onSuccess: (workflow) => {
      message.success(editing ? '流水线已更新' : '流水线已创建')
      invalidate()
      setEditorOpen(false)
      setEditing(null)
      setValidation(null)
      if (!editing) setContent(defaultWorkflowContent(domain))
      // 新建成功后选中新流水线，右栏直接展示其运行历史
      setSelectedId(workflow.id)
      return workflow
    },
    onError: (err) => message.error(err instanceof Error ? err.message : '保存失败'),
  })

  const toggleEnabled = useMutation({
    mutationFn: (payload: { workflow: PipelineWorkflow; enabled: boolean }) =>
      pipelinesApi.update(wid, payload.workflow.id, { enabled: payload.enabled }),
    onSuccess: () => invalidate(),
    onError: (err) => message.error(err instanceof Error ? err.message : '更新启用状态失败'),
  })

  const run = useMutation({
    mutationFn: (workflow: PipelineWorkflow) => pipelinesApi.run(wid, workflow.id),
    // 手动运行后停留在运行列表（不跳详情）：刷新规则与历史，新运行以「运行中」出现在右栏；
    // 当前正按某条规则过滤时切到刚运行的规则，保证新运行可见
    onSuccess: (_pipelineRun, workflow) => {
      message.success('已开始运行')
      setSelectedId(prev => (prev != null && prev !== workflow.id ? workflow.id : prev))
      invalidate()
    },
    onError: (err) => message.warning(err instanceof Error ? err.message : '触发运行失败'),
  })

  /** 一键运行全部启用的规则：逐条触发，单条失败（如已有进行中的运行）不影响其余 */
  const runAll = useMutation({
    mutationFn: async (input: { targets: PipelineWorkflow[]; disabled: number }) => {
      let started = 0
      let active = 0
      let failed = 0
      for (const workflow of input.targets) {
        try {
          await pipelinesApi.run(wid, workflow.id)
          started += 1
        } catch (err) {
          const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? ''
          if (detail.includes('进行中的运行')) active += 1
          else failed += 1
        }
      }
      return { started, active, failed, disabled: input.disabled }
    },
    onSuccess: ({ started, active, failed, disabled }) => {
      if (started > 0) message.success(`已触发 ${started} 条规则运行`)
      const notes: string[] = []
      if (active > 0) notes.push(`${active} 条已有进行中的运行`)
      if (failed > 0) notes.push(`${failed} 条触发失败`)
      if (disabled > 0) notes.push(`${disabled} 条已停用已跳过`)
      if (notes.length > 0) message.warning(notes.join('；'))
      invalidate()
    },
    onError: (err) => message.warning(err instanceof Error ? err.message : '触发运行失败'),
  })

  const remove = useMutation({
    mutationFn: (workflow: PipelineWorkflow) => pipelinesApi.remove(wid, workflow.id),
    onSuccess: (_result, workflow) => {
      message.success('流水线已删除')
      if (selectedId === workflow.id) setSelectedId(null)
      invalidate()
    },
    onError: (err) => message.error(err instanceof Error ? err.message : '删除失败'),
  })

  const openCreate = () => {
    setEditing(null)
    setContent(defaultWorkflowContent(domain))
    setValidation(null)
    setEditorOpen(true)
  }

  const openEdit = (workflow: PipelineWorkflow) => {
    setEditing(workflow)
    setContent(workflow.content)
    setValidation(null)
    setEditorOpen(true)
  }

  const insertSnippet = (snippet: string) => {
    editorRef.current?.insertSnippet(snippet)
  }

  const saveDisabled = !validation?.ok || save.isPending

  // 内置动作按类别分组的菜单项：动作多时只占一行工具栏，展开后在菜单内滚动
  const actionMenuItems: MenuProps['items'] = (() => {
    const groups = new Map<string, typeof checks>()
    for (const check of checks) {
      const category = CHECK_CATEGORY_LABEL[check.category] ?? check.category
      const bucket = groups.get(category)
      if (bucket) bucket.push(check)
      else groups.set(category, [check])
    }
    return [...groups.entries()].map(([category, items]) => ({
      type: 'group' as const,
      label: category,
      children: items.map(check => ({
        key: check.uses,
        label: (
          <span className="cn-pipeline-action-item">
            <span className="cn-pipeline-action-title">{check.title}</span>
            <span className="cn-pipeline-action-uses">{check.uses}</span>
          </span>
        ),
      })),
    }))
  })()

  return (
    <div className="cn-page cn-qc-page" data-testid="pipelines-page">
      {/* ── 页头：标题 + 口径说明 + 新建入口（与数据分析页同款紧凑页头） ── */}
      <header className="cn-page-head">
        <div className="cn-page-head-main">
          <span className="cn-page-head-icon" aria-hidden><SafetyCertificateOutlined /></span>
          <div className="cn-page-head-text">
            <h1 className="cn-page-head-title">质量检查</h1>
            <div className="cn-page-head-sub">
              <span className="cn-page-head-meta">
                左侧检查规则、右侧运行历史（默认全部规则，选中后只看该规则）；{meta.scope}
              </span>
            </div>
          </div>
        </div>
        <div className="cn-page-head-actions">
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新建流水线</Button>
        </div>
      </header>

      {/* 检查动作目录为空：当前域没有可用检查动作（如仅勾「设计」，
          design 域动作尚未提供），给出明确提示而非静默空态（ADR 0080 边界 #1） */}
      {!isLoading && checks.length === 0 && (
        <Alert
          type="info"
          showIcon
          data-testid="empty-checks-alert"
          title="暂无可用检查动作"
          description={meta.emptyChecks}
        />
      )}

      {/* GitHub 风格双栏：左=规则清单，右=运行历史；两栏都是带边框列表 */}
      <div className="cn-qc-split" data-testid="pipelines-split">
        {/* 左栏：流水线规则清单 */}
        <SectionBox
          title="检查规则"
          icon={<UnorderedListOutlined />}
          extra={<span>共 {workflows.length} 条</span>}
          flush
          testId="qc-rules-box"
        >
          <Spin spinning={isLoading}>
            {/* 「全部」置顶并默认激活（selectedId == null）：右栏展示当前域全部规则的运行历史，
                点击它清除规则过滤；列表为空时不渲染，避免与空态示例重复 */}
            {workflows.length > 0 && (
              <div
                className={[
                  'cn-list-item',
                  'cn-qc-row',
                  'cn-qc-row--selectable',
                  selectedId == null ? 'cn-qc-row--active' : '',
                ].filter(Boolean).join(' ')}
                data-testid="pipeline-item-all"
                onClick={() => setSelectedId(null)}
              >
                <div className="cn-list-item-main">
                  <CnListMeta
                    avatar={<AppstoreOutlined style={{ color: 'var(--cn-text-muted)' }} />}
                    title={<Text strong>全部</Text>}
                    description={(
                      <Text type="secondary">{workflows.length} 条规则 · 展示全部运行历史</Text>
                    )}
                  />
                </div>
                <div className="cn-list-item-actions" onClick={event => event.stopPropagation()}>
                  <Tooltip
                    title={enabledWorkflows.length === 0
                      ? '没有启用的规则'
                      : `运行全部启用的规则（${enabledWorkflows.length} 条）`}
                  >
                    <Button
                      type="text"
                      size="small"
                      aria-label="运行全部规则"
                      data-testid="pipeline-run-all"
                      icon={<PlayCircleOutlined />}
                      loading={runAll.isPending}
                      disabled={enabledWorkflows.length === 0}
                      onClick={() => runAll.mutate({
                        targets: enabledWorkflows,
                        disabled: workflows.length - enabledWorkflows.length,
                      })}
                    />
                  </Tooltip>
                </div>
              </div>
            )}
            {workflows.length === 0 && !isLoading ? (
              <div className="cn-qc-empty">
                <Empty description={meta.emptyRules} />
              </div>
            ) : (
              workflows.map(workflow => (
                <div
                  key={workflow.id}
                  className={[
                    'cn-list-item',
                    'cn-qc-row',
                    'cn-qc-row--selectable',
                    workflow.id === selectedId ? 'cn-qc-row--active' : '',
                  ].filter(Boolean).join(' ')}
                  data-testid={`pipeline-item-${workflow.id}`}
                  onClick={() => setSelectedId(prev => (prev === workflow.id ? null : workflow.id))}
                >
                  <div className="cn-list-item-main">
                    <CnListMeta
                      avatar={(
                        <Switch
                          size="small"
                          checked={workflow.enabled}
                          loading={toggleEnabled.isPending}
                          aria-label={`${workflow.name} 启用`}
                          onClick={(_, event) => event.stopPropagation()}
                          onChange={(enabled) => toggleEnabled.mutate({ workflow, enabled })}
                        />
                      )}
                      title={(
                        <Space size={8} wrap>
                          <Text strong>{workflow.name}</Text>
                          {workflow.last_run && <RunStatusTag status={workflow.last_run.status} />}
                          {!workflow.enabled && <Tag style={{ marginInlineEnd: 0 }}>已停用</Tag>}
                        </Space>
                      )}
                      description={(
                        <Text type="secondary">
                          {describeTriggers(workflow.compiled?.on)}
                          {workflow.last_run
                            ? ` · 最近运行 ${formatDateTime(workflow.last_run.created_at)}`
                            : ' · 尚未运行'}
                        </Text>
                      )}
                    />
                  </div>
                  <div className="cn-list-item-actions" onClick={event => event.stopPropagation()}>
                    <Tooltip title="运行">
                      <Button
                        type="text"
                        size="small"
                        aria-label={`运行 ${workflow.name}`}
                        icon={<PlayCircleOutlined />}
                        onClick={() => run.mutate(workflow)}
                      />
                    </Tooltip>
                    <Tooltip title="编辑 DSL">
                      <Button
                        type="text"
                        size="small"
                        aria-label={`编辑 ${workflow.name}`}
                        icon={<EditOutlined />}
                        onClick={() => openEdit(workflow)}
                      />
                    </Tooltip>
                    <Popconfirm
                      title={`删除流水线「${workflow.name}」？`}
                      description="运行历史与检查发现物会一并删除。"
                      okText="删除"
                      okButtonProps={{ danger: true }}
                      onConfirm={() => remove.mutate(workflow)}
                    >
                      <Button
                        type="text"
                        size="small"
                        danger
                        aria-label={`删除 ${workflow.name}`}
                        icon={<DeleteOutlined />}
                      />
                    </Popconfirm>
                  </div>
                </div>
              ))
            )}
          </Spin>
        </SectionBox>

        {/* 右栏：运行历史（默认全部规则，选中规则后过滤） */}
        <SectionBox
          title={selected ? `运行历史：${selected.name}` : '运行历史'}
          icon={<HistoryOutlined />}
          extra={runPage ? (
            <Space size={4}>
              <span>共 {runPage.total} 次</span>
              {selected && (
                <Button type="link" size="small" onClick={() => setSelectedId(null)}>
                  查看全部
                </Button>
              )}
            </Space>
          ) : undefined}
          flush
          testId="qc-runs-box"
        >
          <Spin spinning={runsLoading}>
            {(runPage?.items.length ?? 0) === 0 && !runsLoading ? (
              <div className="cn-qc-empty">
                <Empty
                  description={selected
                    ? '这条流水线还没有运行记录，点「运行」试试'
                    : workflows.length === 0
                      ? '创建流水线后，这里会展示每次检查的结果'
                      : '还没有运行记录，运行任一流水线后这里会展示历史'}
                />
              </div>
            ) : (
              (runPage?.items ?? []).map(item => (
                <RunItem
                  key={item.id}
                  run={item}
                  showWorkflow={selectedId == null}
                  onOpen={() => navigate(runDetailPath(item.id))}
                />
              ))
            )}
          </Spin>
        </SectionBox>
      </div>

      <Drawer
        title={editing ? `编辑流水线：${editing.name}` : '新建流水线'}
        open={editorOpen}
        onClose={() => { setEditorOpen(false); setEditing(null) }}
        size="min(1080px, 96vw)"
        destroyOnHidden
        classNames={{ body: 'cn-pipeline-drawer-body' }}
        extra={(
          <Button type="primary" onClick={() => save.mutate()} disabled={saveDisabled} loading={save.isPending}>
            保存
          </Button>
        )}
      >
        <div className="cn-pipeline-editor-layout">
          {/* 顶部动作条：单行工具栏 + 分组下拉菜单，动作再多也只占一行；余下高度全部交给编辑器 */}
          <div className="cn-pipeline-action-bar" data-testid="pipeline-action-bar">
            <Text strong>检查动作目录（{checks.length}）</Text>
            {checks.length === 0 ? (
              <Text type="secondary">暂无可用检查动作</Text>
            ) : (
              <>
                <Dropdown
                  trigger={['click']}
                  menu={{
                    items: actionMenuItems,
                    style: { maxHeight: 320, overflowY: 'auto', minWidth: 240 },
                    onClick: ({ key }) => {
                      const check = checks.find(item => item.uses === key)
                      if (check) insertSnippet(buildStepSnippet(check))
                    },
                  }}
                >
                  <Button size="small" icon={<PlusOutlined />} aria-label="插入内置动作">
                    插入动作
                  </Button>
                </Dropdown>
                <Text type="secondary">插入到光标处</Text>
              </>
            )}
          </div>

          <div className="cn-pipeline-editor-main">
            <PipelineDslEditor
              ref={editorRef}
              value={content}
              onChange={setContent}
              checks={checks}
              domain={domain}
            />
          </div>

          <div className="cn-pipeline-validate" role="status" aria-live="polite">
            {validating && <Text type="secondary">校验中…</Text>}
            {!validating && validation && (
              validation.ok ? (
                <Alert
                  type="success"
                  showIcon
                  title={`校验通过：${validation.name}（${validation.job_count} 个 job / ${validation.step_count} 个 step）`}
                />
              ) : (
                <Alert type="error" showIcon title="DSL 校验未通过" description={validation.error} />
              )
            )}
          </div>
        </div>
      </Drawer>
    </div>
  )
}
