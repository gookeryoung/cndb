/** 采集策略编辑抽屉：四段式规则 + 自然语言草案 + 预览（ADR 0085 §10）
 *
 * - 草案只回表单，**不自动保存 / 不自动启用**（模型是规则翻译器，不是决策者）
 * - 保存前先跑 `rules/validate`；实质变更由后端 `rule_version +1` 并回 draft
 * - 预览只对已保存策略开放（预览走指定策略的抓取声明，草稿没有 id）
 */

import { useEffect, useMemo, useState } from 'react'
import {
  Alert, App as AntApp, Button, Divider, Drawer, Form, Input, InputNumber, Radio, Select, Space, Tag, Typography,
} from 'antd'
import { ExperimentOutlined, ThunderboltOutlined } from '@ant-design/icons'
import { useMutation, useQueryClient } from '@tanstack/react-query'

import { acquisitionApi } from '@/api/acquisition'
import type {
  AcquisitionChannelOption, AcquisitionPreview, AcquisitionStrategy, AcquisitionStrategyPayload,
} from '@/api/acquisition'

const { Text } = Typography

export interface EditorTableOption {
  id: number
  name: string
}

export interface EditorFolderOption {
  id: number
  title: string
}

interface Props {
  open: boolean
  wid: string
  strategy: AcquisitionStrategy | null
  channels: AcquisitionChannelOption[]
  tables: EditorTableOption[]
  folders: EditorFolderOption[]
  onClose: () => void
  onSaved: () => void
}

interface FormValues {
  name: string
  channels: string[]
  query: string
  maxPerChannel: number
  mustHave: string[]
  optional: string[]
  exclude: string[]
  targetKind: 'table' | 'document'
  tableId?: number
  matchKeys: string[]
  folderId?: number | null
  maxRounds: number
  review: 'auto' | 'llm' | 'manual'
  maxRequests: number
  scheduleMode: 'manual' | 'daily' | 'interval'
  scheduleAt?: string
  scheduleSeconds?: number
}

const REVIEW_OPTIONS = [
  { value: 'llm', label: '大模型判断后自动继续（默认）' },
  { value: 'auto', label: '纯确定性，不走模型' },
  { value: 'manual', label: '每轮停下等我确认' },
]

function toForm(strategy: AcquisitionStrategy | null): FormValues {
  const scope = strategy?.scope ?? { channels: [] }
  const filter = strategy?.filter_rule ?? {}
  const iteration = strategy?.iteration ?? {}
  const schedule = (strategy?.schedule ?? {}) as Record<string, unknown>
  const tableTarget = strategy?.targets?.find(t => t.kind === 'table')
  const docTarget = strategy?.targets?.find(t => t.kind === 'document')
  const mode = String(schedule.mode || 'manual')
  return {
    name: strategy?.name ?? '',
    channels: Array.isArray(scope.channels) ? scope.channels : [],
    query: String(scope.query ?? ''),
    maxPerChannel: Number(scope.max_results_per_channel ?? 50),
    mustHave: filter.must_have_keywords ?? [],
    optional: filter.optional_keywords ?? [],
    exclude: filter.exclude_keywords ?? [],
    targetKind: docTarget && !tableTarget ? 'document' : 'table',
    tableId: tableTarget?.table_id,
    matchKeys: tableTarget?.match_keys ?? [],
    folderId: docTarget?.parent_id ?? null,
    maxRounds: Number(iteration.max_rounds ?? 1),
    review: ((iteration.expand?.review as FormValues['review']) ?? 'auto'),
    maxRequests: Number(iteration.budget?.max_requests ?? 100),
    scheduleMode: mode === 'daily' || mode === 'interval' ? mode : 'manual',
    scheduleAt: String(schedule.at || '08:00'),
    scheduleSeconds: Number(schedule.seconds || 3600),
  }
}

function toPayload(values: FormValues): AcquisitionStrategyPayload {
  const target = values.targetKind === 'table'
    ? { kind: 'table' as const, table_id: values.tableId ?? 0, match_keys: values.matchKeys }
    : { kind: 'document' as const, parent_id: values.folderId ?? null }
  const schedule: Record<string, unknown> = values.scheduleMode === 'manual'
    ? { mode: 'manual' }
    : values.scheduleMode === 'daily'
      ? { mode: 'daily', at: values.scheduleAt || '08:00' }
      : { mode: 'interval', seconds: values.scheduleSeconds || 3600 }
  return {
    name: values.name.trim(),
    scope: {
      channels: values.channels,
      query: values.query.trim(),
      max_results_per_channel: values.maxPerChannel,
    },
    filter_rule: {
      must_have_keywords: values.mustHave,
      optional_keywords: values.optional,
      exclude_keywords: values.exclude,
    },
    targets: [target],
    iteration: {
      max_rounds: values.maxRounds,
      expand: { review: values.review },
      budget: { max_requests: values.maxRequests },
    },
    schedule,
  }
}

export default function StrategyEditor({ open, wid, strategy, channels, tables, folders, onClose, onSaved }: Props) {
  const [form] = Form.useForm<FormValues>()
  const { message } = AntApp.useApp()
  const queryClient = useQueryClient()
  const [description, setDescription] = useState('')
  const [draftNote, setDraftNote] = useState<{ text: string; tone: 'info' | 'warning' } | null>(null)
  const [preview, setPreview] = useState<AcquisitionPreview | null>(null)

  useEffect(() => {
    if (open) {
      form.setFieldsValue(toForm(strategy))
      setDescription('')
      setDraftNote(null)
      setPreview(null)
    }
  }, [open, strategy, form])

  const channelOptions = useMemo(
    () => channels.map(item => ({ value: item.value, label: `${item.label}${item.hint ? ` · ${item.hint}` : ''}` })),
    [channels],
  )

  const draftMutation = useMutation({
    mutationFn: async () => {
      const targetKind = form.getFieldValue('targetKind') as FormValues['targetKind']
      const tableId = form.getFieldValue('tableId') as number | undefined
      const folderId = form.getFieldValue('folderId') as number | null | undefined
      return acquisitionApi.ruleDraft(wid, {
        description,
        ...(targetKind === 'table' && tableId ? { table_id: tableId } : {}),
        ...(targetKind === 'document' && folderId ? { parent_id: folderId } : {}),
      })
    },
    onSuccess: (data) => {
      const draft = data.draft ?? {}
      const next: Partial<FormValues> = {}
      if (draft.scope?.channels?.length) next.channels = draft.scope.channels
      if (draft.scope?.query) next.query = draft.scope.query
      if (draft.scope?.max_results_per_channel) next.maxPerChannel = draft.scope.max_results_per_channel
      if (draft.filter_rule?.must_have_keywords?.length) next.mustHave = draft.filter_rule.must_have_keywords
      if (draft.filter_rule?.optional_keywords?.length) next.optional = draft.filter_rule.optional_keywords
      if (draft.filter_rule?.exclude_keywords?.length) next.exclude = draft.filter_rule.exclude_keywords
      if (draft.iteration?.max_rounds) next.maxRounds = draft.iteration.max_rounds
      if (draft.iteration?.expand?.review) next.review = draft.iteration.expand.review
      if (draft.iteration?.budget?.max_requests) next.maxRequests = draft.iteration.budget.max_requests
      const tableTarget = draft.targets?.find(t => t.kind === 'table')
      const docTarget = draft.targets?.find(t => t.kind === 'document')
      if (tableTarget?.table_id) {
        next.targetKind = 'table'
        next.tableId = tableTarget.table_id
        next.matchKeys = tableTarget.match_keys ?? []
      } else if (docTarget) {
        next.targetKind = 'document'
        next.folderId = docTarget.parent_id ?? null
      }
      form.setFieldsValue(next)
      setDraftNote({
        tone: data.degraded ? 'warning' : 'info',
        text: data.degraded
          ? `未使用大模型（${data.degraded}），表单未变；请手填或先到「个人设置 → 大模型」配置连接。`
          : `草案来自 ${data.model || '大模型'}，请逐项确认后再保存${draft.notes ? `：${draft.notes}` : ''}`,
      })
    },
    onError: (error: Error) => setDraftNote({ tone: 'warning', text: `草案生成失败：${error.message}` }),
  })

  const previewMutation = useMutation({
    mutationFn: async () => {
      if (!strategy) throw new Error('请先保存策略再预览')
      return acquisitionApi.preview(wid, strategy.id, form.getFieldValue('query'))
    },
    onSuccess: setPreview,
    onError: (error: Error) => message.error(error.message),
  })

  const saveMutation = useMutation({
    mutationFn: async (values: FormValues) => {
      const payload = toPayload(values)
      await acquisitionApi.validateRules(wid, {
        scope: payload.scope,
        filter_rule: payload.filter_rule,
        targets: payload.targets,
        iteration: payload.iteration,
      })
      return strategy
        ? acquisitionApi.updateStrategy(wid, strategy.id, payload)
        : acquisitionApi.createStrategy(wid, payload)
    },
    onSuccess: () => {
      message.success(strategy ? '已保存（实质变更会重置为未启用）' : '已创建，可先预览再启用')
      queryClient.invalidateQueries({ queryKey: ['acquisition', wid] })
      onSaved()
    },
    onError: (error: Error) => message.error(error.message),
  })

  return (
    <Drawer
      open={open}
      size={720}
      title={strategy ? `编辑策略 · ${strategy.name}` : '新建采集策略'}
      onClose={onClose}
      destroyOnHidden
      extra={(
        <Space>
          <Button onClick={onClose}>取消</Button>
          <Button type="primary" loading={saveMutation.isPending} onClick={() => form.submit()}>
            保存
          </Button>
        </Space>
      )}
    >
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 12 }}
        message="规则驱动的自动获取"
        description="一条规则 = 渠道 + 检索式 + 筛选 + 落点 + 迭代。启用前建议先跑「预览」，确认抓到的确实是想要的。"
      />

      <Space.Compact style={{ width: '100%', marginBottom: 8 }}>
        <Input.TextArea
          value={description}
          onChange={event => setDescription(event.target.value)}
          placeholder="用一句话描述需求，例如：每天早上抓固态电池相关的政策与论文，只要近 7 天，写进「政策库」表"
          autoSize={{ minRows: 2, maxRows: 4 }}
        />
        <Button
          icon={<ExperimentOutlined />}
          loading={draftMutation.isPending}
          disabled={description.trim().length < 2}
          onClick={() => draftMutation.mutate()}
          style={{ height: 'auto' }}
        >
          生成草案
        </Button>
      </Space.Compact>
      {draftNote && (
        <Alert
          style={{ marginBottom: 12 }}
          type={draftNote.tone}
          showIcon
          closable
          message={draftNote.text}
          onClose={() => setDraftNote(null)}
        />
      )}

      <Form form={form} layout="vertical" onFinish={values => saveMutation.mutate(values)} initialValues={toForm(strategy)}>
        <Form.Item name="name" label="策略名称" rules={[{ required: true, message: '请填写名称' }]}>
          <Input maxLength={128} placeholder="如：固态电池周报" />
        </Form.Item>

        <Divider plain>① 范围</Divider>
        <Form.Item name="channels" label="渠道" rules={[{ required: true, message: '至少选择一个渠道' }]}>
          <Select
            mode="multiple"
            options={channelOptions}
            placeholder="选择同步任务 / RSS / 学术接口"
            optionFilterProp="label"
            maxTagCount="responsive"
          />
        </Form.Item>
        <Form.Item
          name="query"
          label="检索式"
          rules={[{ required: true, message: '请填写检索式' }]}
          extra="支持 {today} 占位符；多轮迭代会在其后追加扩展词"
        >
          <Input maxLength={500} placeholder="如：固态电池 电解质" />
        </Form.Item>
        <Form.Item name="maxPerChannel" label="每渠道每轮上限">
          <InputNumber min={10} max={200} style={{ width: 160 }} />
        </Form.Item>

        <Divider plain>② 筛选</Divider>
        <Form.Item name="mustHave" label="必须包含（全部命中）">
          <Select mode="tags" placeholder="回车添加关键词" />
        </Form.Item>
        <Form.Item name="optional" label="可选包含（命中任一）">
          <Select mode="tags" placeholder="回车添加关键词" />
        </Form.Item>
        <Form.Item name="exclude" label="必须排除">
          <Select mode="tags" placeholder="回车添加关键词" />
        </Form.Item>

        <Divider plain>③ 落点</Divider>
        <Form.Item name="targetKind" label="写入位置">
          <Radio.Group
            options={[
              { value: 'table', label: '数据表' },
              { value: 'document', label: '文档' },
            ]}
          />
        </Form.Item>
        <Form.Item noStyle shouldUpdate={(prev, next) => prev.targetKind !== next.targetKind}>
          {({ getFieldValue }) => (getFieldValue('targetKind') === 'table' ? (
            <>
              <Form.Item name="tableId" label="目标表" rules={[{ required: true, message: '请选择目标表' }]}>
                <Select options={tables.map(t => ({ value: t.id, label: t.name }))} showSearch optionFilterProp="label" />
              </Form.Item>
              <Form.Item name="matchKeys" label="去重键（同键视为同一行）">
                <Select mode="tags" open={false} placeholder="如：city、day" />
              </Form.Item>
            </>
          ) : (
            <Form.Item name="folderId" label="文档文件夹" extra="留空即写入文档根目录">
              <Select
                allowClear
                options={folders.map(f => ({ value: f.id, label: f.title }))}
                showSearch
                optionFilterProp="label"
                placeholder="选择文件夹"
              />
            </Form.Item>
          ))}
        </Form.Item>

        <Divider plain>④ 迭代与预算</Divider>
        <Form.Item name="maxRounds" label="最大轮数">
          <InputNumber min={1} max={5} style={{ width: 160 }} />
        </Form.Item>
        <Form.Item name="review" label="扩展词复核">
          <Select options={REVIEW_OPTIONS} />
        </Form.Item>
        <Form.Item name="maxRequests" label="单次运行请求上限">
          <InputNumber min={1} max={1000} style={{ width: 160 }} />
        </Form.Item>

        <Divider plain>调度</Divider>
        <Space size="middle" wrap>
          <Form.Item name="scheduleMode" label="触发方式" style={{ marginBottom: 8 }}>
            <Select
              style={{ width: 160 }}
              options={[
                { value: 'manual', label: '仅手动' },
                { value: 'daily', label: '每天定时' },
                { value: 'interval', label: '固定间隔' },
              ]}
            />
          </Form.Item>
          <Form.Item noStyle shouldUpdate={(prev, next) => prev.scheduleMode !== next.scheduleMode}>
            {({ getFieldValue }) => {
              const mode = getFieldValue('scheduleMode')
              if (mode === 'daily') {
                return (
                  <Form.Item name="scheduleAt" label="每天时刻（HH:MM）" style={{ marginBottom: 8 }}>
                    <Input style={{ width: 120 }} placeholder="08:00" />
                  </Form.Item>
                )
              }
              if (mode === 'interval') {
                return (
                  <Form.Item name="scheduleSeconds" label="间隔（秒）" style={{ marginBottom: 8 }}>
                    <InputNumber min={60} max={86400} style={{ width: 140 }} />
                  </Form.Item>
                )
              }
              return <Text type="secondary">手动运行：只在你点「运行」或 CLI 触发时执行</Text>
            }}
          </Form.Item>
        </Space>
      </Form>

      <Divider plain>预览</Divider>
      <Space orientation="vertical" style={{ width: '100%' }}>
        <Space>
          <Button
            icon={<ThunderboltOutlined />}
            loading={previewMutation.isPending}
            disabled={!strategy}
            onClick={() => previewMutation.mutate()}
          >
            抓一次看看（不写入）
          </Button>
          {!strategy && <Text type="secondary">保存后可用预览</Text>}
        </Space>
        {preview && (
          <Alert
            type={preview.channel_errors.length ? 'warning' : 'success'}
            showIcon
            message={`抓取 ${preview.collected} 条 → 去重 ${preview.after_dedup} → 命中 ${preview.after_filter}`}
            description={(
              <Space orientation="vertical" size={4} style={{ width: '100%' }}>
                {Object.entries(preview.by_channel).map(([channel, count]) => (
                  <Text key={channel} type="secondary">{channel}：{count} 条</Text>
                ))}
                {preview.samples.map(sample => (
                  <Text key={`${sample.title}-${sample.url}`} ellipsis>
                    {sample.match_score} 分 · {sample.title || sample.url}
                  </Text>
                ))}
                {preview.channel_errors.map(error => (
                  <Text key={error.channel} type="danger">{error.channel}：{error.error}</Text>
                ))}
              </Space>
            )}
          />
        )}
      </Space>

      <div style={{ marginTop: 12 }}>
        {strategy && (
          <Space wrap>
            <Tag>规则版本 v{strategy.rule_version}</Tag>
            <Tag color={strategy.enabled ? 'green' : 'default'}>{strategy.enabled ? '已启用' : '未启用'}</Tag>
          </Space>
        )}
      </div>
    </Drawer>
  )
}
