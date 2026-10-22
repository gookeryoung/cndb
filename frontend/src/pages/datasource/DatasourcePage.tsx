/** 数据源同步页 — 工作区级任务列表 + Provider 驱动的任务编辑 / 抓取预览 / 运行历史.
 *
 * 后端：`/api/v1/workspaces/{wid}/datasource/*`（ADR 0006 M2/M3）
 * - 列表列：名称 / 适配器 / 目标表 / 调度 / 上次运行 / 操作
 * - 编辑抽屉：Provider 选择 → 请求模板 → 游标 → 调度 →（保存后）抓取预览
 * - 历史抽屉：每次运行的状态 / 游标区间 / 新增·更新 / 失败原因
 * - 大模型连接是个人级配置（「个人设置 → 大模型」），本页不再提供工作区级连接入口
 */

import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Alert, App as AntApp, Button, Collapse, Drawer, Dropdown, Empty, Form, Input, InputNumber, Modal,
  Select, Space, Switch, Table, Tag, Tooltip, Typography,
} from 'antd'
import {
  CloudDownloadOutlined, DeleteOutlined, EditOutlined, ExperimentOutlined, EyeOutlined,
  HistoryOutlined, KeyOutlined, PlayCircleOutlined, PlusOutlined,
} from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useParams } from 'react-router-dom'
import { datasourceApi, tableApi } from '@/api'
import { analyticsApi } from '@/api/analytics'
import { materializeDomainTemplate } from './domainTemplate'
import { LLM_PROMPT_PRESETS, type LlmPromptPreset } from './llmPromptPresets'
import type {
  DatasourceProviderInfo, DatasourceSession, DomainTemplate, SyncJob, SyncJobPayload, SyncPreviewResult,
  SyncRequestSpec, SyncRun, SyncScheduleConfig,
} from '@/api'

const { Title, Text, Paragraph } = Typography

/** llm_prompt 任务高级参数的默认值（与后端 llm_prompt provider 对齐；长提示词输出默认 4096） */
const LLM_DEFAULTS = { temperature: 0.2, maxTokens: 4096 }

/** 个人级大模型连接入口（工作区级连接已删除） */
const LLM_PERSONAL_HINT = '使用「个人设置 → 大模型」中的连接配置；未配置请先到个人设置填写 API Key'

const STATUS_META: Record<string, { color: string; label: string }> = {
  success: { color: 'green', label: '成功' },
  partial: { color: 'orange', label: '部分成功' },
  failed: { color: 'red', label: '失败' },
  running: { color: 'blue', label: '运行中' },
}

const CURSOR_LABEL: Record<string, string> = {
  date: '按日增量',
  datetime: '按时刻增量',
  key_set: '按幂等键去重',
  none: '每次全量',
}

/** 列表时间：`2026-10-20 17:10`（窄列不换行） */
function formatTime(value?: string | null): string {
  if (!value) return '—'
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return '—'
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function scheduleLabel(schedule?: SyncScheduleConfig | null): string {
  switch (schedule?.mode) {
    case 'daily':
      return `每天 ${schedule.at || '—'}`
    case 'interval':
      return `每 ${schedule.seconds ?? 0} 秒`
    case 'cron':
      return `cron ${schedule.expr || '—'}`
    case 'manual':
    default:
      return '手动'
  }
}

export default function DatasourcePage() {
  const { wid = '' } = useParams()
  const queryClient = useQueryClient()
  const { message, modal } = AntApp.useApp()

  const [drawerOpen, setDrawerOpen] = useState(false)
  const [editing, setEditing] = useState<SyncJob | null>(null)
  const [historyJob, setHistoryJob] = useState<SyncJob | null>(null)
  const [sessionModalOpen, setSessionModalOpen] = useState(false)

  const providersQuery = useQuery({
    queryKey: ['datasource', 'providers', wid],
    queryFn: () => datasourceApi.providers(wid),
    enabled: !!wid,
    staleTime: 300_000,
  })
  const jobsQuery = useQuery({
    queryKey: ['datasource', 'jobs', wid],
    queryFn: () => datasourceApi.listJobs(wid),
    enabled: !!wid,
  })
  const tablesQuery = useQuery({
    queryKey: ['workspaces', wid, 'tables'],
    queryFn: () => tableApi.list(wid),
    enabled: !!wid,
  })
  const sessionsQuery = useQuery({
    queryKey: ['datasource', 'sessions', wid],
    queryFn: () => datasourceApi.sessions(wid),
    enabled: !!wid,
  })
  const domainTemplatesQuery = useQuery({
    queryKey: ['datasource', 'domain-templates', wid],
    queryFn: () => datasourceApi.domainTemplates(wid),
    enabled: !!wid,
    staleTime: 300_000,
  })

  const providers = useMemo(() => providersQuery.data ?? [], [providersQuery.data])
  const jobs = useMemo(() => jobsQuery.data?.jobs ?? [], [jobsQuery.data])
  const tables = useMemo(() => tablesQuery.data ?? [], [tablesQuery.data])
  const sessions = useMemo(() => sessionsQuery.data ?? [], [sessionsQuery.data])
  const domainTemplates = useMemo(() => domainTemplatesQuery.data ?? [], [domainTemplatesQuery.data])

  const providerLabel = useCallback(
    (name: string) => providers.find(p => p.name === name)?.label ?? name,
    [providers],
  )
  const tableName = useCallback(
    (id: number | null) => (id == null ? '未绑定' : tables.find(t => Number(t.id) === id)?.name ?? `#${id}`),
    [tables],
  )

  const invalidate = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: ['datasource', 'jobs', wid] })
  }, [queryClient, wid])

  const runMutation = useMutation({
    mutationFn: (job: SyncJob) => datasourceApi.runJob(wid, job.id),
    onSuccess: result => {
      invalidate()
      if (result.run.status === 'failed') {
        message.error(`「${result.job.name}」同步失败：${result.run.error_message || '未知错误'}`)
      } else {
        message.success(
          `「${result.job.name}」${STATUS_META[result.run.status]?.label ?? result.run.status}：新增 ${result.run.inserted} / 更新 ${result.run.updated}`,
        )
      }
    },
    onError: () => message.error('运行失败（任务可能正在执行，请稍后再试）'),
  })

  const removeMutation = useMutation({
    mutationFn: (job: SyncJob) => datasourceApi.removeJob(wid, job.id),
    onSuccess: () => {
      invalidate()
      message.success('已删除同步任务')
    },
    onError: () => message.error('删除失败'),
  })

  const openCreate = () => {
    setEditing(null)
    setDrawerOpen(true)
  }
  const openEdit = (job: SyncJob) => {
    setEditing(job)
    setDrawerOpen(true)
  }
  const applyDomainTemplate = useCallback(
    async (job: SyncJob, template: DomainTemplate) => {
      if (job.table_id == null) {
        message.warning('该任务未绑定目标表，无法套用分析模板')
        return
      }
      // 模板字段名按 provider 默认输出；任务改过字段映射时要先对齐到目标字段名
      const { config, skipped } = materializeDomainTemplate(template, job.field_mapping)
      if (config.formulas.length === 0 && !config.chart && !config.summary) {
        message.error(`套用失败：模板字段与「${tableName(job.table_id)}」的字段映射对不上，没有可用配置`)
        return
      }
      try {
        await analyticsApi.createTemplate(wid, {
          name: `${job.name} · ${template.name}`,
          description: template.description,
          table_id: job.table_id,
          config,
        })
        message.success('已创建分析模板，可在「数据分析」页签打开')
        if (skipped.length > 0) {
          message.warning(`已跳过：${skipped.join('、')}（相关字段在字段映射里被丢弃）`)
        }
      } catch (err) {
        const detail = err instanceof Error && err.message ? err.message : '未知错误'
        message.error(`套用失败：${detail}`)
      }
    },
    [wid, message, tableName],
  )

  const confirmRemove = (job: SyncJob) => {
    modal.confirm({
      title: `删除同步任务「${job.name}」？`,
      content: '运行历史会一并删除，目标表中的数据保留。',
      okText: '删除',
      okButtonProps: { danger: true },
      cancelText: '取消',
      onOk: () => removeMutation.mutateAsync(job),
    })
  }

  const columns = useMemo(
    () => [
      {
        title: '名称',
        dataIndex: 'name',
        render: (name: string, job: SyncJob) => (
          <Space size={6}>
            <Text strong>{name}</Text>
            {!job.enabled && <Tag>已停用</Tag>}
          </Space>
        ),
      },
      {
        title: '适配器',
        dataIndex: 'provider',
        width: 190,
        render: (provider: string) => <Tag color="blue">{providerLabel(provider)}</Tag>,
      },
      {
        title: '目标表',
        dataIndex: 'table_id',
        width: 160,
        render: (id: number | null) => <Text type={id == null ? 'secondary' : undefined}>{tableName(id)}</Text>,
      },
      {
        title: '调度',
        dataIndex: 'schedule',
        width: 150,
        render: (schedule: SyncScheduleConfig) => <Text>{scheduleLabel(schedule)}</Text>,
      },
      {
        title: '上次运行',
        dataIndex: 'last_run_at',
        width: 190,
        render: (value: string | null, job: SyncJob) => {
          const meta = STATUS_META[job.last_status]
          return (
            <Space size={6}>
              {meta ? <Tag color={meta.color}>{meta.label}</Tag> : <Tag>未运行</Tag>}
              <Text type="secondary">{formatTime(value)}</Text>
            </Space>
          )
        },
      },
      {
        title: '操作',
        key: 'actions',
        width: 210,
        render: (_: unknown, job: SyncJob) => (
          <Space size={4}>
            <Tooltip title="立即运行">
              <Button
                size="small"
                type="text"
                aria-label={`立即运行 ${job.name}`}
                icon={<PlayCircleOutlined />}
                loading={runMutation.isPending && runMutation.variables?.id === job.id}
                onClick={() => runMutation.mutate(job)}
              />
            </Tooltip>
            <Tooltip title="运行历史">
              <Button
                size="small"
                type="text"
                aria-label={`运行历史 ${job.name}`}
                icon={<HistoryOutlined />}
                onClick={() => setHistoryJob(job)}
              />
            </Tooltip>
            <Dropdown
              trigger={['click']}
              disabled={job.table_id == null || domainTemplates.filter(t => t.provider === job.provider).length === 0}
              menu={{
                items: domainTemplates
                  .filter(template => template.provider === job.provider)
                  .map(template => ({
                    key: template.id,
                    label: template.name,
                    onClick: () => void applyDomainTemplate(job, template),
                  })),
              }}
            >
              <Button
                size="small"
                type="text"
                aria-label={`套用分析模板 ${job.name}`}
                title="套用领域分析模板"
                icon={<ExperimentOutlined />}
              />
            </Dropdown>
            <Tooltip title="编辑 / 预览">
              <Button
                size="small"
                type="text"
                aria-label={`编辑 ${job.name}`}
                icon={<EditOutlined />}
                onClick={() => openEdit(job)}
              />
            </Tooltip>
            <Tooltip title="删除">
              <Button
                size="small"
                type="text"
                danger
                aria-label={`删除 ${job.name}`}
                icon={<DeleteOutlined />}
                onClick={() => confirmRemove(job)}
              />
            </Tooltip>
          </Space>
        ),
      },
    ],
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [providerLabel, tableName, runMutation.isPending, runMutation.variables, domainTemplates, applyDomainTemplate, jobs],
  )

  return (
    <div style={{ padding: 16 }} data-testid="datasource-page">
      <Space style={{ width: '100%', justifyContent: 'space-between', marginBottom: 12 }}>
        <Space size={8}>
          <CloudDownloadOutlined />
          <Title level={4} style={{ margin: 0 }}>
            数据源同步
          </Title>
          <Text type="secondary">定期抓取外部数据并按幂等键写入数据表</Text>
        </Space>
        <Space size={8}>
          <Button type="primary" data-testid="datasource-create-btn" icon={<PlusOutlined />} onClick={openCreate}>
            新建同步任务
          </Button>
        </Space>
      </Space>

      <Table<SyncJob>
        data-testid="datasource-jobs-table"
        rowKey="id"
        size="small"
        loading={jobsQuery.isLoading}
        dataSource={jobs}
        columns={columns}
        pagination={false}
        locale={{
          emptyText: (
            <Empty
              description={
                <Space direction="vertical" size={2}>
                  <Text>还没有同步任务</Text>
                  <Text type="secondary">新建后可按每天 / 间隔 / cron 自动抓取</Text>
                </Space>
              }
            />
          ),
        }}
      />

      <JobDrawer
        wid={wid}
        open={drawerOpen}
        job={editing}
        providers={providers}
        tables={tables}
        sessions={sessions}
        onManageSessions={() => setSessionModalOpen(true)}
        onClose={() => setDrawerOpen(false)}
        onSaved={close => {
          invalidate()
          if (close) setDrawerOpen(false)
        }}
      />

      <SessionModal
        wid={wid}
        open={sessionModalOpen}
        sessions={sessions}
        onClose={() => setSessionModalOpen(false)}
        onSaved={() => void queryClient.invalidateQueries({ queryKey: ['datasource', 'sessions', wid] })}
      />

      <HistoryDrawer wid={wid} job={historyJob} onClose={() => setHistoryJob(null)} />
    </div>
  )
}

interface JobDrawerProps {
  wid: string
  open: boolean
  job: SyncJob | null
  providers: DatasourceProviderInfo[]
  tables: Array<{ id: number | string; name: string }>
  sessions: DatasourceSession[]
  onManageSessions: () => void
  onClose: () => void
  /** close=true 关闭抽屉；false 仅刷新列表（保存并预览时保留抽屉展示预览结果） */
  onSaved: (close: boolean) => void
}

/** 新建时的默认任务名：精确到秒，避免连续新建出现同名任务 */
function defaultJobName(): string {
  const now = new Date()
  const pad = (value: number) => String(value).padStart(2, '0')
  const date = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`
  const time = `${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}`
  return `同步任务 ${date} ${time}`
}

/** 新建 / 编辑抽屉：Provider 驱动 + 保存后抓取预览（预览不落库） */
function JobDrawer({
  wid,
  open,
  job,
  providers,
  tables,
  sessions,
  onManageSessions,
  onClose,
  onSaved,
}: JobDrawerProps) {
  const [form] = Form.useForm()
  const { message } = AntApp.useApp()
  const [saving, setSaving] = useState(false)
  const [previewing, setPreviewing] = useState(false)
  const [preview, setPreview] = useState<SyncPreviewResult | null>(null)
  const [savedJob, setSavedJob] = useState<SyncJob | null>(null)
  const [presetOpen, setPresetOpen] = useState(false)
  const [appliedPreset, setAppliedPreset] = useState<LlmPromptPreset | null>(null)

  // 保存并预览后抽屉保持打开（不关闭），此时任务已落库；后续保存必须走更新而不是再建一条
  const activeJob = job ?? savedJob
  const watchedName = Form.useWatch('name', form) as string | undefined

  useEffect(() => {
    if (!open) return
    setPreview(null)
    setSavedJob(null)
    setAppliedPreset(null)
    setPresetOpen(false)
    if (job) {
      form.setFieldsValue({
        name: job.name,
        provider: job.provider,
        table_id: job.table_id ?? undefined,
        url_template: job.request_spec?.url_template,
        data_path: job.request_spec?.data_path ?? undefined,
        model: job.request_spec?.llm?.model ?? undefined,
        temperature: job.request_spec?.llm?.temperature ?? LLM_DEFAULTS.temperature,
        max_tokens: job.request_spec?.llm?.max_tokens ?? LLM_DEFAULTS.maxTokens,
        json_mode: job.request_spec?.llm?.json_mode ?? true,
        system_prompt: job.request_spec?.prompt?.system ?? undefined,
        user_template: job.request_spec?.prompt?.user_template ?? undefined,
        entrant_param: job.entrant_param ?? undefined,
        entrant_keys: job.entrant_keys ?? [],
        match_keys: job.match_keys ?? [],
        cursor_strategy: job.cursor?.strategy ?? 'date',
        cursor_field: job.cursor?.field ?? undefined,
        backfill_start: job.cursor?.backfill_start ?? undefined,
        schedule_mode: job.schedule?.mode ?? 'manual',
        schedule_at: job.schedule?.at ?? undefined,
        schedule_seconds: job.schedule?.seconds ?? undefined,
        schedule_expr: job.schedule?.expr ?? undefined,
        session_id: job.session_id ?? undefined,
        rate_limit_ms: job.rate_limit_ms ?? 0,
        paging_mode: job.request_spec?.paging?.mode ?? 'none',
        page_size: job.request_spec?.paging?.page_size ?? 50,
        time_window_mode: job.request_spec?.time_window?.mode ?? 'none',
        chunk_days: job.request_spec?.time_window?.chunk_days ?? 0,
        enabled: job.enabled,
      })
    } else {
      form.resetFields()
      const defaultProvider = providers[0]
      form.setFieldsValue({
        name: defaultJobName(),
        provider: defaultProvider?.name,
        cursor_strategy: defaultProvider?.default_cursor ?? 'date',
        schedule_mode: 'manual',
        paging_mode: 'none',
        time_window_mode: 'none',
        page_size: 50,
        chunk_days: 0,
        temperature: LLM_DEFAULTS.temperature,
        max_tokens: LLM_DEFAULTS.maxTokens,
        json_mode: true,
        entrant_keys: [],
        match_keys: [],
        enabled: true,
        rate_limit_ms: 0,
      })
    }
  }, [open, job, form, providers])

  const buildRequestSpec = useCallback(
    (values: Record<string, unknown>): SyncRequestSpec => {
      const timeWindow = values.time_window_mode === 'none'
        ? { mode: 'none' as const }
        : { mode: 'range' as const, chunk_days: Number(values.chunk_days) || 0 }
      if (values.provider === 'llm_prompt') {
        // 极简口径（ADR 0019）：API 地址 / 模型 / Key 由当前用户的「个人设置 → 大模型」
        // 连接配置提供，request_spec 只带提示词与可选的模型参数覆盖；分页与响应路径不适用。
        const prompt: SyncRequestSpec['prompt'] = {
          user_template: String(values.user_template ?? '').trim(),
        }
        const system = String(values.system_prompt ?? '').trim()
        if (system) prompt.system = system
        const spec: SyncRequestSpec = { prompt, time_window: timeWindow }
        const temperature = Number(values.temperature ?? LLM_DEFAULTS.temperature)
        const maxTokens = Number(values.max_tokens ?? LLM_DEFAULTS.maxTokens)
        const jsonMode = values.json_mode == null ? true : Boolean(values.json_mode)
        // 仅在用户动过高级参数时显式覆盖，默认交给工作区连接 / 后端默认值
        if (
          temperature !== LLM_DEFAULTS.temperature
          || maxTokens !== LLM_DEFAULTS.maxTokens
          || jsonMode !== true
        ) {
          spec.llm = { temperature, max_tokens: maxTokens, json_mode: jsonMode }
        }
        return spec
      }
      const paging = values.paging_mode === 'none'
        ? { mode: 'none' as const }
        : { mode: values.paging_mode as 'page' | 'offset', page_size: Number(values.page_size) || 50, max_pages: 100 }
      return {
        url_template: String(values.url_template ?? '').trim(),
        data_path: (values.data_path as string) || null,
        paging,
        time_window: timeWindow,
      }
    },
    [],
  )

  const buildPayload = useCallback(async (): Promise<SyncJobPayload> => {
    const validated = await form.validateFields()
    // LLM 的主表单极简，调度 / 幂等键 / 模型参数都在收起的「高级设置」里，
    // 未挂载字段不会出现在 validateFields 结果里，需要用 store 值兜底；
    // 非 LLM 任务保持原有口径（只用已挂载字段），避免默认 provider 行为变化。
    const values = form.getFieldValue('provider') === 'llm_prompt'
      ? { ...(form.getFieldsValue(true) as Record<string, unknown>), ...validated }
      : validated
    return {
      name: String(values.name).trim(),
      provider: String(values.provider),
      table_id: values.table_id == null ? null : Number(values.table_id),
      request_spec: buildRequestSpec(values),
      entrant_param: values.entrant_param || null,
      entrant_keys: (values.entrant_keys ?? []).map(String),
      match_keys: (values.match_keys ?? []).map(String),
      cursor: {
        strategy: values.cursor_strategy,
        field: values.cursor_field || '',
        backfill_start: values.backfill_start || '',
      },
      schedule: {
        mode: values.schedule_mode,
        at: values.schedule_mode === 'daily' ? values.schedule_at : '',
        seconds: values.schedule_mode === 'interval' ? Number(values.schedule_seconds) || 0 : 0,
        expr: values.schedule_mode === 'cron' ? values.schedule_expr : '',
      },
      enabled: Boolean(values.enabled),
      session_id: values.session_id == null ? null : Number(values.session_id),
      rate_limit_ms: Number(values.rate_limit_ms) || 0,
    }
  }, [form, buildRequestSpec])

  /** llm_prompt 依赖当前用户的个人大模型连接；未配置时由后端返回 400 detail（已在保存错误里 toast） */
  const handleSave = async (thenPreview: boolean) => {
    setSaving(true)
    try {
      const payload = await buildPayload()
      // 新建后「保存并预览」不关闭抽屉，第二次保存要复用已创建的任务，避免重复建
      const target = job ?? savedJob
      const saved = target
        ? await datasourceApi.updateJob(wid, target.id, payload)
        : await datasourceApi.createJob(wid, payload)
      setSavedJob(saved)
      message.success(target ? '已保存' : '已创建')
      if (!thenPreview) {
        onSaved(true)
        return
      }
      setPreviewing(true)
      try {
        setPreview(await datasourceApi.previewJob(wid, saved.id, 20))
      } catch {
        message.error('抓取预览失败（源可能不可达或配置有误）')
      } finally {
        setPreviewing(false)
      }
      // 保存并预览：只刷新列表，不关闭抽屉，方便对照 suggested_match_keys
      onSaved(false)
    } catch (error) {
      const detail = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      message.error(detail || '保存失败，请检查表单')
    } finally {
      setSaving(false)
    }
  }

  const providerOptions = providers.map(p => ({ value: p.name, label: p.label }))
  const activeProvider = Form.useWatch('provider', form) as string | undefined
  const providerInfo = providers.find(p => p.name === activeProvider)
  const isLlm = activeProvider === 'llm_prompt'
  // 折叠面板未展开时对应 Form.Item 尚未挂载，watch 拿不到值，回退到任务本身
  const scheduleMode = (Form.useWatch('schedule_mode', form) as string | undefined) ?? activeJob?.schedule?.mode
  const cursorStrategy = Form.useWatch('cursor_strategy', form) as string | undefined
  const timeWindowMode = Form.useWatch('time_window_mode', form) as string | undefined
  const pagingMode = Form.useWatch('paging_mode', form) as string | undefined

  const onProviderChange = (value: string) => {
    const info = providers.find(p => p.name === value)
    if (!info) return
    form.setFieldValue('cursor_strategy', info.default_cursor)
    const fields = info.params_schema?.fields ?? []
    const urlDefault = fields.find(f => f.name === 'url_template')?.default
    if (typeof urlDefault === 'string' && urlDefault) form.setFieldValue('url_template', urlDefault)
    // 例如 llm_prompt 的 temperature / max_tokens / json_mode 默认值
    const defaults = Object.fromEntries(
      fields.filter(f => f.default !== undefined && f.name !== 'url_template').map(f => [f.name, f.default]),
    )
    if (Object.keys(defaults).length > 0) form.setFieldsValue(defaults)
    if (value === 'llm_prompt' && !form.getFieldValue('json_mode')) form.setFieldValue('json_mode', true)
    if (value !== 'llm_prompt') setAppliedPreset(null)
  }

  const applyPreset = (preset: LlmPromptPreset) => {
    form.setFieldValue('user_template', preset.prompt)
    setAppliedPreset(preset)
    setPresetOpen(false)
    message.success(`已填入「${preset.name}」提示词，可按需修改`)
  }

  return (
    <>
      <Drawer
        title={activeJob ? `编辑同步任务 · ${watchedName?.trim() || activeJob.name}` : '新建同步任务'}
        width={720}
        open={open}
        onClose={onClose}
        forceRender
        destroyOnClose
        extra={
          <Space>
            <Button onClick={onClose}>取消</Button>
            <Button data-testid="datasource-save-btn" loading={saving} onClick={() => void handleSave(false)}>
              保存
            </Button>
            <Button
              type="primary"
              data-testid="datasource-save-preview-btn"
              loading={saving || previewing}
              onClick={() => void handleSave(true)}
            >
              保存并预览
            </Button>
          </Space>
        }
      >
        <Form form={form} layout="vertical" size="small">
          <Space size={12} style={{ display: 'flex' }}>
            <Form.Item name="name" label="任务名称" rules={[{ required: true, message: '请输入任务名称' }]} style={{ flex: 1 }}>
              <Input data-testid="datasource-name-input" placeholder="例如：北京天气日报" />
            </Form.Item>
            <Form.Item name="provider" label="适配器" rules={[{ required: true }]} style={{ width: 220 }}>
              <Select options={providerOptions} onChange={onProviderChange} />
            </Form.Item>
          </Space>

          {isLlm ? (
            <>
              <Alert
                data-testid="datasource-llm-personal-hint"
                type="info"
                showIcon
                style={{ marginBottom: 16 }}
                message={LLM_PERSONAL_HINT}
                description="API 地址 / 模型 / API Key 在个人设置里配置一次即可，所有提示词任务共用你的个人配置。"
              />

              <Form.Item name="table_id" label="目标表（留空则按任务名自动建表）" style={{ flex: 1 }}>
                <Select
                  allowClear
                  showSearch
                  optionFilterProp="label"
                  placeholder="留空自动建表"
                  options={tables.map(t => ({ value: Number(t.id), label: t.name }))}
                />
              </Form.Item>

              <Form.Item
                name="user_template"
                label="用户提示词"
                rules={[{ required: true, message: '请输入用户提示词' }]}
                extra="描述要抓取的数据，并强制模型只输出 JSON（对象数组或 rows 包裹）；可用 {today} 占位符，JSON 花括号可直接书写。"
              >
                <Input.TextArea
                  data-testid="datasource-llm-user"
                  rows={6}
                  placeholder={'例如：请汇总 {today} 的每日新闻摘要，只输出 JSON 对象数组，字段用英文 snake_case。'}
                />
              </Form.Item>

              <Space size={8} style={{ marginBottom: 16 }} wrap>
                <Button
                  icon={<ExperimentOutlined />}
                  data-testid="datasource-llm-presets-btn"
                  onClick={() => setPresetOpen(true)}
                >
                  推荐提示词（{LLM_PROMPT_PRESETS.length} 组）
                </Button>
                <Text type="secondary" style={{ fontSize: 12 }}>
                  选择典型场景一键填入，再按需修改；每组含建议目标表字段与幂等键
                </Text>
              </Space>

              {appliedPreset && (
                <Alert
                  data-testid="datasource-llm-preset-hint"
                  type="info"
                  showIcon
                  closable
                  style={{ marginBottom: 16 }}
                  onClose={() => setAppliedPreset(null)}
                  message={`已套用推荐场景：${appliedPreset.name}`}
                  description={`建议目标表字段：${appliedPreset.target_fields.join('、')}；建议幂等键：${appliedPreset.match_keys.join('、')}`}
                />
              )}

              <Collapse
                size="small"
                ghost
                items={[
                  {
                    key: 'advanced',
                    label: '高级设置（系统提示词 / 幂等键 / 调度 / 时间区间 / 凭证会话 / 模型参数）',
                    children: (
                      <>
                        <Form.Item
                          name="system_prompt"
                          label="系统提示词覆盖"
                          extra="留空使用内置默认；内置默认全文可在「个人设置 → 大模型」里查看"
                        >
                          <Input.TextArea
                            data-testid="datasource-llm-system"
                            rows={2}
                            placeholder="留空即为内置默认（强制只输出 JSON）"
                          />
                        </Form.Item>

                        <Form.Item
                          name="match_keys"
                          label="幂等键（留空自动识别）"
                          extra={
                            scheduleMode === 'cron'
                              ? '留空由后端自动识别；cron 任务建议预览后确认自动识别的幂等键，避免每轮重复插入'
                              : '留空由后端按返回字段自动识别；配置后按目标表字段去重'
                          }
                        >
                          <Select mode="tags" tokenSeparators={[',', ' ']} placeholder="如 date, city" />
                        </Form.Item>

                        <Space size={12} style={{ display: 'flex' }}>
                          <Form.Item name="entrant_param" label="标的占位符名" style={{ width: 160 }}>
                            <Input placeholder="city / symbol" />
                          </Form.Item>
                          <Form.Item
                            name="entrant_keys"
                            label="标的取值"
                            style={{ flex: 1 }}
                            extra="每个取值各抓一次；留空表示只抓一次"
                          >
                            <Select mode="tags" tokenSeparators={[',', ' ']} placeholder="输入后回车，如 北京" />
                          </Form.Item>
                        </Space>

                        <Space size={12} style={{ display: 'flex' }}>
                          <Form.Item name="schedule_mode" label="调度" style={{ width: 150 }}>
                            <Select
                              options={[
                                { value: 'manual', label: '手动' },
                                { value: 'daily', label: '每天定时' },
                                { value: 'interval', label: '固定间隔' },
                                { value: 'cron', label: 'cron' },
                              ]}
                            />
                          </Form.Item>
                          {scheduleMode === 'daily' && (
                            <Form.Item name="schedule_at" label="时刻（HH:MM）" style={{ width: 150 }}>
                              <Input placeholder="17:10" />
                            </Form.Item>
                          )}
                          {scheduleMode === 'interval' && (
                            <Form.Item name="schedule_seconds" label="间隔（秒）" style={{ width: 150 }}>
                              <InputNumber min={1} style={{ width: '100%' }} />
                            </Form.Item>
                          )}
                          {scheduleMode === 'cron' && (
                            <Form.Item name="schedule_expr" label="cron 表达式" style={{ flex: 1 }}>
                              <Input placeholder="0 7 * * *" />
                            </Form.Item>
                          )}
                        </Space>

                        <Space size={12} style={{ display: 'flex' }}>
                          <Form.Item name="cursor_strategy" label="增量策略" style={{ width: 180 }}>
                            <Select options={Object.entries(CURSOR_LABEL).map(([value, label]) => ({ value, label }))} />
                          </Form.Item>
                          <Form.Item name="cursor_field" label="增量字段" style={{ flex: 1 }}>
                            <Input
                              disabled={cursorStrategy === 'none' || cursorStrategy === 'key_set'}
                              placeholder="day / published_at"
                            />
                          </Form.Item>
                          <Form.Item name="backfill_start" label="回填起点" style={{ width: 150 }}>
                            <Input
                              disabled={cursorStrategy === 'none' || cursorStrategy === 'key_set'}
                              placeholder="2024-01-01"
                            />
                          </Form.Item>
                        </Space>

                        <Space size={12} style={{ display: 'flex' }}>
                          <Form.Item name="time_window_mode" label="时间区间" style={{ width: 150 }}>
                            <Select
                              options={[
                                { value: 'none', label: '不注入' },
                                { value: 'range', label: '按游标区间' },
                              ]}
                            />
                          </Form.Item>
                          {timeWindowMode === 'range' && (
                            <Form.Item name="chunk_days" label="切片天数（0=不切）" style={{ width: 160 }}>
                              <InputNumber min={0} max={3650} style={{ width: '100%' }} />
                            </Form.Item>
                          )}
                        </Space>

                        <Space size={12} style={{ display: 'flex' }}>
                          <Form.Item
                            name="session_id"
                            label={
                              <Space size={4}>
                                凭证会话（可选覆盖）
                                <Button
                                  type="link"
                                  size="small"
                                  data-testid="datasource-session-create"
                                  icon={<KeyOutlined />}
                                  onClick={onManageSessions}
                                >
                                  新建
                                </Button>
                              </Space>
                            }
                            style={{ flex: 1 }}
                            extra="默认使用你在「个人设置 → 大模型」中配置的 Key；留空即可"
                          >
                            <Select
                              allowClear
                              placeholder="默认使用个人设置中的大模型配置"
                              options={sessions.map(item => ({
                                value: item.id,
                                label: item.secret_keys.length
                                  ? `${item.name}（密钥: ${item.secret_keys.join(', ')}）`
                                  : item.name,
                              }))}
                            />
                          </Form.Item>
                          <Form.Item name="rate_limit_ms" label="请求间隔（毫秒）" style={{ width: 190 }}>
                            <InputNumber min={0} max={60000} step={100} style={{ width: '100%' }} />
                          </Form.Item>
                        </Space>

                        <Space size={12} style={{ display: 'flex' }}>
                          <Form.Item name="temperature" label="temperature" style={{ width: 140 }}>
                            <InputNumber min={0} max={2} step={0.1} style={{ width: '100%' }} />
                          </Form.Item>
                          <Form.Item name="max_tokens" label="max_tokens" style={{ width: 140 }}>
                            <InputNumber min={1} max={32768} style={{ width: '100%' }} />
                          </Form.Item>
                          <Form.Item name="json_mode" label="JSON 模式" valuePropName="checked" style={{ width: 110 }}>
                            <Switch />
                          </Form.Item>
                          <Form.Item name="enabled" label="启用" valuePropName="checked" style={{ width: 90 }}>
                            <Switch data-testid="datasource-enabled" />
                          </Form.Item>
                        </Space>
                      </>
                    ),
                  },
                ]}
              />
            </>
          ) : (
            <>
              <Space size={12} style={{ display: 'flex' }}>
                <Form.Item name="table_id" label="目标表（留空则只抓不写）" style={{ flex: 1 }}>
                  <Select
                    allowClear
                    showSearch
                    optionFilterProp="label"
                    placeholder="选择数据表"
                    options={tables.map(t => ({ value: Number(t.id), label: t.name }))}
                  />
                </Form.Item>
                <Form.Item name="enabled" label="启用" valuePropName="checked" style={{ width: 90 }}>
                  <Switch />
                </Form.Item>
              </Space>

              <Space size={12} style={{ display: 'flex' }}>
                <Form.Item
                  name="session_id"
                  label={
                    <Space size={4}>
                      凭证会话
                      <Button
                        type="link"
                        size="small"
                        data-testid="datasource-session-create"
                        icon={<KeyOutlined />}
                        onClick={onManageSessions}
                      >
                        新建
                      </Button>
                    </Space>
                  }
                  style={{ flex: 1 }}
                  extra="会话提供请求头与密钥；请求模板里可用 {密钥名} 占位"
                >
                  <Select
                    allowClear
                    placeholder="不使用会话（凭据内联在请求模板里）"
                    options={sessions.map(item => ({
                      value: item.id,
                      label: item.secret_keys.length ? `${item.name}（密钥: ${item.secret_keys.join(', ')}）` : item.name,
                    }))}
                  />
                </Form.Item>
                <Form.Item
                  name="rate_limit_ms"
                  label="请求间隔（毫秒）"
                  style={{ width: 190 }}
                  extra="同一任务相邻请求最小间隔，0 = 不限速"
                >
                  <InputNumber min={0} max={60000} step={100} style={{ width: '100%' }} />
                </Form.Item>
              </Space>

              <Form.Item
                name="url_template"
                label="URL 模板"
                rules={[{ required: true, message: '请输入 http/https URL 模板' }]}
                extra={
                  providerInfo?.params_schema?.placeholders?.length
                    ? `可用占位符：${providerInfo.params_schema.placeholders.map(p => `{${p}}`).join(' ')}`
                    : '占位符用 {name}，只做字面替换'
                }
              >
                <Input.TextArea
                  data-testid="datasource-url-template"
                  rows={2}
                  placeholder="https://api.example.com/data?city={city}&from={start}&to={end}"
                />
              </Form.Item>

              <Space size={12} style={{ display: 'flex' }}>
                <Form.Item name="data_path" label="响应数组路径" style={{ flex: 1 }}>
                  <Input placeholder="data.items（留空自动探测 data / items / results）" />
                </Form.Item>
                <Form.Item name="entrant_param" label="标的占位符名" style={{ width: 160 }}>
                  <Input placeholder="city / symbol" />
                </Form.Item>
              </Space>

              <Form.Item name="entrant_keys" label="标的取值" extra="每个取值各抓一次；留空表示只抓一次">
                <Select mode="tags" tokenSeparators={[',', ' ']} placeholder="输入后回车，如 北京" />
              </Form.Item>

              <Form.Item
                name="match_keys"
                label="幂等键"
                extra="必须是目标表字段；留空则纯追加（仅快照类源适用）"
              >
                <Select mode="tags" tokenSeparators={[',', ' ']} placeholder="如 city, day" />
              </Form.Item>

              <Collapse
                size="small"
                ghost
                items={[
                  {
                    key: 'advanced',
                    label: '增量与调度',
                    children: (
                      <>
                        <Space size={12} style={{ display: 'flex' }}>
                          <Form.Item name="cursor_strategy" label="增量策略" style={{ width: 180 }}>
                            <Select
                              options={Object.entries(CURSOR_LABEL).map(([value, label]) => ({ value, label }))}
                            />
                          </Form.Item>
                          <Form.Item name="cursor_field" label="增量字段" style={{ flex: 1 }}>
                            <Input disabled={cursorStrategy === 'none' || cursorStrategy === 'key_set'} placeholder="day / published_at" />
                          </Form.Item>
                          <Form.Item name="backfill_start" label="回填起点" style={{ width: 150 }}>
                            <Input
                              disabled={cursorStrategy === 'none' || cursorStrategy === 'key_set'}
                              placeholder="2024-01-01"
                            />
                          </Form.Item>
                        </Space>

                        <Space size={12} style={{ display: 'flex' }}>
                          <Form.Item name="schedule_mode" label="调度" style={{ width: 150 }}>
                            <Select
                              options={[
                                { value: 'manual', label: '手动' },
                                { value: 'daily', label: '每天定时' },
                                { value: 'interval', label: '固定间隔' },
                                { value: 'cron', label: 'cron' },
                              ]}
                            />
                          </Form.Item>
                          {scheduleMode === 'daily' && (
                            <Form.Item name="schedule_at" label="时刻（HH:MM）" style={{ width: 150 }}>
                              <Input placeholder="17:10" />
                            </Form.Item>
                          )}
                          {scheduleMode === 'interval' && (
                            <Form.Item name="schedule_seconds" label="间隔（秒）" style={{ width: 150 }}>
                              <InputNumber min={1} style={{ width: '100%' }} />
                            </Form.Item>
                          )}
                          {scheduleMode === 'cron' && (
                            <Form.Item name="schedule_expr" label="cron 表达式" style={{ flex: 1 }}>
                              <Input placeholder="0 7 * * *" />
                            </Form.Item>
                          )}
                        </Space>

                        <Space size={12} style={{ display: 'flex' }}>
                          <Form.Item name="paging_mode" label="分页" style={{ width: 150 }}>
                            <Select
                              options={[
                                { value: 'none', label: '不分页' },
                                { value: 'page', label: '页码' },
                                { value: 'offset', label: '偏移量' },
                              ]}
                            />
                          </Form.Item>
                          {pagingMode !== 'none' && (
                            <Form.Item name="page_size" label="每页条数" style={{ width: 150 }}>
                              <InputNumber min={1} max={1000} style={{ width: '100%' }} />
                            </Form.Item>
                          )}
                          <Form.Item name="time_window_mode" label="时间区间" style={{ width: 150 }}>
                            <Select
                              options={[
                                { value: 'none', label: '不注入' },
                                { value: 'range', label: '按游标区间' },
                              ]}
                            />
                          </Form.Item>
                          {timeWindowMode === 'range' && (
                            <Form.Item name="chunk_days" label="切片天数（0=不切）" style={{ width: 160 }}>
                              <InputNumber min={0} max={3650} style={{ width: '100%' }} />
                            </Form.Item>
                          )}
                        </Space>
                      </>
                    ),
                  },
                ]}
              />
            </>
          )}
        </Form>

        {preview && (
          <PreviewPanel
            preview={preview}
            onRefresh={
              activeJob
                ? async () => {
                    setPreviewing(true)
                    try {
                      setPreview(await datasourceApi.previewJob(wid, activeJob.id, 20))
                    } catch {
                      message.error('抓取预览失败')
                    } finally {
                      setPreviewing(false)
                    }
                  }
                : undefined
            }
            refreshing={previewing}
          />
        )}
        {!preview && activeJob && (
          <Button icon={<EyeOutlined />} loading={previewing} onClick={() => void handleSave(true)}>
            抓取预览（不落库）
          </Button>
        )}
      </Drawer>

      <LlmPresetModal open={presetOpen} onClose={() => setPresetOpen(false)} onUse={applyPreset} />
    </>
  )
}

/** 预览面板：失败明细 + 前 20 行 + 归一失败 */
function PreviewPanel({
  preview,
  onRefresh,
  refreshing,
}: {
  preview: SyncPreviewResult
  onRefresh?: () => Promise<void>
  refreshing: boolean
}) {
  const columns = preview.columns.slice(0, 8).map(key => ({
    title: key,
    dataIndex: key,
    ellipsis: true,
    render: (value: unknown) => (value == null ? '—' : String(value)),
  }))
  return (
    <div style={{ marginTop: 8 }}>
      <Space style={{ marginBottom: 8 }}>
        <Tag color={STATUS_META[preview.status]?.color ?? 'default'}>
          {STATUS_META[preview.status]?.label ?? preview.status}
        </Tag>
        <Text type="secondary">
          共 {preview.total} 行 · 请求 {preview.plans} 个（成功 {preview.succeeded}）
          {preview.cursor_from ? ` · 区间 ${preview.cursor_from} → ${preview.cursor_to || '—'}` : ''}
        </Text>
        {onRefresh && (
          <Button size="small" loading={refreshing} onClick={() => void onRefresh()}>
            重新抓取
          </Button>
        )}
      </Space>
      {preview.suggested_match_keys && preview.suggested_match_keys.length > 0 && (
        <Alert
          data-testid="datasource-preview-match-keys"
          type="success"
          showIcon
          style={{ marginBottom: 8 }}
          message={`自动识别幂等键：${preview.suggested_match_keys.join(', ')}`}
          description="可在「高级设置 → 幂等键」里采用，或直接保存由后端按此去重。"
        />
      )}
      {preview.failures.length > 0 && (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 8 }}
          message={`${preview.failures.length} 个请求失败`}
          description={preview.failures.map(f => `${f.label}: ${f.error}`).join('；')}
        />
      )}
      {preview.normalize_failures.length > 0 && (
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 8 }}
          message={`${preview.normalize_failures.length} 个字段归一失败（已降级为空值）`}
          description={preview.normalize_failures
            .slice(0, 5)
            .map(f => `第 ${f.row_index + 1} 行 ${f.field}: ${f.reason}`)
            .join('；')}
        />
      )}
      <Table
        rowKey={(_, index) => String(index)}
        size="small"
        dataSource={preview.rows}
        columns={columns}
        pagination={false}
        scroll={{ x: 'max-content' }}
        locale={{ emptyText: '没有抓到数据' }}
      />
    </div>
  )
}

function HistoryDrawer({ wid, job, onClose }: { wid: string; job: SyncJob | null; onClose: () => void }) {
  const runsQuery = useQuery({
    queryKey: ['datasource', 'runs', wid, job?.id],
    queryFn: () => datasourceApi.runs(wid, job?.id ?? 0, { limit: 50 }),
    enabled: !!job,
  })

  const columns = [
    {
      title: '开始时间',
      dataIndex: 'started_at',
      width: 150,
      render: (value: string) => formatTime(value),
    },
    { title: '触发', dataIndex: 'trigger', width: 90 },
    {
      title: '状态',
      dataIndex: 'status',
      width: 100,
      render: (status: string) => (
        <Tag color={STATUS_META[status]?.color ?? 'default'}>{STATUS_META[status]?.label ?? status}</Tag>
      ),
    },
    {
      title: '游标',
      key: 'cursor',
      width: 200,
      render: (_: unknown, run: SyncRun) =>
        run.cursor_from || run.cursor_to ? `${run.cursor_from || '—'} → ${run.cursor_to || '—'}` : '—',
    },
    {
      title: '新增 / 更新',
      key: 'counts',
      width: 110,
      render: (_: unknown, run: SyncRun) => `${run.inserted} / ${run.updated}`,
    },
    { title: '耗时', dataIndex: 'duration_ms', width: 90, render: (ms: number) => `${ms} ms` },
    {
      title: '说明',
      key: 'error',
      ellipsis: true,
      render: (_: unknown, run: SyncRun) => run.error_message || '—',
    },
  ]

  return (
    <Drawer
      title={job ? `运行历史 · ${job.name}` : '运行历史'}
      width={880}
      open={!!job}
      onClose={onClose}
      destroyOnClose
    >
      <Table<SyncRun>
        rowKey="id"
        size="small"
        loading={runsQuery.isLoading}
        dataSource={runsQuery.data?.runs ?? []}
        columns={columns}
        pagination={false}
        locale={{ emptyText: '还没有运行记录' }}
      />
    </Drawer>
  )
}

/** 凭证会话管理：列表 + 新建 / 编辑（改请求头、整体替换密钥）/ 删除（自动解绑任务） */
function SessionModal({
  wid,
  open,
  sessions,
  onClose,
  onSaved,
}: {
  wid: string
  open: boolean
  sessions: DatasourceSession[]
  onClose: () => void
  onSaved: () => void
}) {
  const { message, modal } = AntApp.useApp()
  const [editing, setEditing] = useState<DatasourceSession | null>(null)
  const [formOpen, setFormOpen] = useState(false)

  useEffect(() => {
    if (!open) {
      setFormOpen(false)
      setEditing(null)
    }
  }, [open])

  const openCreate = () => {
    setEditing(null)
    setFormOpen(true)
  }

  const openEdit = (session: DatasourceSession) => {
    setEditing(session)
    setFormOpen(true)
  }

  const confirmRemove = (session: DatasourceSession) => {
    modal.confirm({
      title: `删除会话「${session.name}」？`,
      content: '引用它的同步任务会自动解绑（任务保留，但请求不再带这组请求头与密钥）。',
      okText: '删除',
      okButtonProps: { danger: true },
      cancelText: '取消',
      onOk: async () => {
        try {
          await datasourceApi.removeSession(wid, session.id)
          message.success('会话已删除')
          onSaved()
        } catch {
          message.error('删除失败（需编辑者及以上权限）')
        }
      },
    })
  }

  return (
    <>
      <Modal
        title="凭证会话"
        open={open}
        width={640}
        onCancel={onClose}
        destroyOnHidden
        footer={<Button onClick={onClose}>关闭</Button>}
      >
        <Space direction="vertical" style={{ width: '100%' }} size={8}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <Button size="small" type="primary" icon={<PlusOutlined />} data-testid="datasource-session-new" onClick={openCreate}>
              新建会话
            </Button>
            <Text type="secondary" style={{ fontSize: 12 }}>
              密钥加密存储，读接口只回显键名；不随工作区导出
            </Text>
          </div>
          <Table<DatasourceSession>
            data-testid="datasource-sessions-table"
            rowKey="id"
            size="small"
            pagination={false}
            dataSource={sessions}
            locale={{ emptyText: '还没有凭证会话' }}
            columns={[
              { title: '名称', dataIndex: 'name', ellipsis: true },
              {
                title: '密钥',
                dataIndex: 'secret_keys',
                width: 200,
                render: (keys: string[]) =>
                  keys.length ? (
                    <Space size={4} wrap>
                      {keys.map(key => (
                        <Tag key={key} color="blue">
                          {key}
                        </Tag>
                      ))}
                    </Space>
                  ) : (
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      未配置
                    </Text>
                  ),
              },
              {
                title: '请求头',
                dataIndex: 'headers',
                width: 90,
                render: (headers: Record<string, string>) => `${Object.keys(headers ?? {}).length} 项`,
              },
              {
                title: '操作',
                width: 110,
                render: (_: unknown, session: DatasourceSession) => (
                  <Space size={2}>
                    <Button
                      size="small"
                      type="text"
                      aria-label={`编辑会话 ${session.name}`}
                      icon={<EditOutlined />}
                      onClick={() => openEdit(session)}
                    />
                    <Button
                      size="small"
                      type="text"
                      danger
                      aria-label={`删除会话 ${session.name}`}
                      icon={<DeleteOutlined />}
                      onClick={() => confirmRemove(session)}
                    />
                  </Space>
                ),
              },
            ]}
          />
        </Space>
      </Modal>
      <SessionFormModal
        wid={wid}
        open={formOpen}
        editing={editing}
        onBack={() => setFormOpen(false)}
        onSaved={onSaved}
      />
    </>
  )
}

/** 会话表单态：form 实例只在这里创建，避免列表态下 useForm 未连接 Form 的 dev 警告 */
function SessionFormModal({
  wid,
  open,
  editing,
  onBack,
  onSaved,
}: {
  wid: string
  open: boolean
  editing: DatasourceSession | null
  onBack: () => void
  onSaved: () => void
}) {
  const [form] = Form.useForm()
  const { message } = AntApp.useApp()
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (!open) {
      form.resetFields()
      return
    }
    if (editing) {
      form.setFieldsValue({
        name: editing.name,
        headers_json: Object.keys(editing.headers ?? {}).length ? JSON.stringify(editing.headers, null, 2) : '',
        secrets_json: '',
      })
    } else {
      form.resetFields()
    }
  }, [open, editing, form])

  const submit = async () => {
    const values = await form.validateFields()
    let headers: Record<string, string> = {}
    let secrets: Record<string, string> = {}
    try {
      if (values.headers_json?.trim()) headers = JSON.parse(values.headers_json) as Record<string, string>
      if (values.secrets_json?.trim()) secrets = JSON.parse(values.secrets_json) as Record<string, string>
    } catch {
      message.error('请求头 / 密钥不是合法 JSON')
      return
    }
    const hasSecrets = Boolean(values.secrets_json?.trim())
    setSaving(true)
    try {
      if (editing) {
        // 密钥留空 = 保持原密文不变（后端「提供即整体替换」，所以不填就不要传这个键）
        await datasourceApi.updateSession(wid, editing.id, {
          name: String(values.name).trim(),
          headers,
          ...(hasSecrets ? { secrets } : {}),
        })
        message.success('会话已更新')
      } else {
        await datasourceApi.createSession(wid, { name: String(values.name).trim(), headers, secrets })
        message.success('会话已创建，可在任务里选用')
      }
      onSaved()
      onBack()
    } catch (error) {
      const detail = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      message.error(detail || (editing ? '更新失败（名称可能重复）' : '创建失败（名称可能重复）'))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      title={editing ? '编辑凭证会话' : '新建凭证会话'}
      open={open}
      width={640}
      onCancel={onBack}
      forceRender
      destroyOnHidden
      footer={
        <Space>
          <Button onClick={onBack}>返回</Button>
          <Button type="primary" loading={saving} data-testid="datasource-session-save" onClick={() => void submit()}>
            保存
          </Button>
        </Space>
      }
    >
      <Form form={form} layout="vertical" size="small">
        <Form.Item name="name" label="名称" rules={[{ required: true, message: '请输入会话名称' }]}>
          <Input data-testid="datasource-session-name" placeholder="如：行情源 A" />
        </Form.Item>
        <Form.Item name="headers_json" label="请求头（JSON）" extra='如 {"User-Agent": "cndb-sync/1.0"}'>
          <Input.TextArea data-testid="datasource-session-headers" rows={2} />
        </Form.Item>
        <Form.Item
          name="secrets_json"
          label="密钥（JSON，加密入库、保存后不可回读）"
          extra={
            editing
              ? `已有密钥：${editing.secret_keys.join('、') || '无'}；留空表示不修改，填写则整体替换`
              : '如 {"api_key": "xxx"}；请求模板里写 {api_key} 即可引用'
          }
        >
          <Input.TextArea data-testid="datasource-session-secrets" rows={2} />
        </Form.Item>
      </Form>
    </Modal>
  )
}

/** 推荐提示词弹窗：8 组典型场景默认收起（手风琴，一次只展开一组详情），
 *  点「使用」把 prompt 填入用户提示词（ADR 0019 P2）。
 *  详情（适用场景 / 建议字段 / 建议幂等键）随展开挂载，避免 8 组铺开把弹窗撑高。 */
function LlmPresetModal({
  open,
  onClose,
  onUse,
}: {
  open: boolean
  onClose: () => void
  onUse: (preset: LlmPromptPreset) => void
}) {
  return (
    <Modal
      title="推荐提示词"
      open={open}
      width={760}
      onCancel={onClose}
      destroyOnHidden
      footer={<Button onClick={onClose}>关闭</Button>}
      styles={{ body: { maxHeight: 'min(60vh, 480px)', overflowY: 'auto' } }}
    >
      <Space direction="vertical" size={12} style={{ width: '100%' }}>
        <Text type="secondary" style={{ fontSize: 12 }}>
          选一个典型场景一键填入用户提示词，再按需修改；点击场景名可展开适用场景与建议字段 / 幂等键。
          提示词里的 {'{{ }}'} 是 JSON 花括号的模板转义，运行时会还原为 {'{ }'}。
        </Text>
        <Collapse
          accordion
          size="small"
          destroyOnHidden
          items={LLM_PROMPT_PRESETS.map(preset => ({
            key: preset.id,
            label: (
              <Text strong data-testid={`datasource-llm-preset-${preset.id}`}>
                {preset.name}
              </Text>
            ),
            extra: (
              <Button
                size="small"
                type="primary"
                data-testid={`llm-preset-use-${preset.id}`}
                onClick={event => {
                  // 按钮在折叠头内部，阻止冒泡避免顺带展开 / 收起
                  event.stopPropagation()
                  onUse(preset)
                }}
              >
                使用
              </Button>
            ),
            children: (
              <Space direction="vertical" size={4} style={{ width: '100%' }}>
                <Paragraph type="secondary" style={{ margin: 0, fontSize: 12 }}>
                  {preset.description}
                </Paragraph>
                <Text style={{ fontSize: 12 }}>建议字段：{preset.target_fields.join(', ')}</Text>
                <Text style={{ fontSize: 12 }}>建议幂等键：{preset.match_keys.join(', ')}</Text>
              </Space>
            ),
          }))}
        />
      </Space>
    </Modal>
  )
}

