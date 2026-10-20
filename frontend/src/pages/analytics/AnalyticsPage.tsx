/** 数据分析页 —— 独立于文档的工作区级模块.
 *
 * 定位：数据源为工作区内任意数据表，提供「公式 + 分组汇总 + 图表 + 描述统计」一体化分析。
 *
 * 页面能力：
 * - 模板：加载 / 保存 / 另存为副本 / 重命名 / 删除；`?template=<id>` 深链刷新保持；
 *   有未保存修改时切换模板先确认
 * - 计算模板：多行公式编辑器（字段/函数快捷插入、示例片段、Ctrl/Cmd+Enter 运行、实时校验）
 * - 可视化：图表类型 + 维度聚合方式 + 维度/指标/系列
 * - 分组汇总：分组字段 + 指标（字段/公式 × 聚合）+ 排序 + Top N
 * - 结果：图表（可导出 PNG）+ 分组汇总表 + 描述统计（方差/极差/非空率）+ 派生数据（分页/排序/CSV）
 *
 * 公式语法（后端受限引擎，非 eval）：`[字段名]` 引用字段、`+ - * / ( )`、后缀 `%`、
 * round/abs/sqrt/pow/ceil/floor、整列聚合 sum/avg/count/min/max。
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useParams, useSearchParams } from 'react-router-dom'
import {
  App as AntApp, Alert, Button, Card, Empty, Input, Modal, Select,
  Space, Tag, Typography,
} from 'antd'
import {
  DeleteOutlined, SaveOutlined, BarChartOutlined, PlayCircleOutlined, CopyOutlined, EditOutlined,
  UnorderedListOutlined,
} from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { tableApi } from '@/api'
import type { Field } from '@/api'
import { analyticsApi } from '@/api/analytics'
import type {
  AnalyticsChart, AnalyticsComputeResponse, AnalyticsFormula, AnalyticsRecommendationExample,
  AnalyticsSummary, AnalyticsTemplate, AnalyticsTemplateCreate, AnalyticsTemplateUpdate,
} from '@/api/analytics'
import { FormulaPanel } from './FormulaPanel'
import { ChartPanel } from './ChartPanel'
import { SummaryPanel } from './SummaryPanel'
import { AnalyticsResultView } from './AnalyticsResultView'
import { RecommendationPanel } from './RecommendationPanel'
import { AnalyticsManagerDrawer } from './AnalyticsManagerDrawer'
import {
  DEFAULT_CHART,
  EMPTY_SUMMARY,
  applyExampleConfig,
  buildTemplateConfig,
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

const { Text, Title } = Typography

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

  // ── 分析配置 ──
  const [tableId, setTableId] = useState<number | null>(null)
  const [formulas, setFormulas] = useState<AnalyticsFormula[]>([newFormula(0)])
  const [chart, setChart] = useState<AnalyticsChart>({ ...DEFAULT_CHART })
  const [summary, setSummary] = useState<AnalyticsSummary>({ ...EMPTY_SUMMARY, metrics: [] })
  const [result, setResult] = useState<AnalyticsComputeResponse | null>(null)
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

  const { data: templates = [] } = useQuery({
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
  const canRun = !!tableId && validFormulas.length > 0 && !hasError

  const currentSnapshot = useMemo(
    () => templateSnapshot({ name: templateName, description: templateDesc, tableId, formulas, chart, summary }),
    [templateName, templateDesc, tableId, formulas, chart, summary],
  )
  const dirty = activeTemplateId != null && isDirty(snapshot, currentSnapshot)

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

  // ── 深链：?template=<id> 刷新/分享后自动载入 ──
  // 注意：URL 更新走 React Router 的 transition，可能晚于模板列表刷新一个渲染；
  // 这里用「已处理参数」ref 记录真正处理过的值，避免保存模板后的过渡态把旧模板再载入一次。
  const templateParam = searchParams.get('template')
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
      }),
    onSuccess: data => setResult(data),
    onError: (error: unknown) => {
      const detail = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      message.error(detail ? `计算失败：${detail}` : '计算失败，请检查公式与分组汇总配置')
    },
  })

  const runAnalysis = useCallback(() => {
    if (!canRun || computeMutation.isPending) return
    computeMutation.mutate()
  }, [canRun, computeMutation])

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
  const showTableMissing = (tableMissing || activeTemplate?.table_id == null) && tableId == null && activeTemplateId != null

  if (!wid) return null

  return (
    <div data-testid="analytics-page" style={{ padding: 16, display: 'flex', flexDirection: 'column', gap: 12 }}>
      {/* ── 顶栏：标题 + 模板管理 ── */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
        <Title level={4} style={{ margin: 0 }}>
          <BarChartOutlined /> 数据分析
        </Title>
        <Text type="secondary" style={{ fontSize: 12 }}>
          数据源为工作区内任意数据表；模板存后端，可跨设备复用
        </Text>
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
          <Button
            data-testid="analytics-manager-btn"
            icon={<UnorderedListOutlined />}
            onClick={() => setManagerOpen(true)}
          >
            分析列表
          </Button>
          <Select
            data-testid="analytics-template-select"
            style={{ width: 220 }}
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
          {dirty && <Tag color="orange" data-testid="analytics-dirty">未保存</Tag>}
          <Button
            data-testid="analytics-save-btn"
            icon={<SaveOutlined />}
            loading={saveMutation.isPending}
            onClick={saveActiveTemplate}
          >
            {activeTemplateId != null ? '保存模板' : '保存为模板'}
          </Button>
          <Button
            data-testid="analytics-saveas-btn"
            icon={<CopyOutlined />}
            onClick={openSaveAs}
          >
            另存为
          </Button>
          <Button
            data-testid="analytics-rename-btn"
            icon={<EditOutlined />}
            disabled={activeTemplateId == null}
            onClick={openRename}
          >
            重命名
          </Button>
          {activeTemplateId != null && (
            <Button
              danger
              icon={<DeleteOutlined />}
              loading={removeMutation.isPending}
              onClick={() => {
                modal.confirm({
                  title: `删除模板「${templateName || activeTemplate?.name || ''}」？`,
                  onOk: () => removeMutation.mutate(activeTemplateId),
                })
              }}
            >
              删除
            </Button>
          )}
        </div>
      </div>
      {activeTemplateId != null && (
        <Text type="secondary" style={{ fontSize: 12, marginTop: -4 }} data-testid="analytics-template-meta">
          当前模板：{templateName}{templateDesc ? ` · ${templateDesc}` : ''}
          {activeTemplate?.updated_at ? ` · 更新于 ${new Date(activeTemplate.updated_at).toLocaleString()}` : ''}
        </Text>
      )}

      {showTableMissing && (
        <Alert
          type="warning"
          showIcon
          data-testid="analytics-table-missing"
          message="该模板的数据源表已被删除，请重新选择分析表后再运行"
        />
      )}

      {/* ── 数据源 ── */}
      <Card size="small" title="数据源">
        <Space wrap>
          <Text>分析表：</Text>
          <Select
            data-testid="analytics-table-select"
            style={{ width: 260 }}
            placeholder="选择工作区内的数据表"
            value={tableId ?? undefined}
            options={tables.map(t => ({ value: Number(t.id), label: t.name }))}
            onChange={id => {
              setTableId(id ?? null)
              setTableMissing(false)
              setResult(null)
              setServerErrors({})
            }}
          />
          {tableDetail && (
            <Text type="secondary" style={{ fontSize: 12 }}>
              {tableDetail.fields.length} 个字段 / {tableDetail.record_count ?? 0} 行
            </Text>
          )}
          <Text type="secondary" style={{ fontSize: 12 }}>
            可用字段：{tableFields.length ? tableFields.join('、') : '（先选择数据表）'}
          </Text>
        </Space>
      </Card>

      {/* ── 智能推荐：选表后按字段画像推荐图表 / 汇总 / 公式 / 典型示例 ── */}
      {tableId != null && (
        <RecommendationPanel
          recommendations={recommendations}
          loading={recommendLoading}
          error={recommendError}
          tableName={tableDetail?.name ?? templateTableName(tables, tableId)}
          onSelectDimension={selectRecommendedDimension}
          onSelectMetric={selectRecommendedMetric}
          onSelectTime={selectRecommendedTime}
          onApplyChart={applyRecommendedChart}
          onApplySummary={applyRecommendedSummary}
          onApplyFormulas={applyRecommendedFormulas}
          onApplyExample={applyRecommendedExample}
        />
      )}

      {/* ── 配置区：公式 + 图表，分组汇总占整行 ── */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(420px, 1fr))', gap: 12 }}>
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
        <ChartPanel
          chart={chart}
          onChange={setChart}
          options={chartOptions}
          tableFields={tableFields}
        />
      </div>
      <SummaryPanel
        summary={summary}
        onChange={setSummary}
        groupOptions={groupOptions}
        metricOptions={chartOptions}
      />

      {/* ── 运行 ── */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <Button
          type="primary"
          data-testid="analytics-run-btn"
          icon={<PlayCircleOutlined />}
          loading={computeMutation.isPending}
          disabled={!canRun}
          onClick={runAnalysis}
        >
          运行分析
        </Button>
        {!tableId && <Text type="secondary" style={{ fontSize: 12 }}>请先选择分析表</Text>}
        {!!tableId && validFormulas.length === 0 && (
          <Text type="secondary" style={{ fontSize: 12 }}>请至少填写一条公式</Text>
        )}
        {!!tableId && hasError && <Text type="danger" style={{ fontSize: 12 }}>公式存在错误，修正后可运行</Text>}
      </div>

      {/* ── 结果 ── */}
      {result ? (
        <AnalyticsResultView
          result={result}
          chart={chart}
          formulas={validFormulas.map(f => ({
            key: f.key.trim(),
            label: (f.label ?? '').trim() || f.key.trim(),
          }))}
          fields={syntheticFields}
          title={templateName || chart.title || '分析结果'}
        />
      ) : (
        <Card size="small">
          <Empty
            description={
              <span>
                选择数据表并配置公式后点击「运行分析」
                {templates.length > 0 && (
                  <>
                    <br />
                    <Button
                      type="link"
                      size="small"
                      onClick={() => requestTemplateLoad(templates[0])}
                    >
                      载入示例模板「{templates[0]?.name}」
                    </Button>
                  </>
                )}
              </span>
            }
          />
        </Card>
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
