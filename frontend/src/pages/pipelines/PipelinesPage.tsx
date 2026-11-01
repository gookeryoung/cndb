/** 质量检查（流水线）页 —— GitHub 风格双栏（ADR 0080 D4）.
 *
 * 左栏：流水线规则清单（启用开关 / 手动运行 / 编辑 / 删除，点击选中）；
 * 右栏：选中规则的运行结果历史（run 列表 → 点击进运行详情），未选中时给引导提示。
 * 检查动作目录按已启用模块由后端过滤；目录为空（如仅勾「设计」）时页面给提示。
 * 编辑抽屉对 YAML 做防抖实时编译校验，保存前要求校验通过；插入片段由 `checkCatalog` 生成。
 * queryKey 约定：['pipelines', wid]。
 */

import { useEffect, useState } from 'react'
import {
  Alert, App as AntApp, Button, Collapse, Drawer, Empty, Input, Listy, Popconfirm, Space, Spin,
  Switch, Tag, Typography,
} from 'antd'
import {
  DeleteOutlined, EditOutlined, PlayCircleOutlined, PlusOutlined, RightOutlined,
} from '@ant-design/icons'
import CnListMeta from '@/components/CnListMeta'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate, useParams } from 'react-router-dom'
import { formatDateTime } from '@/utils/datetime'
import { pipelinesApi } from '@/api'
import type { PipelineRun, PipelineValidateResult, PipelineWorkflow } from '@/api'
import {
  CHECK_CATEGORY_LABEL, PIPELINE_STATUS_META, PIPELINE_TRIGGER_LABEL, buildStepSnippet,
  defaultWorkflowContent, describeTriggers, isActiveRun,
} from './checkCatalog'

const { Text } = Typography

/** 校验失败时统一兜底文案（网络错误等非 4xx 场景） */
function validateErrorText(err: unknown): string {
  return err instanceof Error ? err.message : '校验请求失败'
}

/** 运行行 —— 右栏单条历史记录（状态 / 触发来源 / 时间；活跃运行轮询提示交给详情页） */
function RunItem({ run, onOpen }: { run: PipelineRun; onOpen: () => void }) {
  const meta = PIPELINE_STATUS_META[run.status] ?? { label: run.status, color: 'default' }
  return (
    <div
      className="cn-list-item"
      style={{ cursor: 'pointer' }}
      data-testid={`run-item-${run.id}`}
      onClick={onOpen}
    >
      <div className="cn-list-item-main">
        <CnListMeta
          title={(
            <Space size={8} wrap>
              <Tag color={meta.color} style={{ marginInlineEnd: 0 }}>{meta.label}</Tag>
              <Text strong>#{run.id}</Text>
              <Text type="secondary">{PIPELINE_TRIGGER_LABEL[run.trigger] ?? run.trigger}</Text>
            </Space>
          )}
          description={<Text type="secondary">{formatDateTime(run.created_at)}</Text>}
        />
      </div>
      <div className="cn-list-item-actions">
        <RightOutlined style={{ color: 'var(--cn-text-muted)' }} aria-hidden />
      </div>
    </div>
  )
}

export default function PipelinesPage() {
  const { wid = '' } = useParams<{ wid: string }>()
  const navigate = useNavigate()
  const { message } = AntApp.useApp()
  const queryClient = useQueryClient()

  const [editorOpen, setEditorOpen] = useState(false)
  const [editing, setEditing] = useState<PipelineWorkflow | null>(null)
  const [content, setContent] = useState('')
  const [validation, setValidation] = useState<PipelineValidateResult | null>(null)
  const [validating, setValidating] = useState(false)
  /** 左栏当前选中的流水线（决定右栏展示哪条规则的运行历史） */
  const [selectedId, setSelectedId] = useState<string | number | null>(null)

  const { data: workflows = [], isLoading } = useQuery({
    queryKey: ['pipelines', wid],
    queryFn: () => pipelinesApi.list(wid),
    enabled: !!wid,
  })

  const { data: checks = [] } = useQuery({
    queryKey: ['pipelines', wid, 'checks'],
    queryFn: () => pipelinesApi.checks(wid),
    enabled: !!wid,
  })

  const selected = workflows.find(w => w.id === selectedId) ?? null

  // 右栏运行历史：仅选中规则后拉取；活跃运行（pending/running）10s 轮询推进状态
  const { data: runPage, isLoading: runsLoading } = useQuery({
    queryKey: ['pipelines', wid, 'runs', selectedId],
    queryFn: () => pipelinesApi.listRuns(wid, selectedId!, { limit: 20 }),
    enabled: !!wid && selectedId != null,
    refetchInterval: (query) => {
      const runs = query.state.data?.items ?? []
      return runs.some(r => isActiveRun(r.status)) ? 10_000 : false
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
      if (!editing) setContent(defaultWorkflowContent())
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
    onSuccess: (pipelineRun) => {
      message.success('已开始运行')
      navigate(`/w/${wid}/pipelines/${pipelineRun.id}`)
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
    setContent(defaultWorkflowContent())
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
    setContent(prev => (prev.trim() ? `${prev.replace(/\s+$/, '')}\n${snippet}` : snippet))
  }

  const saveDisabled = !validation?.ok || save.isPending

  return (
    <div style={{ padding: '16px 24px', maxWidth: 1200, margin: '0 auto' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
        <div>
          <Text strong style={{ fontSize: 18 }}>质量检查</Text>
          <div>
            <Text type="secondary">
              左侧为检查规则清单，点击查看右侧的运行结果历史；可手动运行，也可订阅记录变更、文档保存与同步完成事件。
            </Text>
          </div>
        </div>
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新建流水线</Button>
      </div>

      {/* 检查动作目录为空：当前工作区勾选的模块没有可用检查动作（如仅勾「设计」，
          design 域动作尚未提供），给出明确提示而非静默空态（ADR 0080 边界 #1） */}
      {!isLoading && checks.length === 0 && (
        <Alert
          type="info"
          showIcon
          data-testid="empty-checks-alert"
          message="暂无可用检查动作"
          description="当前工作区启用的功能模块下还没有检查动作；仍可创建流水线，待后续版本提供更多检查动作后即可运行。"
          style={{ marginBottom: 12 }}
        />
      )}

      {/* GitHub 风格双栏：左=规则清单，右=运行历史 */}
      <div style={{ display: 'flex', gap: 16, alignItems: 'flex-start' }} data-testid="pipelines-split">
        {/* 左栏：流水线规则清单 */}
        <div style={{ flex: '0 0 42%', minWidth: 0 }}>
          <Text strong style={{ display: 'block', marginBottom: 8 }}>检查规则</Text>
          <Spin spinning={isLoading}>
            {workflows.length === 0 && !isLoading ? (
              <Empty description="还没有流水线定义" style={{ padding: 48 }} />
            ) : (
              <Listy
                className="cn-listy-plain"
                items={workflows}
                rowKey={item => item.id}
                itemRender={(workflow: PipelineWorkflow) => (
                  <div
                    className="cn-list-item"
                    data-testid={`pipeline-item-${workflow.id}`}
                    style={{
                      cursor: 'pointer',
                      background: workflow.id === selectedId ? 'var(--cn-bg-subtle, #f5f5f5)' : undefined,
                    }}
                    onClick={() => setSelectedId(workflow.id)}
                  >
                    <div className="cn-list-item-main">
                      <CnListMeta
                        title={(
                          <Space size={8} wrap>
                            <Switch
                              size="small"
                              checked={workflow.enabled}
                              loading={toggleEnabled.isPending}
                              aria-label={`${workflow.name} 启用`}
                              onClick={(_, e) => e.stopPropagation()}
                              onChange={(enabled) => toggleEnabled.mutate({ workflow, enabled })}
                            />
                            <Text strong>{workflow.name}</Text>
                            {workflow.last_run && (
                              <Tag
                                color={PIPELINE_STATUS_META[workflow.last_run.status]?.color ?? 'default'}
                                style={{ marginInlineEnd: 0 }}
                              >
                                {PIPELINE_STATUS_META[workflow.last_run.status]?.label ?? workflow.last_run.status}
                              </Tag>
                            )}
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
                    <div className="cn-list-item-actions" onClick={e => e.stopPropagation()}>
                      <Space size={4}>
                        {workflow.last_run && (
                          <Button
                            type="link"
                            size="small"
                            onClick={() => navigate(`/w/${wid}/pipelines/${workflow.last_run!.id}`)}
                          >
                            最近运行
                          </Button>
                        )}
                        <Button type="link" size="small" icon={<PlayCircleOutlined />} onClick={() => run.mutate(workflow)}>
                          运行
                        </Button>
                        <Button type="link" size="small" icon={<EditOutlined />} onClick={() => openEdit(workflow)}>
                          编辑
                        </Button>
                        <Popconfirm
                          title={`删除流水线「${workflow.name}」？`}
                          description="运行历史与检查发现物会一并删除。"
                          okText="删除"
                          okButtonProps={{ danger: true }}
                          onConfirm={() => remove.mutate(workflow)}
                        >
                          <Button type="link" size="small" danger icon={<DeleteOutlined />}>删除</Button>
                        </Popconfirm>
                      </Space>
                    </div>
                  </div>
                )}
              />
            )}
          </Spin>
        </div>

        {/* 右栏：选中规则的运行结果历史 */}
        <div style={{ flex: 1, minWidth: 0 }}>
          <Text strong style={{ display: 'block', marginBottom: 8 }}>
            运行历史{selected ? `：${selected.name}` : ''}
          </Text>
          {selectedId == null ? (
            <Empty
              description={workflows.length === 0
                ? '创建流水线后，这里会展示每次检查的结果'
                : '在左侧选择一条流水线，查看它的运行历史'}
              style={{ padding: 48 }}
            />
          ) : (
            <Spin spinning={runsLoading}>
              {(runPage?.items.length ?? 0) === 0 && !runsLoading ? (
                <Empty description="这条流水线还没有运行记录，点「运行」试试" style={{ padding: 48 }} />
              ) : (
                <Listy
                  className="cn-listy-plain"
                  items={runPage?.items ?? []}
                  rowKey={(item: PipelineRun) => item.id}
                  itemRender={(item: PipelineRun) => (
                    <RunItem run={item} onOpen={() => navigate(`/w/${wid}/pipelines/${item.id}`)} />
                  )}
                />
              )}
            </Spin>
          )}
        </div>
      </div>

      <Drawer
        title={editing ? `编辑流水线：${editing.name}` : '新建流水线'}
        open={editorOpen}
        onClose={() => { setEditorOpen(false); setEditing(null) }}
        size={760}
        destroyOnHidden
        extra={(
          <Button type="primary" onClick={() => save.mutate()} disabled={saveDisabled} loading={save.isPending}>
            保存
          </Button>
        )}
      >
        <Input.TextArea
          aria-label="流水线 YAML"
          value={content}
          onChange={(event) => setContent(event.target.value)}
          autoSize={{ minRows: 16, maxRows: 30 }}
          style={{ fontFamily: 'var(--cn-font-mono, monospace)', fontSize: 13 }}
          spellCheck={false}
        />
        <div style={{ marginTop: 8 }}>
          {validating && <Text type="secondary">校验中…</Text>}
          {!validating && validation && (
            validation.ok ? (
              <Alert
                type="success"
                showIcon
                message={`校验通过：${validation.name}（${validation.job_count} 个 job / ${validation.step_count} 个 step）`}
              />
            ) : (
              <Alert type="error" showIcon message="DSL 校验未通过" description={validation.error} />
            )
          )}
        </div>

        <Collapse
          style={{ marginTop: 16 }}
          size="small"
          items={[{
            key: 'checks',
            label: `检查动作目录（${checks.length}）`,
            children: checks.length === 0 ? (
              <Text type="secondary">暂无可用检查动作</Text>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                {checks.map(check => (
                  <div key={check.uses}>
                    <Space size={8} wrap>
                      <Text strong>{check.title}</Text>
                      <Tag style={{ marginInlineEnd: 0 }}>{CHECK_CATEGORY_LABEL[check.category] ?? check.category}</Tag>
                      <Text type="secondary">{check.uses}</Text>
                      <Button size="small" type="link" onClick={() => insertSnippet(buildStepSnippet(check))}>
                        插入
                      </Button>
                    </Space>
                  </div>
                ))}
              </div>
            ),
          }]}
        />
      </Drawer>
    </div>
  )
}
