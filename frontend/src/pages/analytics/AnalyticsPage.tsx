/** 数据分析页 —— 独立于文档的工作区级模块.
 *
 * 定位：数据源为工作区内任意数据表，提供「公式 + 分组汇总 + 图表 + 描述统计」一体化分析。
 *
 * 页面能力：
 * - 模板：加载 / 保存 / 另存为副本 / 重命名 / 删除；`?template=<id>` 深链刷新保持；
 *   有未保存修改时切换模板先确认
 * - 布局：顶部「数据源 + 智能推荐」左右并列，未选表时推荐收起为窄条（表名称、维度为空），
 *   选表后向右展开；下方按分析环节分三段带状布局，左配置右对应结果——
 *   计算模板 → 描述统计/派生数据、可视化 → 图表、分组汇总 → 分组汇总表
 * - 计算模板：多行公式编辑器（字段/函数快捷插入、示例片段、Ctrl/Cmd+Enter 运行、实时校验）
 * - 可视化：图表类型 + 维度聚合方式 + 维度/指标/系列
 * - 分组汇总：分组字段 + 指标（字段/公式 × 聚合）+ 排序 + Top N
 * - AI：一句话生成分析模板（填编辑态不落库）+ 结果 AI 解读（只读抽屉）
 *
 * 公式语法（后端受限引擎，非 eval）：`[字段名]` 引用字段、`+ - * / ( )`、后缀 `%`、
 * round/abs/sqrt/pow/ceil/floor、整列聚合 sum/avg/count/min/max。
 */

import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useParams, useSearchParams } from 'react-router-dom'
import {
  App as AntApp, Alert, Button, Empty, Input, Modal, Select, Space,
  Tag, Tooltip, Typography,
} from 'antd'
import {
  DeleteOutlined, SaveOutlined, BarChartOutlined, PlayCircleOutlined, CopyOutlined, EditOutlined,
  UnorderedListOutlined, DatabaseOutlined, GroupOutlined, FunctionOutlined,
} from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { tableApi, useLlmConfigured } from '@/api'
import type { Field } from '@/api'
import { analyticsApi } from '@/api/analytics'
import type {
  AnalyticsAiExplainPayload,
  AnalyticsAiSuggestTemplatePayload,
  AnalyticsAiTemplateSuggestion,
  AnalyticsChart, AnalyticsComputeResponse, AnalyticsFilter, AnalyticsFormula,
  AnalyticsRecommendationExample, AnalyticsSummary, AnalyticsTemplate, AnalyticsTemplateCreate,
  AnalyticsTemplateUpdate,
} from '@/api/analytics'
import { useLlmAction } from '@/hooks/useLlmAction'
import { useAuthStore } from '@/store/auth'
import {
  DEFAULT_ANALYTICS_BLOCKS, useAnalyticsBlocksStore, type AnalyticsBlockKey,
} from '@/store/analyticsBlocks'
import { AnalyticsAiPanel } from './AnalyticsAiPanel'
import { AnalyticsBox } from './AnalyticsBox'
import { FormulaPanel } from './FormulaPanel'
import { ChartPanel } from './ChartPanel'
import { SummaryPanel } from './SummaryPanel'
import { ChartResultBox, RowsResultBox, StatsResultBox, SummaryResultBox } from './AnalyticsResultView'
import { RecommendationPanel } from './RecommendationPanel'
import { AnalyticsManagerDrawer } from './AnalyticsManagerDrawer'
import { applySuggestionConfig, buildExplainPayload, suggestionName } from './analyticsAi'
import {
  DEFAULT_CHART,
  EMPTY_SUMMARY,
  applyExampleConfig,
  buildTemplateConfig,
  canRunAnalysis,
  chartConfigured,
  collectFormulaErrors,
  isDirty,
  mergeFormulas,
  newFormula,
  normalizeChart,
  normalizeFormulas,
  normalizeSummary,
  templateSnapshot,
  templateTableName,
} from './analyticsModel'

const { Text } = Typography

/** AI 解读抽屉只在点击「AI 解读」后才需要，lazy 挂载避免进入分析页首屏 chunk */
const AnalyticsAiExplainDrawer = lazy(() => import('./AnalyticsAiExplainDrawer'))

/** 未运行时的结果占位：与对应配置同排展示，提示运行后此处出现什么 */
function ResultPlaceholder({ text }: { text: string }) {
  return (
    <div className="cn-an-band-empty" data-testid="analytics-result-placeholder">
      <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={text} />
    </div>
  )
}

const DEFAULT_TEMPLATE_NAME = '未命名分析'
/** 数值型字段：用于公式示例 / 分组汇总默认指标候选 */
const NUMERIC_TYPES = new Set(['number', 'decimal', 'float', 'percentage'])

type SaveMode = 'create' | 'rename'
type SaveVariables = {
  mode: 'create' | 'update' | 'rename'
  payload: AnalyticsTemplateCreate | AnalyticsTemplateUpdate
}

export default function AnalyticsPage() {
  const { wid } = useParams<{ wid: string }>()
  const { message, modal } = AntApp.useApp()
  const queryClient = useQueryClient()
  const [searchParams, setSearchParams] = useSearchParams()
  /** 深链模板 id（URL ?template=<id>）：改写走 setSearchParams，读取提前到状态区供按钮禁用判定 */
  const templateParam = searchParams.get('template')
  // 未配置大模型时隐藏 AI 生成分析面板与 AI 解读按钮（需求 0069）
  const llmConfigured = useLlmConfigured()

  // ── 区块启用开关（可视化 / 分组汇总 / 计算模板；按用户 + 本机记忆，默认仅启用可视化） ──
  const authUserId = useAuthStore(s => s.user?.id)
  const blockUserId = authUserId != null ? String(authUserId) : 'anon'
  const blockByUser = useAnalyticsBlocksStore(s => s.byUser)
  const setBlocks = useAnalyticsBlocksStore(s => s.setBlocks)
  const blocks = blockByUser[blockUserId] ?? DEFAULT_ANALYTICS_BLOCKS
  const toggleBlock = (key: AnalyticsBlockKey, enabled: boolean) => setBlocks(blockUserId, { [key]: enabled })

  // ── 分析配置 ──
  const [tableId, setTableId] = useState<number | null>(null)
  const [formulas, setFormulas] = useState<AnalyticsFormula[]>([newFormula(0)])
  const [chart, setChart] = useState<AnalyticsChart>({ ...DEFAULT_CHART })
  const [summary, setSummary] = useState<AnalyticsSummary>({ ...EMPTY_SUMMARY, metrics: [] })
  const [result, setResult] = useState<AnalyticsComputeResponse | null>(null)
  // 分析范围：运行时参数（只影响本次扫描，不入模板），用于把时序分析限定在区间内
  const [scopeField, setScopeField] = useState<string | null>(null)
  const [scopeFrom, setScopeFrom] = useState('')
  const [scopeTo, setScopeTo] = useState('')
  /** 后端 validate 返回的公式错误（键 → 信息） */
  const [serverErrors, setServerErrors] = useState<Record<string, string>>({})

  // ── 模板状态 ──
  const [activeTemplateId, setActiveTemplateId] = useState<number | null>(null)
  const [templateName, setTemplateName] = useState('')
  const [templateDesc, setTemplateDesc] = useState('')
  /** 已保存快照：用于「未保存修改」判定 */
  const [snapshot, setSnapshot] = useState('')
  const [saveOpen, setSaveOpen] = useState(false)
  const [saveMode, setSaveMode] = useState<SaveMode>('create')
  const [formName, setFormName] = useState('')
  const [formDesc, setFormDesc] = useState('')
  const [tableMissing, setTableMissing] = useState(false)
  /** 分析列表 Drawer 开关 */
  const [managerOpen, setManagerOpen] = useState(false)
  /** 已处理的 ?template= 参数：模板列表刷新/保存过渡期间不重复载入 */
  const handledParamRef = useRef<string | null>(null)

  // ── 查询 ──
  const { data: tables = [] } = useQuery({
    queryKey: ['workspaces', wid, 'tables'],
    queryFn: () => tableApi.list(wid!),
    enabled: !!wid,
  })

  const { data: tableDetail } = useQuery({
    queryKey: ['table', wid, tableId],
    queryFn: () => tableApi.get(wid!, tableId!),
    enabled: !!wid && !!tableId,
  })

  const { data: templates = [], isLoading: templatesLoading } = useQuery({
    queryKey: ['analytics-templates', wid],
    queryFn: () => analyticsApi.listTemplates(wid!),
    enabled: !!wid,
  })

  /** 智能推荐：选表后请求；失败静默降级（不弹全局错误），不影响手动配置 */
  const {
    data: recommendations = null,
    isLoading: recommendLoading,
    isError: recommendError,
  } = useQuery({
    queryKey: ['analytics-recommendations', wid, tableId],
    queryFn: () => analyticsApi.recommend(wid!, tableId!),
    enabled: !!wid && !!tableId,
    retry: false,
    staleTime: 5 * 60_000,
  })

  const tableFields = useMemo<string[]>(() => (tableDetail?.fields ?? []).map(f => f.name), [tableDetail])
  const numericFields = useMemo<string[]>(
    () => (tableDetail?.fields ?? []).filter(f => NUMERIC_TYPES.has(f.field_type)).map(f => f.name),
    [tableDetail],
  )

  // ── 派生配置 ──
  const validFormulas = useMemo(
    () => formulas.filter(f => f.key.trim() && f.expr.trim()),
    [formulas],
  )
  const errors = useMemo(() => collectFormulaErrors(formulas, serverErrors), [formulas, serverErrors])
  const hasError = Object.keys(errors).length > 0
  const canRun = canRunAnalysis({
    tableId,
    validFormulaCount: validFormulas.length,
    chart,
    summary,
    hasError,
  })
  /** 无公式但图表 / 汇总可用时仍可运行；三者皆空才提示 */
  const noRunnableConfig = validFormulas.length === 0 && !chartConfigured(chart) && !summaryConfigured(summary)

  const currentSnapshot = useMemo(
    () => templateSnapshot({ name: templateName, description: templateDesc, tableId, formulas, chart, summary }),
    [templateName, templateDesc, tableId, formulas, chart, summary],
  )
  const dirty = activeTemplateId != null && isDirty(snapshot, currentSnapshot)

  /** 深链 ?template=<id> 仍在拉模板列表：此时另存为/重命名的默认名会落到「未命名分析」，先禁用 */
  const templatePending = templateParam != null && templatesLoading

  /** 图表可选值：表字段 + 公式键（公式键在结果行中作为列存在） */
  const chartOptions = useMemo(
    () => [
      ...validFormulas.map(f => ({ value: f.key.trim(), label: `${(f.label ?? '').trim() || f.key.trim()}（公式）` })),
      ...tableFields.map(name => ({ value: name, label: name })),
    ],
    [validFormulas, tableFields],
  )
  const groupOptions = useMemo(() => tableFields.map(name => ({ value: name, label: name })), [tableFields])

  /** ChartCard 需要 Field 结构：公式列合成 number 字段（供图表与预览格式化） */
  const syntheticFields = useMemo<Field[]>(
    () => [
      ...validFormulas.map((f, i) => ({
        id: -(i + 1),
        name: f.key.trim(),
        field_type: 'number' as Field['field_type'],
      })),
      ...(tableDetail?.fields ?? []),
    ],
    [validFormulas, tableDetail],
  )

  // ── 模板载入 / 快照同步 ──
  const applyTemplateConfig = useCallback((tpl: AnalyticsTemplate, opts?: { keepResult?: boolean }) => {
    const nextFormulas = normalizeFormulas(tpl.config?.formulas)
    const nextChart = normalizeChart(tpl.config?.chart)
    const nextSummary = normalizeSummary(tpl.config?.summary)
    const nextName = tpl.name
    const nextDesc = tpl.description ?? ''
    const nextTableId = tpl.table_id ?? null

    setActiveTemplateId(tpl.id)
    setTemplateName(nextName)
    setTemplateDesc(nextDesc)
    setTableId(nextTableId)
    setFormulas(nextFormulas)
    setChart(nextChart)
    setSummary(nextSummary)
    setServerErrors({})
    setTableMissing(nextTableId == null)
    setSnapshot(templateSnapshot({
      name: nextName,
      description: nextDesc,
      tableId: nextTableId,
      formulas: nextFormulas,
      chart: nextChart,
      summary: nextSummary,
    }))
    if (!opts?.keepResult) setResult(null)
  }, [])

  const clearActiveTemplate = useCallback(() => {
    setActiveTemplateId(null)
    setTemplateName('')
    setTemplateDesc('')
    setSnapshot('')
    setTableMissing(false)
    handledParamRef.current = null
    setSearchParams(prev => {
      const next = new URLSearchParams(prev)
      next.delete('template')
      return next
    }, { replace: true })
  }, [setSearchParams])

  /** 切换模板：有未保存修改先确认（避免用户误丢编辑成果） */
  const requestTemplateLoad = useCallback((tpl: AnalyticsTemplate, opts?: { onApplied?: () => void }) => {
    if (!dirty) {
      applyTemplateConfig(tpl)
      opts?.onApplied?.()
      return
    }
    modal.confirm({
      title: '放弃未保存的修改？',
      content: `模板「${templateName || '未命名分析'}」有未保存的修改，切换后将丢失。`,
      okText: '放弃并切换',
      cancelText: '继续编辑',
      onOk: () => {
        applyTemplateConfig(tpl)
        opts?.onApplied?.()
      },
    })
  }, [dirty, templateName, applyTemplateConfig, modal])

  /** 新建分析：真正清空当前配置与深链（有未保存修改先确认） */
  const startNewAnalysis = useCallback(() => {
    const reset = () => {
      setActiveTemplateId(null)
      setTemplateName('')
      setTemplateDesc('')
      setTableId(null)
      setFormulas([newFormula(0)])
      setChart({ ...DEFAULT_CHART })
      setSummary({ ...EMPTY_SUMMARY, metrics: [] })
      setResult(null)
      setServerErrors({})
      setTableMissing(false)
      setSnapshot('')
      // URL 更新走 startTransition，可能晚于本次渲染；先记录已处理的参数，
      // 避免过渡期内深链 effect 用旧 ?template= 把刚清空的模板再载入一次。
      handledParamRef.current = searchParams.get('template')
      setManagerOpen(false)
      setSearchParams(prev => {
        const next = new URLSearchParams(prev)
        next.delete('template')
        return next
      }, { replace: true })
    }
    if (!dirty) {
      reset()
      return
    }
    modal.confirm({
      title: '放弃未保存的修改？',
      content: `当前分析「${templateName || '未命名分析'}」有未保存的修改，新建后将丢失。`,
      okText: '放弃并新建',
      cancelText: '继续编辑',
      onOk: reset,
    })
  }, [dirty, templateName, modal, searchParams, setSearchParams])

  // ── 智能推荐：应用动作（不等待后端；接口失败仅降级面板，不阻塞页面）──
  /** 首个推荐维度：点击推荐指标时用它补充分组汇总维度 */
  const recommendedDimension = useMemo(
    () => recommendations?.fields.find(f => f.role === 'dimension')?.name ?? null,
    [recommendations],
  )

  const selectRecommendedDimension = useCallback((name: string) => {
    setChart(prev => ({ ...prev, x: name }))
  }, [])

  const selectRecommendedTime = useCallback((name: string) => {
    setChart(prev => ({ ...prev, type: 'line', x: name }))
  }, [])

  const selectRecommendedMetric = useCallback((name: string) => {
    setChart(prev => ({ ...prev, y: name }))
    if (recommendedDimension) {
      setSummary(prev => (prev.group_by ? prev : { ...prev, group_by: recommendedDimension }))
    }
  }, [recommendedDimension])

  const applyRecommendedChart = useCallback((next: AnalyticsChart) => {
    setChart(normalizeChart(next))
    message.success('已应用推荐图表')
  }, [message])

  const applyRecommendedSummary = useCallback((next: AnalyticsSummary) => {
    setSummary(normalizeSummary(next))
    message.success('已应用推荐分组汇总')
  }, [message])

  const applyRecommendedFormulas = useCallback((list: AnalyticsFormula[]) => {
    const next = mergeFormulas(formulas, list)
    if (next === formulas) {
      message.info('推荐公式均已存在，未追加')
      return
    }
    const currentKeys = new Set(formulas.filter(f => f.expr.trim()).map(f => f.key.trim()))
    const added = next.filter(f => !currentKeys.has(f.key.trim())).length
    setFormulas(next)
    setServerErrors({})
    message.success(`已追加 ${added} 条推荐公式`)
  }, [formulas, message])

  const applyRecommendedExample = useCallback((example: AnalyticsRecommendationExample) => {
    const config = applyExampleConfig(example)
    setFormulas(config.formulas)
    setChart(config.chart)
    setSummary(config.summary)
    setServerErrors({})
    message.success(`已应用典型示例「${example.name}」`)
  }, [message])

  // ── AI：用一句话生成分析模板 / 结论解读（ADR 0020 P3）──
  // 生成结果只填编辑态，不自动保存；解读只读，不写模板与数据。
  const [aiAppliedName, setAiAppliedName] = useState<string | null>(null)

  const suggestAi = useLlmAction(
    (payload: AnalyticsAiSuggestTemplatePayload) => analyticsApi.aiSuggestTemplate(wid!, payload),
    { fallbackError: 'AI 生成分析失败，请稍后重试' },
  )
  const explainAi = useLlmAction(
    (payload: AnalyticsAiExplainPayload) => analyticsApi.aiExplain(wid!, payload),
    { fallbackError: 'AI 解读失败，请稍后重试' },
  )
  const suggestRun = suggestAi.run
  const suggestReset = suggestAi.reset
  const explainRun = explainAi.run
  const explainReset = explainAi.reset

  /** 覆盖风险：已保存模板的未保存修改，或（无模板时）编辑区已有用户配置 */
  const aiOverwriteRisk = useMemo(() => {
    if (activeTemplateId != null) return dirty
    return (
      formulas.some(f => f.expr.trim() !== '')
      || !!chart.x
      || !!chart.y
      || summary.metrics.length > 0
      || templateName.trim() !== ''
    )
  }, [activeTemplateId, dirty, formulas, chart.x, chart.y, summary.metrics.length, templateName])

  /** 把 AI 生成的配置填入编辑态（不落库；保存仍由用户点「保存 / 保存为模板」） */
  const applyAiSuggestion = useCallback((suggestion: AnalyticsAiTemplateSuggestion) => {
    const next = applySuggestionConfig(suggestion.config)
    const name = suggestionName(suggestion, DEFAULT_TEMPLATE_NAME)
    setFormulas(next.formulas)
    setChart(next.chart)
    setSummary(next.summary)
    setTemplateName(name)
    setTemplateDesc(suggestion.description ?? '')
    setServerErrors({})
    setTableMissing(false)
    setAiAppliedName(name)
    message.success(`已填入 AI 生成的分析「${name}」，尚未保存，确认后点保存`)
  }, [message])

  const generateAnalysis = useCallback(async (question: string) => {
    if (!wid || tableId == null) {
      message.warning('请先选择分析表')
      return
    }
    setAiAppliedName(null)
    const data = await suggestRun({ table_id: tableId, question })
    if (!data) return
    const apply = () => applyAiSuggestion(data.result)
    if (!aiOverwriteRisk) {
      apply()
      return
    }
    modal.confirm({
      title: '覆盖当前编辑中的分析配置？',
      content: dirty
        ? '当前模板有未保存的修改，AI 生成结果将替换公式 / 图表 / 分组汇总；保存仍需你手动确认。'
        : 'AI 生成结果将替换当前编辑中的公式 / 图表 / 分组汇总；保存仍需你手动确认。',
      okText: '覆盖并填入',
      cancelText: '保留当前配置',
      onOk: apply,
    })
  }, [wid, tableId, suggestRun, aiOverwriteRisk, dirty, applyAiSuggestion, message, modal])

  /** 解读当前结果：有分组汇总用汇总行，否则退回派生数据行（后端再截断 50 行） */
  const requestExplain = useCallback(() => {
    if (!result) {
      message.warning('请先运行分析，再让 AI 解读结果')
      return
    }
    const payload = buildExplainPayload({ result, chartType: chart.type, templateId: activeTemplateId })
    if (payload.summary_rows.length === 0) {
      message.warning('当前没有可解读的结果行')
      return
    }
    void explainRun(payload)
  }, [result, chart.type, activeTemplateId, explainRun, message])

  const explainOpen = explainAi.loading || explainAi.error != null || explainAi.data != null
  const explainMeta = explainAi.data
    ? [
      explainAi.data.model ? `模型 ${explainAi.data.model}` : '',
      typeof explainAi.data.usage?.total_tokens === 'number'
        ? `${explainAi.data.usage.total_tokens} tokens`
        : '',
      `留痕 #${explainAi.data.run_id}`,
    ].filter(Boolean).join(' · ')
    : undefined
  const explainBasis = result
    ? `解读依据：${
      result.summary
        ? `分组汇总 ${Math.min(result.summary.rows.length, 50)} 行`
        : `派生数据 ${Math.min(result.rows.length, 50)} 行`
    } · 图表 ${chart.type}`
    : undefined

  // ── 深链：?template=<id> 刷新/分享后自动载入 ──
  // 注意：URL 更新走 React Router 的 transition，可能晚于模板列表刷新一个渲染；
  // 这里用「已处理参数」ref 记录真正处理过的值，避免保存模板后的过渡态把旧模板再载入一次。
  useEffect(() => {
    if (!templateParam) {
      handledParamRef.current = null
      return
    }
    if (templates.length === 0) return
    if (handledParamRef.current === templateParam) return
    handledParamRef.current = templateParam
    const tpl = templates.find(t => String(t.id) === templateParam)
    if (!tpl) return
    if (activeTemplateId != null && tpl.id === activeTemplateId) return
    applyTemplateConfig(tpl)
  }, [templateParam, templates, activeTemplateId, applyTemplateConfig])

  // ── URL 同步：当前模板写入 ?template=<id>（刷新/分享保持；清空由 clearActiveTemplate 负责）──
  useEffect(() => {
    if (activeTemplateId == null) return
    if (templateParam === String(activeTemplateId)) return
    setSearchParams(prev => {
      const next = new URLSearchParams(prev)
      next.set('template', String(activeTemplateId))
      return next
    }, { replace: true })
  }, [activeTemplateId, templateParam, setSearchParams])

  // ── 公式实时校验（防抖 350ms；本地结构错误由 collectFormulaErrors 即时给出）──
  const validateTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const validateSeq = useRef(0)
  const formulasKey = JSON.stringify(formulas)
  useEffect(() => {
    if (!wid) return
    if (!formulas.some(f => f.expr.trim() && f.key.trim())) {
      setServerErrors({})
      return
    }
    if (validateTimer.current) clearTimeout(validateTimer.current)
    validateTimer.current = setTimeout(() => {
      const seq = ++validateSeq.current
      analyticsApi
        .validate(wid, tableId, formulas)
        .then(res => {
          if (seq !== validateSeq.current) return // 丢弃过期响应
          const next: Record<string, string> = {}
          for (const item of res.results) {
            if (!item.ok) next[item.key] = item.error || '公式非法'
          }
          setServerErrors(next)
        })
        .catch(() => { /* 校验失败不打断编辑，运行时报错兜底 */ })
    }, 350)
    return () => {
      if (validateTimer.current) clearTimeout(validateTimer.current)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wid, tableId, formulasKey])

  // ── 模板保存 / 删除 ──
  const saveMutation = useMutation({
    mutationFn: async (vars: SaveVariables) => {
      if (vars.mode === 'create') {
        return analyticsApi.createTemplate(wid!, vars.payload as AnalyticsTemplateCreate)
      }
      return analyticsApi.updateTemplate(wid!, activeTemplateId!, vars.payload)
    },
    onSuccess: (tpl, vars) => {
      queryClient.setQueryData<AnalyticsTemplate[]>(['analytics-templates', wid], old => {
        const list = old ?? []
        return list.some(t => t.id === tpl.id) ? list.map(t => (t.id === tpl.id ? tpl : t)) : [tpl, ...list]
      })
      void queryClient.invalidateQueries({ queryKey: ['analytics-templates', wid] })
      applyTemplateConfig(tpl, { keepResult: true })
      setSaveOpen(false)
      message.success(
        vars.mode === 'create'
          ? `已另存为模板「${tpl.name}」`
          : vars.mode === 'rename'
            ? `模板已重命名为「${tpl.name}」`
            : `模板「${tpl.name}」已保存`,
      )
    },
    onError: () => message.error('保存失败：请检查公式与字段引用（仅编辑者及以上可保存）'),
  })

  const removeMutation = useMutation({
    mutationFn: (id: number) => analyticsApi.removeTemplate(wid!, id),
    onSuccess: (_r, id) => {
      if (id === activeTemplateId) clearActiveTemplate()
      void queryClient.invalidateQueries({ queryKey: ['analytics-templates', wid] })
      message.success('模板已删除')
    },
    onError: () => message.error('删除失败（需编辑者及以上权限）'),
  })

  /** 复制模板：成功后刷新列表并打开副本 */
  const duplicateMutation = useMutation({
    mutationFn: (tpl: AnalyticsTemplate) => analyticsApi.duplicateTemplate(wid!, tpl.id),
    onSuccess: tpl => {
      queryClient.setQueryData<AnalyticsTemplate[]>(['analytics-templates', wid], old => {
        const list = old ?? []
        return list.some(t => t.id === tpl.id) ? list.map(t => (t.id === tpl.id ? tpl : t)) : [tpl, ...list]
      })
      void queryClient.invalidateQueries({ queryKey: ['analytics-templates', wid] })
      message.success(`已复制为「${tpl.name}」`)
      // 与普通「打开模板」同口径：当前有未保存修改时先确认再载入副本
      requestTemplateLoad(tpl, { onApplied: () => setManagerOpen(false) })
    },
    onError: () => message.error('复制失败（需编辑者及以上权限）'),
  })

  /** 范围 → 扫描过滤（字段 + 起止值都是可选，两个都空等于不过滤） */
  const scopeFilters = useMemo<AnalyticsFilter[]>(() => {
    if (!scopeField) return []
    const filters: AnalyticsFilter[] = []
    const from = scopeFrom.trim()
    const to = scopeTo.trim()
    if (from) filters.push({ field_name: scopeField, op: '>=', value: from })
    if (to) filters.push({ field_name: scopeField, op: '<=', value: to })
    return filters
  }, [scopeField, scopeFrom, scopeTo])

  const computeMutation = useMutation({
    mutationFn: () =>
      analyticsApi.compute(wid!, {
        table_id: tableId!,
        formulas: validFormulas.map(f => ({
          key: f.key.trim(),
          label: (f.label ?? '').trim() || f.key.trim(),
          expr: f.expr.trim(),
          ...(f.partition_by ? { partition_by: f.partition_by } : {}),
          ...(f.order_by ? { order_by: f.order_by } : {}),
          ...(f.order_desc ? { order_desc: true } : {}),
        })),
        fields: [],
        limit: 1000,
        summary: summary.metrics.length ? summary : null,
        filters: scopeFilters,
      }),
    onSuccess: data => {
      setResult(data)
      // 结果已刷新：旧解读不再对应当前数据，关闭解读抽屉
      explainReset()
    },
    onError: (error: unknown) => {
      const detail = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      message.error(detail ? `计算失败：${detail}` : '计算失败，请检查公式与分组汇总配置')
    },
  })

  const runAnalysis = useCallback(() => {
    if (!canRun || computeMutation.isPending) return
    computeMutation.mutate()
  }, [canRun, computeMutation])

  // ── 全局快捷键：Win/⌘/Ctrl + Enter 运行分析（公式输入框内的同键位已在 FormulaPanel 内处理并阻断冒泡）──
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
        e.preventDefault()
        runAnalysis()
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [runAnalysis])

  // 有未保存修改时，关闭/刷新页面前给浏览器原生提示
  useEffect(() => {
    if (!dirty) return
    const handler = (event: BeforeUnloadEvent) => {
      event.preventDefault()
      event.returnValue = ''
    }
    window.addEventListener('beforeunload', handler)
    return () => window.removeEventListener('beforeunload', handler)
  }, [dirty])

  const openSaveAs = () => {
    setSaveMode('create')
    setFormName(activeTemplateId != null ? `${templateName || DEFAULT_TEMPLATE_NAME} 副本` : templateName || DEFAULT_TEMPLATE_NAME)
    setFormDesc(templateDesc)
    setSaveOpen(true)
  }

  const openRename = () => {
    setSaveMode('rename')
    setFormName(templateName)
    setFormDesc(templateDesc)
    setSaveOpen(true)
  }

  const submitModal = () => {
    const name = formName.trim()
    if (!name) {
      message.warning('请填写模板名称')
      return
    }
    if (saveMode === 'rename') {
      saveMutation.mutate({ mode: 'rename', payload: { name, description: formDesc } })
      return
    }
    const payload: AnalyticsTemplateCreate = {
      name,
      description: formDesc,
      table_id: tableId,
      config: buildTemplateConfig({ formulas, chart, summary }),
    }
    saveMutation.mutate({ mode: 'create', payload })
  }

  const saveActiveTemplate = () => {
    if (activeTemplateId == null) {
      openSaveAs()
      return
    }
    saveMutation.mutate({
      mode: 'update',
      payload: {
        name: templateName.trim() || DEFAULT_TEMPLATE_NAME,
        description: templateDesc,
        table_id: tableId,
        config: buildTemplateConfig({ formulas, chart, summary }),
      },
    })
  }

  const activeTemplate = useMemo(
    () => templates.find(t => t.id === activeTemplateId) ?? null,
    [templates, activeTemplateId],
  )
  /** 结果盒共用的导出文件名主体：模板名优先，其次图表标题 */
  const resultTitle = templateName || chart.title || '分析结果'
  const showTableMissing = (tableMissing || activeTemplate?.table_id == null) && tableId == null && activeTemplateId != null

  if (!wid) return null

  return (
    <div data-testid="analytics-page" className="cn-page cn-an-page">
      {/* ── 页头：标题 + 当前模板 + 模板操作／运行（主操作常驻右侧） ── */}
      <header className="cn-an-head">
        <div className="cn-an-head-main">
          <span className="cn-an-head-icon" aria-hidden><BarChartOutlined /></span>
          <div className="cn-an-head-text">
            <h1 className="cn-an-head-title">数据分析</h1>
            <div className="cn-an-head-sub">
              {activeTemplateId != null ? (
                <span
                  data-testid="analytics-template-meta"
                  className="cn-an-head-meta"
                  title={templateDesc ? `模板描述：${templateDesc}` : undefined}
                >
                  当前模板：{templateName}
                  {activeTemplate?.updated_at ? ` · 更新于 ${new Date(activeTemplate.updated_at).toLocaleString()}` : ''}
                </span>
              ) : (
                <span>工作区任意数据表 · 模板存后端，可跨设备复用</span>
              )}
              {dirty && <Tag color="orange" data-testid="analytics-dirty">未保存</Tag>}
            </div>
          </div>
        </div>

        <div className="cn-an-head-actions">
          {/* 连体按钮组：不设 size，与周围默认尺寸控件等高 */}
          <Space.Compact className="cn-an-block-toggles" data-testid="analytics-block-toggles">
            {([
              { key: 'chart', label: '可视化', icon: <BarChartOutlined /> },
              { key: 'summary', label: '分组汇总', icon: <GroupOutlined /> },
              { key: 'formula', label: '计算模板', icon: <FunctionOutlined /> },
            ] as Array<{ key: AnalyticsBlockKey; label: string; icon: JSX.Element }>).map(item => (
              <Button
                key={item.key}
                className="cn-an-block-toggle"
                data-testid={`analytics-block-toggle-${item.key}`}
                aria-label={`启用${item.label}区块`}
                aria-pressed={blocks[item.key]}
                type={blocks[item.key] ? 'primary' : 'default'}
                ghost={blocks[item.key]}
                icon={item.icon}
                onClick={() => toggleBlock(item.key, !blocks[item.key])}
              >
                {item.label}
              </Button>
            ))}
          </Space.Compact>
          <Select
            data-testid="analytics-template-select"
            style={{ width: 200 }}
            placeholder="加载已保存模板"
            value={activeTemplateId ?? undefined}
            allowClear
            options={templates.map(t => ({ value: t.id, label: t.name }))}
            onChange={id => {
              if (id == null) {
                clearActiveTemplate()
                return
              }
              const tpl = templates.find(t => t.id === id)
              if (tpl) requestTemplateLoad(tpl)
            }}
          />
          <Tooltip title="分析列表：打开 / 复制 / 删除 / 新建">
            <Button
              data-testid="analytics-manager-btn"
              aria-label="分析列表"
              icon={<UnorderedListOutlined />}
              onClick={() => setManagerOpen(true)}
            />
          </Tooltip>
          <Button
            data-testid="analytics-save-btn"
            icon={<SaveOutlined />}
            loading={saveMutation.isPending}
            onClick={saveActiveTemplate}
          >
            {activeTemplateId != null ? '保存' : '保存为模板'}
          </Button>
          <Tooltip title="另存为副本">
            <Button
              data-testid="analytics-saveas-btn"
              aria-label="另存为副本"
              icon={<CopyOutlined />}
              disabled={templatePending}
              onClick={openSaveAs}
            />
          </Tooltip>
          <Tooltip title="重命名当前模板">
            <Button
              data-testid="analytics-rename-btn"
              aria-label="重命名当前模板"
              icon={<EditOutlined />}
              disabled={activeTemplateId == null || templatePending}
              onClick={openRename}
            />
          </Tooltip>
          {activeTemplateId != null && (
            <Tooltip title="删除当前模板">
              <Button
                danger
                aria-label="删除当前模板"
                icon={<DeleteOutlined />}
                loading={removeMutation.isPending}
                onClick={() => {
                  modal.confirm({
                    title: `删除模板「${templateName || activeTemplate?.name || ''}」？`,
                    onOk: () => removeMutation.mutate(activeTemplateId),
                  })
                }}
              />
            </Tooltip>
          )}
          <Tooltip title="Win / ⌘ / Ctrl + Enter">
            <Button
              type="primary"
              data-testid="analytics-run-btn"
              icon={<PlayCircleOutlined />}
              loading={computeMutation.isPending}
              disabled={!canRun}
              onClick={runAnalysis}
            >
              运行分析 (Ctrl+Enter)
            </Button>
          </Tooltip>
          {!tableId && <Text type="secondary" className="cn-an-run-hint">请先选择分析表</Text>}
          {!!tableId && noRunnableConfig && (
            <Text type="secondary" className="cn-an-run-hint">请填写公式，或配置图表 / 分组汇总后再运行</Text>
          )}
          {!!tableId && hasError && (
            <Text type="danger" className="cn-an-run-hint">公式存在错误，修正后可运行</Text>
          )}
        </div>
      </header>

      {showTableMissing && (
        <Alert
          type="warning"
          showIcon
          data-testid="analytics-table-missing"
          message="该模板的数据源表已被删除，请重新选择分析表后再运行"
        />
      )}

      <div className="cn-an-workbench">
        {/* 顶部并列：数据源 + 智能推荐（未选表时推荐收起为窄条，选表后向右展开） */}
        <div
          className={tableId != null ? 'cn-an-top cn-an-top--expanded' : 'cn-an-top'}
          data-testid="analytics-top"
        >
          <div className="cn-an-top-data">
            <AnalyticsBox
              title="数据源"
              icon={<DatabaseOutlined />}
              extra={tableDetail
                ? `${tableDetail.fields.length} 字段 · ${tableDetail.record_count ?? 0} 行`
                : '未选择'}
              footer={scopeField
                ? <span className="cn-an-foot-hint">只统计区间内的行；全表扫描超上限时用它收窄</span>
                : null}
            >
          <div className="cn-an-grid cn-an-grid--3">
            <div className="cn-an-field cn-an-span3">
              <span className="cn-an-label">分析表</span>
              <Select
                data-testid="analytics-table-select"
                placeholder="选择工作区内的数据表"
                value={tableId ?? undefined}
                options={tables.map(t => ({ value: Number(t.id), label: t.name }))}
                onChange={id => {
                  setTableId(id ?? null)
                  setTableMissing(false)
                  setResult(null)
                  setServerErrors({})
                  // 换表后 AI 生成结果 / 解读都不再对应当前数据源，清空避免误用
                  setAiAppliedName(null)
                  suggestReset()
                  explainReset()
                  // 范围字段属于旧表，换表后必须清空，否则会带着不存在的字段去过滤
                  setScopeField(null)
                  setScopeFrom('')
                  setScopeTo('')
                }}
              />
            </div>
            {/* 分析范围：扫描前过滤（时序表用「时间 >= 起点」把扫描面压到区间内） */}
            <div className="cn-an-field">
              <span className="cn-an-label">范围字段</span>
              <Select
                size="small"
                allowClear
                data-testid="analytics-scope-field"
                placeholder="不限（全表）"
                value={scopeField ?? undefined}
                options={tableFields.map(name => ({ value: name, label: name }))}
                onChange={value => setScopeField(value ?? null)}
              />
            </div>
            <div className="cn-an-field">
              <span className="cn-an-label">起始值（含）</span>
              <Input
                size="small"
                data-testid="analytics-scope-from"
                placeholder="如 2025-01-01"
                disabled={!scopeField}
                value={scopeFrom}
                onChange={event => setScopeFrom(event.target.value)}
              />
            </div>
            <div className="cn-an-field">
              <span className="cn-an-label">结束值（含）</span>
              <Input
                size="small"
                data-testid="analytics-scope-to"
                placeholder="可选"
                disabled={!scopeField}
                value={scopeTo}
                onChange={event => setScopeTo(event.target.value)}
              />
            </div>
          </div>
        </AnalyticsBox>
          </div>

          <div className="cn-an-top-recommend">
            <RecommendationPanel
              collapsed={tableId == null}
              recommendations={recommendations}
              loading={recommendLoading}
              error={recommendError}
              tableName={tableId != null
                ? tableDetail?.name ?? templateTableName(tables, tableId)
                : undefined}
              onSelectDimension={selectRecommendedDimension}
              onSelectMetric={selectRecommendedMetric}
              onSelectTime={selectRecommendedTime}
              onApplyChart={applyRecommendedChart}
              onApplySummary={applyRecommendedSummary}
              onApplyFormulas={applyRecommendedFormulas}
              onApplyExample={applyRecommendedExample}
            />
          </div>
        </div>

        {/* ── 第一段：可视化 → 图表 ── */}
        {blocks.chart && (
        <section className="cn-an-band" data-testid="analytics-band-chart">
          <div className="cn-an-band-config">
            <ChartPanel
              chart={chart}
              onChange={setChart}
              options={chartOptions}
              tableFields={tableFields}
            />
          </div>
          <div className="cn-an-band-result">
            {result ? (
              <ChartResultBox
                result={result}
                chart={chart}
                fields={syntheticFields}
                title={resultTitle}
                onAiExplain={llmConfigured ? requestExplain : undefined}
                aiExplainLoading={explainAi.loading}
              />
            ) : (
              <ResultPlaceholder text="运行分析后，这里显示图表" />
            )}
          </div>
        </section>
        )}

        {/* ── 第二段：分组汇总 → 汇总表 ── */}
        {blocks.summary && (
        <section className="cn-an-band" data-testid="analytics-band-summary">
          <div className="cn-an-band-config">
            <SummaryPanel
              summary={summary}
              onChange={setSummary}
              groupOptions={groupOptions}
              metricOptions={chartOptions}
            />
          </div>
          <div className="cn-an-band-result">
            {result
              ? <SummaryResultBox result={result} title={resultTitle} />
              : <ResultPlaceholder text="运行分析后，这里显示分组汇总表" />}
          </div>
        </section>
        )}

        {/* ── 第三段：计算模板 → 描述统计 + 派生数据 ── */}
        {blocks.formula && (
        <section className="cn-an-band" data-testid="analytics-band-formula">
          <div className="cn-an-band-config">
            <FormulaPanel
              tableFields={tableFields}
              numericFields={numericFields}
              formulas={formulas}
              errors={errors}
              onChange={setFormulas}
              onRun={runAnalysis}
              canRun={canRun}
              running={computeMutation.isPending}
            />
          </div>
          <div className="cn-an-band-result">
            {result ? (
              <>
                <StatsResultBox result={result} title={resultTitle} />
                <RowsResultBox
                  result={result}
                  fields={syntheticFields}
                  formulas={validFormulas.map(f => ({
                    key: f.key.trim(),
                    label: (f.label ?? '').trim() || f.key.trim(),
                  }))}
                  title={resultTitle}
                />
              </>
            ) : (
              <ResultPlaceholder text="运行分析后，这里显示描述统计与派生数据" />
            )}
          </div>
        </section>
        )}
      </div>

      {llmConfigured && (
        <AnalyticsAiPanel
          tableReady={tableId != null}
          loading={suggestAi.loading}
          error={suggestAi.error}
          suggestion={suggestAi.data?.result ?? null}
          appliedName={aiAppliedName}
          onGenerate={question => { void generateAnalysis(question) }}
        />
      )}

      {/* ── 另存为 / 重命名 ── */}
      <Modal
        title={saveMode === 'rename' ? '重命名分析模板' : '另存为分析模板'}
        open={saveOpen}
        onCancel={() => setSaveOpen(false)}
        onOk={submitModal}
        confirmLoading={saveMutation.isPending}
        okText={saveMode === 'rename' ? '重命名' : '保存'}
      >
        <Space direction="vertical" style={{ width: '100%' }}>
          <Input
            data-testid="analytics-template-name"
            placeholder="模板名称"
            value={formName}
            onChange={e => setFormName(e.target.value)}
          />
          <Input.TextArea
            rows={2}
            placeholder="说明（可选）"
            value={formDesc}
            onChange={e => setFormDesc(e.target.value)}
          />
          <Text type="secondary" style={{ fontSize: 12 }}>
            模板保存到后端（含公式、图表与分组汇总配置），工作区成员均可加载；仅编辑者及以上可保存/删除。
          </Text>
        </Space>
      </Modal>

      {/* ── AI 结论解读抽屉：只读，只展示结论 + 口径提醒（lazy 挂载） ── */}
      {explainOpen && (
        <Suspense fallback={null}>
          <AnalyticsAiExplainDrawer
            open
            onClose={explainReset}
            loading={explainAi.loading}
            error={explainAi.error}
            result={explainAi.data?.result ?? null}
            meta={explainMeta}
            basis={explainBasis}
            onRegenerate={requestExplain}
            testId="analytics-ai-explain-drawer"
          />
        </Suspense>
      )}

      {/* ── 分析列表 Drawer：打开 / 复制 / 删除 / 新建 ── */}
      <AnalyticsManagerDrawer
        open={managerOpen}
        onClose={() => setManagerOpen(false)}
        templates={templates}
        tables={tables}
        activeTemplateId={activeTemplateId}
        dirty={dirty}
        duplicating={duplicateMutation.isPending}
        deleting={removeMutation.isPending}
        onOpenTemplate={tpl => requestTemplateLoad(tpl, { onApplied: () => setManagerOpen(false) })}
        onDuplicate={tpl => duplicateMutation.mutate(tpl)}
        onDelete={tpl => removeMutation.mutate(tpl.id)}
        onNew={startNewAnalysis}
      />
    </div>
  )
}
