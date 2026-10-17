/** 数据分析页 —— 独立于文档的工作区级模块.
 *
 * 定位：数据源为工作区内任意数据表（与文档正文的 `{{table:…}}` 引用解耦），
 * 提供描述统计 + 自定义计算模板（公式引擎）+ 可视化图表。
 *
 * 结构：
 * - 顶栏：加载已保存模板 + 保存/另存为/删除
 * - 数据源：选表
 * - 计算模板：多行公式编辑器（键名 / 展示名 / 表达式），经 /analytics/validate 实时校验
 * - 可视化配置：图表类型 + 维度/指标/系列 + 标题
 * - 结果：图表（复用网格视图 ChartCard）+ 全列描述统计 + 派生数据预览
 *
 * 公式语法（后端受限引擎，非 eval）：`[字段名]` 引用字段、`+ - * / ( )`、后缀 `%`、
 * round/abs/sqrt/pow/ceil/floor、整列聚合 sum/avg/count/min/max。
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import {
  App as AntApp, Alert, Button, Card, Empty, Input, Modal, Select,
  Space, Table, Tag, Tooltip, Typography,
} from 'antd'
import {
  DeleteOutlined, PlusOutlined, SaveOutlined, BarChartOutlined, PlayCircleOutlined,
} from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { tableApi } from '@/api'
import type { Field } from '@/api'
import { analyticsApi } from '@/api/analytics'
import type { AnalyticsChart, AnalyticsComputeResponse, AnalyticsFormula, AnalyticsTemplate } from '@/api/analytics'
import { ChartCard } from '@/pages/grid/views/ChartView'
import type { ChartConfig } from '@/pages/grid/views/chartBoard'

const { Text, Title } = Typography

/** 图表类型候选（对齐后端 ChartSpec.type） */
const CHART_TYPES: Array<{ value: string; label: string }> = [
  { value: 'bar', label: '柱状图' },
  { value: 'line', label: '折线图' },
  { value: 'pie', label: '饼图' },
  { value: 'scatter', label: '散点图' },
  { value: 'histogram', label: '直方图' },
  { value: 'boxplot', label: '箱线图' },
]

const DEFAULT_TEMPLATE_NAME = '未命名分析'
const PREVIEW_ROWS = 50

/** 新建一条空公式行 */
function newFormula(index: number): AnalyticsFormula {
  return { key: `metric_${index + 1}`, label: '', expr: '' }
}

/** 分析图表配置 → ChartCard 的 ChartConfig（按图表类型分派字段语义） */
function toChartConfig(chart: AnalyticsChart): ChartConfig {
  const x = chart.x ?? undefined
  const y = chart.y ?? undefined
  const cfg: ChartConfig = {
    chart_type: chart.type as ChartConfig['chart_type'],
    aggregation: 'sum',
    show_stats_panel: true,
  }
  if (chart.type === 'scatter') {
    cfg.x_field = x
    cfg.y_field = y
  } else if (chart.type === 'histogram') {
    // 直方图对单个数值列分箱：x 即被分箱的列
    cfg.measure_field = x ?? y
  } else {
    cfg.dimension_field = x
    cfg.measure_field = y
    cfg.group_field = chart.series ?? undefined
  }
  return cfg
}

/** 数值显示：整数原样，浮点保留 4 位有效数字 */
function fmt(v: unknown): string {
  if (typeof v !== 'number' || !Number.isFinite(v)) return '—'
  return Number.isInteger(v) ? String(v) : String(parseFloat(v.toPrecision(4)))
}

export default function AnalyticsPage() {
  const { wid } = useParams<{ wid: string }>()
  const { message, modal } = AntApp.useApp()
  const queryClient = useQueryClient()

  const [tableId, setTableId] = useState<number | null>(null)
  const [formulas, setFormulas] = useState<AnalyticsFormula[]>([newFormula(0)])
  const [chart, setChart] = useState<AnalyticsChart>({ type: 'bar', x: null, y: null, series: null, title: '' })
  const [result, setResult] = useState<AnalyticsComputeResponse | null>(null)
  const [activeTemplateId, setActiveTemplateId] = useState<number | null>(null)
  const [templateName, setTemplateName] = useState('')
  const [templateDesc, setTemplateDesc] = useState('')
  const [saveOpen, setSaveOpen] = useState(false)
  /** 校验结果：公式键 → 错误信息 */
  const [errors, setErrors] = useState<Record<string, string>>({})

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

  const tableFields = useMemo<string[]>(() => (tableDetail?.fields ?? []).map(f => f.name), [tableDetail])

  const formulasKey = JSON.stringify(formulas)

  // ── 公式实时校验（防抖 350ms，避免逐字符打接口）──
  const validateTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  useEffect(() => {
    if (!wid || !formulasKey) return
    if (validateTimer.current) clearTimeout(validateTimer.current)
    validateTimer.current = setTimeout(() => {
      analyticsApi
        .validate(wid, tableId, formulas)
        .then(res => {
          const next: Record<string, string> = {}
          for (const item of res.results) {
            if (!item.ok) next[item.key] = item.error || '公式非法'
          }
          setErrors(next)
        })
        .catch(() => { /* 校验失败不打断编辑，运行时报错兜底 */ })
    }, 350)
    return () => {
      if (validateTimer.current) clearTimeout(validateTimer.current)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wid, tableId, formulasKey])

  /** 载入模板 → 回填公式 / 图表 / 表 */
  const loadTemplate = useCallback((tpl: AnalyticsTemplate) => {
    setActiveTemplateId(tpl.id)
    setTemplateName(tpl.name)
    setTemplateDesc(tpl.description || '')
    setFormulas(tpl.config.formulas?.length ? tpl.config.formulas.map(f => ({ ...f })) : [newFormula(0)])
    setChart({
      type: tpl.config.chart?.type || 'bar',
      x: tpl.config.chart?.x ?? null,
      y: tpl.config.chart?.y ?? null,
      series: tpl.config.chart?.series ?? null,
      title: tpl.config.chart?.title || '',
    })
    if (tpl.table_id) setTableId(tpl.table_id)
    setResult(null)
  }, [])

  const validFormulas = useMemo(
    () => formulas.filter(f => f.key.trim() && f.expr.trim()),
    [formulas],
  )

  /** 收集可提交的配置（过滤空行） */
  const buildConfig = useCallback(
    () => ({
      formulas: validFormulas.map(f => ({
        key: f.key.trim(),
        label: (f.label ?? '').trim() || f.key.trim(),
        expr: f.expr.trim(),
      })),
      chart,
      limit: 1000,
    }),
    [validFormulas, chart],
  )

  const saveMutation = useMutation({
    mutationFn: async (mode: 'create' | 'update') => {
      const payload = {
        name: templateName.trim() || DEFAULT_TEMPLATE_NAME,
        description: templateDesc,
        table_id: tableId,
        config: buildConfig(),
      }
      return mode === 'update' && activeTemplateId != null
        ? analyticsApi.updateTemplate(wid!, activeTemplateId, payload)
        : analyticsApi.createTemplate(wid!, payload)
    },
    onSuccess: tpl => {
      setActiveTemplateId(tpl.id)
      setTemplateName(tpl.name)
      setSaveOpen(false)
      void queryClient.invalidateQueries({ queryKey: ['analytics-templates', wid] })
      message.success(`分析模板「${tpl.name}」已保存`)
    },
    onError: () => message.error('保存失败：请检查公式与字段引用（仅编辑者及以上可保存）'),
  })

  const removeMutation = useMutation({
    mutationFn: (id: number) => analyticsApi.removeTemplate(wid!, id),
    onSuccess: (_r, id) => {
      if (id === activeTemplateId) setActiveTemplateId(null)
      void queryClient.invalidateQueries({ queryKey: ['analytics-templates', wid] })
      message.success('模板已删除')
    },
    onError: () => message.error('删除失败（需编辑者及以上权限）'),
  })

  const computeMutation = useMutation({
    mutationFn: () =>
      analyticsApi.compute(wid!, {
        table_id: tableId!,
        formulas: buildConfig().formulas,
        fields: [],
        limit: 1000,
      }),
    onSuccess: data => setResult(data),
    onError: () => message.error('计算失败，请检查公式是否合法'),
  })

  const hasError = Object.keys(errors).length > 0
  const canRun = !!tableId && validFormulas.length > 0 && !hasError

  /** 图表可选值：表字段 + 公式键（公式键在结果行中作为列存在） */
  const chartOptions = useMemo(
    () => [
      ...validFormulas.map(f => ({ value: f.key.trim(), label: `${(f.label ?? '').trim() || f.key.trim()}（公式）` })),
      ...tableFields.map(name => ({ value: name, label: name })),
    ],
    [validFormulas, tableFields],
  )

  /** ChartCard 需要的最小 Field 结构：公式列合成 number 字段 */
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

  if (!wid) return null

  return (
    <div data-testid="analytics-page" style={{ padding: 16, display: 'flex', flexDirection: 'column', gap: 12 }}>
      {/* ── 顶栏 ── */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
        <Title level={4} style={{ margin: 0 }}>
          <BarChartOutlined /> 数据分析
        </Title>
        <Text type="secondary" style={{ fontSize: 12 }}>
          数据源为工作区内任意数据表；模板存后端，可跨设备复用
        </Text>
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 8, alignItems: 'center' }}>
          <Select
            data-testid="analytics-template-select"
            style={{ width: 220 }}
            placeholder="加载已保存模板"
            value={activeTemplateId ?? undefined}
            allowClear
            options={templates.map(t => ({ value: t.id, label: t.name }))}
            onChange={id => {
              const tpl = templates.find(t => t.id === id)
              if (tpl) loadTemplate(tpl)
              else setActiveTemplateId(null)
            }}
          />
          <Button
            data-testid="analytics-save-btn"
            icon={<SaveOutlined />}
            loading={saveMutation.isPending}
            onClick={() => {
              if (activeTemplateId != null) saveMutation.mutate('update')
              else setSaveOpen(true)
            }}
          >
            {activeTemplateId != null ? '保存模板' : '另存为模板'}
          </Button>
          {activeTemplateId != null && (
            <Button
              danger
              icon={<DeleteOutlined />}
              loading={removeMutation.isPending}
              onClick={() => {
                const tpl = templates.find(t => t.id === activeTemplateId)
                modal.confirm({
                  title: `删除模板「${tpl?.name ?? ''}」？`,
                  onOk: () => removeMutation.mutate(activeTemplateId),
                })
              }}
            >
              删除
            </Button>
          )}
        </div>
      </div>

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
              setTableId(id)
              setResult(null)
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

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(420px, 1fr))', gap: 12 }}>
        {/* ── 计算模板 ── */}
        <Card
          size="small"
          title="自定义计算模板"
          extra={
            <Tooltip
              title={
                <div style={{ lineHeight: 1.9 }}>
                  [字段名] 引用字段值；支持 + - * / ( ) 与后缀 %；
                  单值函数：round(x, n) / abs / sqrt / pow(x, y) / ceil / floor；
                  整列聚合：sum([字段]) / avg / count / min / max；
                  例：round([合格数] / [实际产量] * 100, 2) 逐行算合格率
                </div>
              }
            >
              <Text type="secondary" style={{ fontSize: 12, cursor: 'help' }}>公式语法</Text>
            </Tooltip>
          }
        >
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {formulas.map((f, i) => (
              <div key={i} style={{ display: 'flex', gap: 6, alignItems: 'flex-start' }}>
                <Input
                  style={{ width: 110 }}
                  placeholder="键名"
                  value={f.key}
                  onChange={e => setFormulas(list => list.map((x, j) => (j === i ? { ...x, key: e.target.value } : x)))}
                />
                <Input
                  style={{ width: 110 }}
                  placeholder="展示名"
                  value={f.label}
                  onChange={e => setFormulas(list => list.map((x, j) => (j === i ? { ...x, label: e.target.value } : x)))}
                />
                <Input
                  data-testid={`analytics-formula-expr-${i}`}
                  placeholder="round([合格数] / [实际产量] * 100, 2)"
                  value={f.expr}
                  status={errors[f.key] ? 'error' : undefined}
                  onChange={e => setFormulas(list => list.map((x, j) => (j === i ? { ...x, expr: e.target.value } : x)))}
                />
                <Button
                  type="text"
                  danger
                  icon={<DeleteOutlined />}
                  aria-label="删除公式"
                  onClick={() =>
                    setFormulas(list => (list.length > 1 ? list.filter((_, j) => j !== i) : [newFormula(0)]))
                  }
                />
              </div>
            ))}
            {hasError && (
              <Alert
                type="error"
                showIcon
                data-testid="analytics-formula-error"
                message={Object.entries(errors).map(([k, v]) => `${k}：${v}`).join('；')}
              />
            )}
            <Button
              type="dashed"
              icon={<PlusOutlined />}
              onClick={() => setFormulas(list => [...list, newFormula(list.length)])}
            >
              添加公式
            </Button>
          </div>
        </Card>

        {/* ── 可视化配置 ── */}
        <Card size="small" title="可视化配置">
          <Space direction="vertical" style={{ width: '100%' }}>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              <Select
                data-testid="analytics-chart-type"
                style={{ width: 140 }}
                value={chart.type}
                options={CHART_TYPES}
                onChange={v => setChart(c => ({ ...c, type: v }))}
              />
              <Select
                data-testid="analytics-chart-x"
                style={{ width: 220 }}
                placeholder={chart.type === 'scatter' ? 'X 数值列' : '维度 / 分箱列（X 轴）'}
                value={chart.x ?? undefined}
                allowClear
                options={chartOptions}
                onChange={v => setChart(c => ({ ...c, x: v ?? null }))}
              />
              <Select
                data-testid="analytics-chart-y"
                style={{ width: 220 }}
                placeholder={chart.type === 'scatter' ? 'Y 数值列' : '指标（被聚合的列）'}
                value={chart.y ?? undefined}
                allowClear
                options={chartOptions}
                onChange={v => setChart(c => ({ ...c, y: v ?? null }))}
              />
            </div>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              <Select
                style={{ width: 220 }}
                placeholder="系列分组字段（柱状/折线可选）"
                value={chart.series ?? undefined}
                allowClear
                options={tableFields.map(n => ({ value: n, label: n }))}
                onChange={v => setChart(c => ({ ...c, series: v ?? null }))}
              />
              <Input
                data-testid="analytics-chart-title"
                style={{ width: 260 }}
                placeholder="图表标题（可选）"
                value={chart.title}
                onChange={e => setChart(c => ({ ...c, title: e.target.value }))}
              />
            </div>
            <Space>
              <Button
                type="primary"
                data-testid="analytics-run-btn"
                icon={<PlayCircleOutlined />}
                loading={computeMutation.isPending}
                disabled={!canRun}
                onClick={() => computeMutation.mutate()}
              >
                运行分析
              </Button>
              {!tableId && <Text type="secondary" style={{ fontSize: 12 }}>请先选择分析表</Text>}
              {!!tableId && validFormulas.length === 0 && (
                <Text type="secondary" style={{ fontSize: 12 }}>请至少填写一条公式</Text>
              )}
            </Space>
          </Space>
        </Card>
      </div>

      {/* ── 结果 ── */}
      {result ? (
        <>
          <Card
            size="small"
            title={chart.title || '可视化结果'}
            extra={
              <Text type="secondary" style={{ fontSize: 12 }}>
                共 {result.total} 行{result.truncated ? '（超出单次扫描上限，已截断）' : ''}
              </Text>
            }
          >
            {result.rows.length === 0 ? (
              <Empty description="该表暂无数据" />
            ) : (
              <ChartCard
                cfg={toChartConfig(chart)}
                rows={result.rows}
                fields={syntheticFields}
                total={result.total}
              />
            )}
          </Card>

          <Card size="small" title="描述统计（含派生指标）">
            <Table
              data-testid="analytics-stats-table"
              size="small"
              rowKey="key"
              pagination={false}
              scroll={{ x: 'max-content' }}
              dataSource={result.columns}
              columns={[
                {
                  title: '列',
                  dataIndex: 'key',
                  render: (_v, row) => (
                    <Space size={4}>
                      <span>{row.label || row.key}</span>
                      {row.kind === 'formula' && <Tag color="blue">公式</Tag>}
                    </Space>
                  ),
                },
                { title: '计数', dataIndex: 'count' },
                { title: '缺失', dataIndex: 'missing' },
                { title: '均值', dataIndex: 'mean', render: fmt },
                { title: '标准差', dataIndex: 'stdev', render: fmt },
                { title: '最小值', dataIndex: 'min', render: fmt },
                { title: 'P25', dataIndex: 'q1', render: fmt },
                { title: '中位数', dataIndex: 'median', render: fmt },
                { title: 'P75', dataIndex: 'q3', render: fmt },
                { title: '最大值', dataIndex: 'max', render: fmt },
                { title: '求和', dataIndex: 'sum', render: fmt },
              ]}
            />
          </Card>

          <Card size="small" title={`派生数据预览（前 ${PREVIEW_ROWS} 行）`}>
            <Table
              data-testid="analytics-rows-table"
              size="small"
              rowKey="id"
              pagination={false}
              scroll={{ x: 'max-content', y: 320 }}
              dataSource={result.rows.slice(0, PREVIEW_ROWS)}
              columns={[
                ...result.table_fields.map(name => ({ title: name, dataIndex: name, render: fmt })),
                ...validFormulas.map(f => ({
                  title: `${(f.label ?? '').trim() || f.key.trim()}（公式）`,
                  dataIndex: f.key.trim(),
                  render: fmt,
                })),
              ]}
            />
          </Card>
        </>
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
                      onClick={() => {
                        const tpl = templates[0]
                        loadTemplate(tpl)
                        message.info(`已加载示例模板「${tpl.name}」，点「运行分析」查看结果`)
                      }}
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

      {/* ── 另存为模板 ── */}
      <Modal
        title="另存为分析模板"
        open={saveOpen}
        onCancel={() => setSaveOpen(false)}
        onOk={() => {
          if (!templateName.trim()) {
            message.warning('请填写模板名称')
            return
          }
          saveMutation.mutate('create')
        }}
        confirmLoading={saveMutation.isPending}
      >
        <Space direction="vertical" style={{ width: '100%' }}>
          <Input
            data-testid="analytics-template-name"
            placeholder="模板名称"
            value={templateName}
            onChange={e => setTemplateName(e.target.value)}
          />
          <Input.TextArea
            rows={2}
            placeholder="说明（可选）"
            value={templateDesc}
            onChange={e => setTemplateDesc(e.target.value)}
          />
          <Text type="secondary" style={{ fontSize: 12 }}>
            模板保存到后端（含公式与图表配置），工作区成员均可加载；仅编辑者及以上可保存/删除。
          </Text>
        </Space>
      </Modal>
    </div>
  )
}
