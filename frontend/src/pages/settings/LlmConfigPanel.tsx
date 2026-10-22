/** 个人设置「大模型」页签 — 个人级连接配置 + 本人调用记录（ADR 0019 / ADR 0020 P0/P3）.
 *
 * 后端接口（当前登录用户，不依赖工作区）：
 * - `GET  /api/v1/llm/config`：读取配置（不回显 api_key，附带内置默认系统提示词）
 * - `PUT  /api/v1/llm/config`：保存配置（api_key 非空才更新、clear_api_key 清除）
 * - `POST /api/v1/llm/config/test`：连通测试（可用未保存的地址 / 模型 / Key，不落库）
 * - `GET  /api/v1/llm/runs`：本人 AI 调用记录（最近 20 条；只含元数据与失败摘要）
 *
 * 交互要点：
 * - 面板内独立「保存」按钮（个人设置 Modal 的 footer 仍只有关闭）；
 * - API Key 密码框只写不回显，已保存时显示「清除」入口；
 * - 测试连接直接用当前输入（含未保存 Key），无需先保存；
 * - 系统提示词留空使用后端内置默认，并把内置默认全文展示在面板内；
 * - 调用记录只读：动作 / 状态 / 模型 / token / 耗时 / 时间；失败摘要截断展示，
 *   完整 error 放 Tooltip（不把模型错误全文铺在设置页）。
 */

import { useEffect, useState } from 'react'
import {
  Alert, App, Button, Divider, Empty, Form, Input, Space, Table, Tag, Tooltip, Typography,
} from 'antd'
import { ApiOutlined, HistoryOutlined, ReloadOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  llmApi,
  type LlmConfigPayload,
  type LlmConnectionTestResult,
  type LlmRun,
} from '@/api'
import { SPACE, TEXT } from '@/theme/tokens'

const { Text, Paragraph } = Typography

/** 与后端 `plugins/llm/services/connection.py` 的内置默认值对齐 */
const DEFAULT_BASE_URL = 'https://api.deepseek.com'
const DEFAULT_MODEL = 'deepseek-chat'

/** 调用记录查询条数（ADR 0020 P3：个人设置只展示最近 20 条） */
const RUNS_LIMIT = 20

/** 已知动作名 → 中文展示名（未知动作回退原始动作名，避免后端新增动作时前端空白） */
const ACTION_LABELS: Record<string, string> = {
  'datasource.llm_prompt': '大模型提示词',
  'document.polish': 'AI 润色',
  'document.summarize': 'AI 摘要',
  'document.suggest_tags': 'AI 标签建议',
  'table.fill_field': 'AI 字段填充',
  'import.mapping_suggestion': 'AI 列映射',
  'analytics.suggest_template': 'AI 生成分析',
  'analytics.explain': 'AI 结论解读',
  'search.rewrite_query': 'AI 搜索改写',
}

/** 动作名展示文案 */
function actionLabel(action: string): string {
  return ACTION_LABELS[action] ?? action
}

/** token 文案：上游未返回时各字段为 0，展示「—」避免误读成真实用量 */
function tokenText(run: LlmRun): string {
  const total = run.total_tokens || run.prompt_tokens + run.completion_tokens
  return total > 0 ? `${total} tokens` : '—'
}

/** 失败摘要截断（完整 error 只放 Tooltip，不铺在表里） */
function truncateError(error: string, max = 24): string {
  const text = (error ?? '').trim()
  return text.length > max ? `${text.slice(0, max)}…` : text
}

interface LlmConfigFormValues {
  base_url: string
  model: string
  api_key: string
  system_prompt: string
}

interface ApiError {
  response?: { data?: { detail?: string } }
}

/** 抽取后端 400 的 detail 文案（axios 拦截器也会写进 err.message） */
function errorDetail(error: unknown): string | undefined {
  const detail = (error as ApiError)?.response?.data?.detail
  return typeof detail === 'string' && detail ? detail : undefined
}

export default function LlmConfigPanel() {
  const { message } = App.useApp()
  const queryClient = useQueryClient()
  const [form] = Form.useForm<LlmConfigFormValues>()
  const [clearKey, setClearKey] = useState(false)
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<LlmConnectionTestResult | null>(null)

  const configQuery = useQuery({
    queryKey: ['llm-config'],
    queryFn: llmApi.get,
    staleTime: 300_000,
  })
  const config = configQuery.data ?? null

  // 调用记录（最近 20 条）：与连接配置分区独立，失败只降级本区、不影响配置编辑
  const runsQuery = useQuery({
    queryKey: ['llm-runs', RUNS_LIMIT],
    queryFn: () => llmApi.listRuns({ limit: RUNS_LIMIT }),
    staleTime: 30_000,
    retry: false,
  })
  const runs = runsQuery.data?.items ?? []
  const runsError = runsQuery.isError
    ? errorDetail(runsQuery.error)
      || (runsQuery.error instanceof Error && runsQuery.error.message)
      || '调用记录加载失败，请稍后重试'
    : null

  // 读取到配置后回填表单；api_key 永远从空开始，只写不回显
  useEffect(() => {
    if (!config) return
    form.setFieldsValue({
      base_url: config.base_url || DEFAULT_BASE_URL,
      model: config.model || DEFAULT_MODEL,
      api_key: '',
      system_prompt: config.system_prompt ?? '',
    })
    setClearKey(false)
  }, [config, form])

  const saveMutation = useMutation({
    mutationFn: (payload: LlmConfigPayload) => llmApi.update(payload),
    onSuccess: saved => {
      queryClient.setQueryData(['llm-config'], saved)
      form.setFieldValue('api_key', '')
      setClearKey(false)
      setTestResult(null)
      message.success('大模型配置已保存')
    },
    onError: (error: unknown) => {
      message.error(errorDetail(error) || (error instanceof Error && error.message) || '保存失败，请稍后重试')
    },
  })

  const submit = async () => {
    let values: LlmConfigFormValues
    try {
      values = await form.validateFields()
    } catch {
      return
    }
    const payload: LlmConfigPayload = {
      base_url: String(values.base_url ?? '').trim(),
      model: String(values.model ?? '').trim(),
      system_prompt: String(values.system_prompt ?? ''),
    }
    const apiKey = String(values.api_key ?? '').trim()
    if (apiKey) payload.api_key = apiKey
    if (clearKey) payload.clear_api_key = true
    saveMutation.mutate(payload)
  }

  const testConnection = async () => {
    let values: Pick<LlmConfigFormValues, 'base_url' | 'model'>
    try {
      values = await form.validateFields(['base_url', 'model'])
    } catch {
      return
    }
    setTesting(true)
    setTestResult(null)
    try {
      const apiKey = String(form.getFieldValue('api_key') ?? '').trim()
      const systemPrompt = String(form.getFieldValue('system_prompt') ?? '').trim()
      setTestResult(
        await llmApi.testConnection({
          base_url: String(values.base_url ?? '').trim(),
          model: String(values.model ?? '').trim(),
          // 未保存的 Key / 系统提示词直接随请求带上，后端只用于本次测试、不落库
          ...(apiKey ? { api_key: apiKey } : {}),
          ...(systemPrompt ? { system_prompt: systemPrompt } : {}),
        }),
      )
    } catch (error) {
      setTestResult({
        ok: false,
        latency_ms: 0,
        model: '',
        message: errorDetail(error) || (error instanceof Error && error.message) || '连通测试请求失败，请检查网络',
      })
    } finally {
      setTesting(false)
    }
  }

  const configuredTag = config?.has_api_key
    ? <Tag color="green" data-testid="llm-config-status">已配置</Tag>
    : <Tag data-testid="llm-config-status">未配置 API Key</Tag>

  /** 调用记录列：动作 / 状态 / 模型 / token / 耗时 / 时间（不再展示提示词与输出） */
  const runColumns = [
    {
      key: 'action',
      title: '动作',
      dataIndex: 'action',
      width: 160,
      render: (action: string, run: LlmRun) => (
        <Tooltip title={`${action}（留痕 #${run.id}）`}>
          <Text data-testid={`llm-run-action-${run.id}`}>{actionLabel(action)}</Text>
        </Tooltip>
      ),
    },
    {
      key: 'status',
      title: '状态',
      dataIndex: 'status',
      width: 120,
      render: (status: LlmRun['status'], run: LlmRun) => {
        const ok = status === 'success'
        const error = (run.error ?? '').trim()
        return (
          <Space direction="vertical" size={0}>
            <Tag
              color={ok ? 'green' : 'red'}
              data-testid={`llm-run-status-${run.id}`}
              style={{ marginInlineEnd: 0 }}
            >
              {ok ? '成功' : '失败'}
            </Tag>
            {!ok && error && (
              <Tooltip title={<span style={{ whiteSpace: 'pre-wrap' }}>{error}</span>}>
                <Text
                  type="secondary"
                  data-testid={`llm-run-error-${run.id}`}
                  style={{ fontSize: TEXT['2xs'], maxWidth: 110 }}
                  ellipsis
                >
                  {truncateError(error)}
                </Text>
              </Tooltip>
            )}
          </Space>
        )
      },
    },
    {
      key: 'model',
      title: '模型',
      dataIndex: 'model',
      width: 150,
      ellipsis: true,
      render: (model: string) => model || '—',
    },
    {
      key: 'tokens',
      title: 'Token',
      width: 120,
      render: (_value: unknown, run: LlmRun) => (
        <Tooltip title={`prompt ${run.prompt_tokens} / completion ${run.completion_tokens}`}>
          <Text style={{ fontSize: TEXT.xs }}>{tokenText(run)}</Text>
        </Tooltip>
      ),
    },
    {
      key: 'latency',
      title: '耗时',
      dataIndex: 'latency_ms',
      width: 100,
      render: (latency: number) => (typeof latency === 'number' ? `${latency} ms` : '—'),
    },
    {
      key: 'created_at',
      title: '时间',
      dataIndex: 'created_at',
      width: 150,
      render: (createdAt: string) => (
        <Text type="secondary" style={{ fontSize: TEXT.xs }}>
          {createdAt ? dayjs(createdAt).format('YYYY-MM-DD HH:mm') : '—'}
        </Text>
      ),
    },
  ]

  return (
    <div style={{ padding: '12px 0' }} data-testid="llm-config-panel">
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message={<Space size={8}>个人级配置，所有「大模型提示词」任务共用{configuredTag}</Space>}
        description="API Key 只加密保存在你的账号下、只写不回显；其他成员不会读取你的配置。保存 / 运行提示词任务时按当前登录用户的配置解析。"
      />
      <Form
        form={form}
        layout="vertical"
        size="small"
        initialValues={{ base_url: DEFAULT_BASE_URL, model: DEFAULT_MODEL, api_key: '', system_prompt: '' }}
      >
        <Form.Item
          name="base_url"
          label="API 地址（base_url）"
          rules={[{ required: true, message: '请输入 API 地址' }]}
          extra="OpenAI 兼容；只填 base_url 时自动补全 /chat/completions"
        >
          <Input data-testid="llm-config-base-url" placeholder={DEFAULT_BASE_URL} />
        </Form.Item>
        <Form.Item name="model" label="模型" rules={[{ required: true, message: '请输入模型名称' }]}>
          <Input data-testid="llm-config-model" placeholder={DEFAULT_MODEL} />
        </Form.Item>
        <Form.Item
          name="api_key"
          label="API Key"
          extra={
            config?.has_api_key
              ? '已配置 API Key：留空保持不变，填写则整体替换；填写后可直接点「测试连接」验证'
              : '填写后可直接点「测试连接」验证；保存后加密存储，读接口只回显是否已配置'
          }
        >
          <Input.Password
            data-testid="llm-config-api-key"
            autoComplete="new-password"
            placeholder={config?.has_api_key ? '已配置，留空保持不变' : 'sk-...'}
          />
        </Form.Item>
        {config?.has_api_key && (
          <Form.Item style={{ marginBottom: 12 }}>
            <Space size={8}>
              <Button
                size="small"
                danger={!clearKey}
                type={clearKey ? 'primary' : 'default'}
                data-testid="llm-config-clear-key"
                onClick={() => setClearKey(value => !value)}
              >
                {clearKey ? '取消清除 API Key' : '清除已保存的 API Key'}
              </Button>
              <Text type="secondary" style={{ fontSize: 12 }}>
                保存后清除
              </Text>
            </Space>
          </Form.Item>
        )}
        <Form.Item
          name="system_prompt"
          label="系统提示词（可选）"
          extra="留空使用内置默认；填写后覆盖你的内置默认系统提示词"
        >
          <Input.TextArea data-testid="llm-config-system" rows={3} placeholder="留空使用内置默认" />
        </Form.Item>
        <div
          data-testid="llm-config-default-system"
          style={{ padding: 8, background: 'rgba(0,0,0,0.03)', borderRadius: 6, marginBottom: 16 }}
        >
          <Text type="secondary" style={{ fontSize: 12 }}>
            内置默认系统提示词（系统提示词留空时使用）
          </Text>
          <Paragraph style={{ marginBottom: 0, marginTop: 4, whiteSpace: 'pre-wrap', fontSize: 12 }}>
            {config?.default_system_prompt || '（内置默认系统提示词加载中…）'}
          </Paragraph>
        </div>
        <Space size={8} wrap>
          <Button
            type="primary"
            loading={saveMutation.isPending}
            data-testid="llm-config-save"
            onClick={() => void submit()}
          >
            保存
          </Button>
          <Button
            icon={<ApiOutlined />}
            loading={testing}
            data-testid="llm-config-test"
            onClick={() => void testConnection()}
          >
            测试连接
          </Button>
          <Text type="secondary" style={{ fontSize: 12 }}>
            测试连接会发一次真实模型请求（可能产生费用）；可直接用当前填写的 API Key 测试，无需先保存
          </Text>
        </Space>
        {testResult && (
          <Alert
            data-testid="llm-config-test-result"
            type={testResult.ok ? 'success' : 'error'}
            showIcon
            style={{ marginTop: 12 }}
            message={
              testResult.ok
                ? `连通成功 · ${testResult.model || '模型'} · ${testResult.latency_ms} ms`
                : '连通失败'
            }
            description={testResult.ok ? undefined : testResult.message}
          />
        )}
      </Form>

      {/* ── 调用记录：本人最近 20 条（只读，不展示提示词 / 输出全文） ── */}
      <Divider style={{ margin: `${SPACE.lg}px 0 ${SPACE.md}px` }} />
      <div data-testid="llm-runs">
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            flexWrap: 'wrap',
            gap: SPACE.md,
            marginBottom: SPACE.md,
          }}
        >
          <Space size={SPACE.md} wrap>
            <HistoryOutlined />
            <Text strong>调用记录</Text>
            <Text type="secondary" style={{ fontSize: TEXT.xs }}>
              最近 {RUNS_LIMIT} 条（仅本人）
            </Text>
          </Space>
          <Button
            size="small"
            icon={<ReloadOutlined />}
            data-testid="llm-runs-refresh"
            loading={runsQuery.isFetching}
            onClick={() => void runsQuery.refetch()}
          >
            刷新
          </Button>
        </div>

        {runsError ? (
          <div data-testid="llm-runs-error">
            <Alert
              type="error"
              showIcon
              message="调用记录加载失败"
              description={runsError}
              action={(
                <Button
                  size="small"
                  data-testid="llm-runs-retry"
                  onClick={() => void runsQuery.refetch()}
                >
                  重试
                </Button>
              )}
            />
          </div>
        ) : (
          <Table<LlmRun>
            data-testid="llm-runs-table"
            size="small"
            rowKey="id"
            loading={runsQuery.isLoading}
            dataSource={runs}
            columns={runColumns}
            pagination={false}
            scroll={{ x: 'max-content' }}
            locale={{
              emptyText: (
                <Empty
                  data-testid="llm-runs-empty"
                  image={Empty.PRESENTED_IMAGE_SIMPLE}
                  description="还没有大模型调用记录；使用 AI 功能后会在这里留下用量与状态。"
                />
              ),
            }}
          />
        )}

        <Text
          type="secondary"
          style={{ display: 'block', marginTop: SPACE.md, fontSize: TEXT['2xs'] }}
        >
          记录只保存动作、模型、用量、耗时与失败摘要，不保存提示词与模型输出全文；失败摘要悬停可看完整错误，动作列悬停可看留痕 id。
        </Text>
      </div>
    </div>
  )
}
