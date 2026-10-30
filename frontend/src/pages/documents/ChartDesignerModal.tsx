/** 图表设计器弹窗（ADR 0048 C4 / D5，ADR 0052 D9）：按模板 schema 编辑数据与文案，实时预览.
 *
 * - 新建：从模板 default_config 起步，保存仍写图表素材库并回传实例（正文插入其定义副本）；
 * - 编辑正文块（`editBlock`）：以块内定义起步，保存只回传新定义，不写素材库、不查实例；
 * - 数据表按模板 schema 生成（行增删受 row_min/row_max 钳制，系列数受 series_min/max 钳制），
 *   行结构按 row_kind 分派（需求卡片 0070）：dual-axis / series / value / xy；
 * - 数据一键导入（需求卡片 0070 C3）：粘贴 TSV / CSV（可含表头行）整表替换数据行；
 * - 样式实时编辑（需求卡片 0070 C3）：按模板 style_fields 生成开关表单，随预览防抖生效；
 * - 实时预览走 POST /charts/render-preview（不落库），输入防抖 300ms；
 * - 保存走 POST，后端严格校验 400 时逐条回显；模板下线只读展示（边界 3）。
 */

import { useEffect, useMemo, useState } from 'react'
import {
  Alert,
  Button,
  Checkbox,
  Input,
  InputNumber,
  Modal,
  Skeleton,
  Space,
  Tooltip,
  Typography,
} from 'antd'
import { DeleteOutlined, PlusOutlined } from '@ant-design/icons'
import { useMutation, useQuery } from '@tanstack/react-query'
import { useDebouncedValue } from '@/hooks/useDebouncedValue'
import { useResponsive } from '@/hooks/useResponsive'
import { useTheme } from '@/theme/ThemeProvider'
import { chartApi } from '@/api/charts'
import type { ChartInstance, ChartTemplateInfo } from '@/api/charts'
import { sanitizeSvg } from '@/components/Document/ChartEmbed'
import type { ChartBlockSpec } from '@/components/Document/chartBlock'
import { growthLinkedDisplay, linkGrowthFromValue, linkValueFromGrowth } from './chartLinkage'

const { Text, Paragraph } = Typography

/** 设计目标：新建（模板 key）或编辑正文内嵌块（定义 + 出现序号） */
export type ChartDesignTarget =
  | { kind: 'create'; templateKey: string }
  | { kind: 'editBlock'; spec: ChartBlockSpec; occurrence: number }

/** 保存结果：新建返回素材库实例；编辑正文块返回替换用的定义 */
export type ChartDesignResult =
  | { kind: 'chart'; chart: ChartInstance }
  | { kind: 'block'; spec: ChartBlockSpec }

/** 行草稿：双轴（label/value/growth）| 系列（label/values[]）| value（label/value）| xy（x/y） */
type ChartDataRowDraft =
  | { label: string; value: number | null; growth: number | null }
  | { label: string; values: (number | null)[] }
  | { x: number | null; y: number | null }

/** config 草稿：与后端归一结构同形，前端全量编辑后整体提交 */
interface ChartConfigDraft {
  caption: Record<string, string>
  labels: Record<string, unknown>
  theme: { palette: string[]; paper: string }
  /** 样式开关（需求卡片 0070 C3）；无样式模板无此节 */
  style?: Record<string, boolean>
  data: { actualCount?: number; rows: ChartDataRowDraft[] }
}

const CAPTION_FIELDS: { key: string; label: string }[] = [
  { key: 'no', label: '图号' },
  { key: 'context', label: '章节信息' },
  { key: 'title', label: '标题' },
  { key: 'subtitle', label: '副题' },
]

/** 防御性提取 config 草稿（旧实例 / 部分字段缺失时回退空值，编辑不崩） */
function toDraftRow(raw: unknown): ChartDataRowDraft {
  const r = (raw && typeof raw === 'object' ? raw : {}) as Record<string, unknown>
  if (Array.isArray(r.values)) {
    return {
      label: typeof r.label === 'string' ? r.label : '',
      values: r.values.map(v => (typeof v === 'number' && Number.isFinite(v) ? v : null)),
    }
  }
  const num = (v: unknown) => (typeof v === 'number' && Number.isFinite(v) ? v : null)
  if ('x' in r || 'y' in r) {
    return { x: num(r.x), y: num(r.y) }
  }
  return {
    label: typeof r.label === 'string' ? r.label : '',
    value: num(r.value),
    growth: num(r.growth),
  }
}

function toDraftConfig(raw: unknown): ChartConfigDraft {
  const obj = (raw && typeof raw === 'object' ? raw : {}) as Record<string, unknown>
  const captionRaw = (obj.caption && typeof obj.caption === 'object' ? obj.caption : {}) as Record<string, unknown>
  const caption: Record<string, string> = {}
  for (const { key } of [...CAPTION_FIELDS, { key: 'note', label: '' }]) {
    caption[key] = typeof captionRaw[key] === 'string' ? (captionRaw[key] as string) : ''
  }
  const themeRaw = (obj.theme && typeof obj.theme === 'object' ? obj.theme : {}) as Record<string, unknown>
  const palette = Array.isArray(themeRaw.palette)
    ? themeRaw.palette.filter((c): c is string => typeof c === 'string' && /^#[0-9A-Fa-f]{6}$/.test(c))
    : []
  const dataRaw = (obj.data && typeof obj.data === 'object' ? obj.data : {}) as Record<string, unknown>
  const actualCount = typeof dataRaw.actualCount === 'number' ? dataRaw.actualCount : undefined
  const rows = Array.isArray(dataRaw.rows) ? dataRaw.rows.map(toDraftRow) : []
  const styleRaw = (obj.style && typeof obj.style === 'object' ? obj.style : {}) as Record<string, unknown>
  const style: Record<string, boolean> = {}
  for (const [k, v] of Object.entries(styleRaw)) {
    if (typeof v === 'boolean') style[k] = v
  }
  return {
    caption,
    labels: (obj.labels && typeof obj.labels === 'object' ? obj.labels : {}) as Record<string, unknown>,
    theme: {
      palette,
      paper: typeof themeRaw.paper === 'string' ? themeRaw.paper : '#FBFAF5',
    },
    ...(Object.keys(style).length > 0 ? { style } : {}),
    data: actualCount !== undefined ? { actualCount, rows } : { rows },
  }
}

const isSeriesRow = (row: ChartDataRowDraft): row is { label: string; values: (number | null)[] } =>
  'values' in row

const isXyRow = (row: ChartDataRowDraft): row is { x: number | null; y: number | null } => 'x' in row

/** 标量行（dual-axis / value 共用形状）：label + value（+ growth，仅双轴展示） */
const isScalarRow = (
  row: ChartDataRowDraft,
): row is { label: string; value: number | null; growth: number | null } =>
  'label' in row && 'value' in row

// ── 数据一键导入（需求卡片 0070 C3）：粘贴 TSV / CSV 整表替换 ──

/** 数值单元格解析：容忍千分位 / 百分号 / 全角逗号 */
function parseImportNumber(cell: string): number | null {
  const cleaned = cell.replace(/[,，\s%]/g, '')
  if (cleaned === '' || cleaned === '-') return null
  const n = Number(cleaned)
  return Number.isFinite(n) ? n : null
}

/** 分行分列：Tab 优先，其次逗号，否则按空白切 */
function splitImportLines(text: string): string[][] {
  return text
    .split(/\r?\n/)
    .map(line => line.trim())
    .filter(Boolean)
    .map(line => {
      const cells = line.includes('\t')
        ? line.split('\t')
        : line.includes(',')
          ? line.split(',')
          : line.split(/\s+/)
      return cells.map(c => c.trim())
    })
}

/** 导入解析结果：rows 为替换用行草稿；seriesNames 为表头识别出的系列名（仅系列模板） */
interface ImportedData {
  rows: ChartDataRowDraft[]
  seriesNames?: string[]
}

/** 按模板行结构解析粘贴数据；无有效数据行返回 null */
function parseImportedRows(text: string, template: ChartTemplateInfo): ImportedData | null {
  const lines = splitImportLines(text)
  if (lines.length === 0) return null
  const clampMax = (rows: ChartDataRowDraft[]) => rows.slice(0, template.row_max)

  if (template.row_kind === 'series') {
    // 表头行判定：首行第 2 列起存在非数值单元格
    const first = lines[0]
    const hasHeader = first.length > 1 && first.slice(1).some(c => parseImportNumber(c) === null)
    const dataLines = hasHeader ? lines.slice(1) : lines
    const seriesNames = hasHeader ? first.slice(1).map(c => c.replace(/^["']|["']$/g, '')) : undefined
    const count = Math.max(
      seriesNames?.length ?? 0,
      ...dataLines.map(l => Math.max(l.length - 1, 0)),
      template.series_min,
    )
    const rows = dataLines.map(l => ({
      label: l[0] ?? '',
      values: Array.from({ length: count }, (_, j) => parseImportNumber(l[j + 1] ?? '')),
    }))
    if (rows.length === 0) return null
    return { rows: clampMax(rows), ...(seriesNames ? { seriesNames } : {}) }
  }
  if (template.row_kind === 'xy') {
    const hasHeader = parseImportNumber(lines[0][0] ?? '') === null
    const dataLines = (hasHeader ? lines.slice(1) : lines).filter(l => l.length >= 2)
    const rows = dataLines.map(l => ({ x: parseImportNumber(l[0] ?? ''), y: parseImportNumber(l[1] ?? '') }))
    if (rows.length === 0) return null
    return { rows: clampMax(rows) }
  }
  // value（label + value）与 dual-axis（label + value + 可选 growth）
  const hasHeader = lines[0].length > 1 && parseImportNumber(lines[0][1] ?? '') === null
  const dataLines = hasHeader ? lines.slice(1) : lines
  const rows = dataLines.map(l => ({
    label: l[0] ?? '',
    value: parseImportNumber(l[1] ?? ''),
    growth: template.row_kind === 'dual-axis' && l.length > 2 ? parseImportNumber(l[2] ?? '') : null,
  }))
  if (rows.length === 0) return null
  return { rows: clampMax(rows) }
}

/** 右侧实时预览：防抖后的 config 走 render-preview，SVG 内联（与正式渲染同源） */
function DesignerPreview({ workspaceId, templateKey, config, open }: {
  workspaceId: number
  templateKey: string | null
  config: ChartConfigDraft | null
  open: boolean
}) {
  const debounced = useDebouncedValue(config, 300)
  const configKey = useMemo(() => JSON.stringify(debounced), [debounced])
  const previewQuery = useQuery({
    queryKey: ['chart-designer-preview', workspaceId, templateKey, configKey],
    queryFn: () => chartApi.renderPreview(workspaceId, templateKey!, debounced as unknown as Record<string, unknown>),
    enabled: open && templateKey !== null && debounced !== null,
    retry: false,
    // 防抖窗口内保留上一版预览，避免闪烁
    placeholderData: prev => prev,
  })
  const svg = useMemo(
    () => (previewQuery.data ? sanitizeSvg(previewQuery.data) : ''),
    [previewQuery.data],
  )

  if (svg) {
    return (
      <div
        data-testid="chart-designer-preview-svg"
        style={{ border: '1px solid var(--cn-border, #eee)', borderRadius: 8, overflow: 'hidden', lineHeight: 0 }}
        dangerouslySetInnerHTML={{ __html: svg }}
      />
    )
  }
  if (previewQuery.isError) {
    return (
      <Alert
        type="warning"
        showIcon
        message="预览暂时不可用"
        description="当前输入渲染失败（数据可能不完整），修正后自动重试；不影响保存。"
        data-testid="chart-designer-preview-error"
      />
    )
  }
  return <Skeleton active paragraph={{ rows: 6 }} data-testid="chart-designer-preview-loading" />
}

export default function ChartDesignerModal({
  open,
  workspaceId,
  target,
  onCancel,
  onSaved,
}: {
  open: boolean
  workspaceId: number
  target: ChartDesignTarget | null
  onCancel: () => void
  /** 保存成功：页面关闭弹窗，新建插入定义副本 / 编辑替换目标块 */
  onSaved: (result: ChartDesignResult) => void
}) {
  const templatesQuery = useQuery({
    queryKey: ['chart-templates', workspaceId],
    queryFn: () => chartApi.templates(workspaceId),
    enabled: open,
    staleTime: 5 * 60 * 1000,
  })
  const { isMobile } = useResponsive()
  const { isDark } = useTheme()
  /** 联动计算值单元格高亮底色：随主题取色，深色下浅橙底会与浅色文字同化不可读 */
  const linkedCellBg = isDark ? 'rgba(250, 173, 20, 0.15)' : '#FDF2E4'

  const templateKey = target?.kind === 'create' ? target.templateKey : target?.spec.templateKey ?? null
  const template: ChartTemplateInfo | undefined = useMemo(
    () => templatesQuery.data?.templates.find(t => t.key === templateKey),
    [templatesQuery.data, templateKey],
  )
  /** 行结构分派（需求卡片 0070）：双轴 / 系列 / value / xy */
  const rowKind = template?.row_kind ?? 'series'
  const isSeriesTemplate = rowKind === 'series'
  const isDualAxisTemplate = rowKind === 'dual-axis'
  /** 旧系列模板（堆叠 / 分组）的横轴单位在数据区固定展示；新类型走 label_fields 声明 */
  const showSeriesUnitX =
    isSeriesTemplate &&
    typeof (template?.default_config.labels as Record<string, unknown> | undefined)?.unitX === 'string'

  const [title, setTitle] = useState('')
  const [config, setConfig] = useState<ChartConfigDraft | null>(null)
  const [saveError, setSaveError] = useState<string | null>(null)
  /** 受影响单元格（ADR 0056 C4）：联动重算产生的单元格键（`value:i` / `growth:i`），仅编辑期可见 */
  const [affected, setAffected] = useState<ReadonlySet<string>>(new Set())
  /** 联动单元格编辑态（ADR 0059 C3）：正在编辑的单元格键与草稿值；联动态非编辑时显示「数值(计算)」，点击后仅显示纯数值 */
  const [editingCell, setEditingCell] = useState<string | null>(null)
  const [cellDraft, setCellDraft] = useState<number | null>(null)
  /** 数据导入（需求卡片 0070 C3）：粘贴文本与解析错误 */
  const [importText, setImportText] = useState('')
  const [importError, setImportError] = useState<string | null>(null)

  // 打开且模板就绪时初始化草稿：新建从 default_config 起步，编辑从实例 config 起步
  useEffect(() => {
    if (!open || !template || !templatesQuery.data) return
    const base = target?.kind === 'editBlock' ? target.spec.config : template.default_config
    setTitle(target?.kind === 'editBlock' ? target.spec.title : template.name)
    setConfig(toDraftConfig(base))
    setSaveError(null)
    setAffected(new Set())
    setEditingCell(null)
    setCellDraft(null)
    setImportText('')
    setImportError(null)
    // 依赖收敛到 templateKey 与清单数据：模板对象引用变化（重取）不重置编辑中的草稿
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, templateKey, templatesQuery.data, target])

  const updateRows = (rows: ChartDataRowDraft[]) =>
    setConfig(prev => (prev ? { ...prev, data: { ...prev.data, rows } } : prev))

  /** 双轴联动编辑（ADR 0056 C3 / Q4）：填次值联动本行主值；改主值（i≥2）反向重算本行次值；
   * 联动结果登记为受影响单元格，手动编辑的单元格清除其标记（D3：不跨行级联）。
   * 标量行编辑（value 行结构的 label / value）复用本函数，联动仅对双轴模板生效 */
  const updateRowField = (index: number, field: 'label' | 'value' | 'growth', v: string | number | null) => {
    if (!config) return
    const rows: ChartDataRowDraft[] = config.data.rows.map((row, i) => {
      if (i !== index || isSeriesRow(row) || isXyRow(row)) return row
      if (field === 'label') return { ...row, label: String(v ?? '') }
      return { ...row, [field]: typeof v === 'number' ? v : null }
    })
    if (!isDualAxisTemplate) {
      setConfig({ ...config, data: { ...config.data, rows } })
      return
    }
    const nextAffected = new Set(affected)
    const row = config.data.rows[index]
    if (row && isScalarRow(row) && typeof v === 'number' && index > 0) {
      const prevRow = config.data.rows[index - 1]
      const prevValue = prevRow && isScalarRow(prevRow) ? prevRow.value : null
      if (field === 'growth') {
        const linked = linkValueFromGrowth(prevValue, v)
        if (linked !== null && isScalarRow(rows[index])) {
          rows[index] = { ...rows[index], value: linked }
          nextAffected.add(`value:${index}`)
        }
        nextAffected.delete(`growth:${index}`)
      } else if (field === 'value') {
        const linked = linkGrowthFromValue(v, prevValue)
        if (linked !== null && isScalarRow(rows[index])) {
          rows[index] = { ...rows[index], growth: linked }
          nextAffected.add(`growth:${index}`)
        }
        nextAffected.delete(`value:${index}`)
      } else {
        nextAffected.delete(`${field}:${index}`)
      }
    } else {
      nextAffected.delete(`${field}:${index}`)
    }
    setAffected(nextAffected)
    setConfig({ ...config, data: { ...config.data, rows } })
  }

  /** 联动单元格编辑提交（ADR 0059 C4 / Q1）：数值有实际改动才走联动写入，未改动失焦保持联动态 */
  const commitLinkedCell = (field: 'value' | 'growth', index: number, original: number | null) => {
    if (cellDraft !== original) updateRowField(index, field, cellDraft)
    setEditingCell(null)
    setCellDraft(null)
  }

  const updateSeriesRow = (index: number, field: 'label' | 'values', v: string | (number | null)[]) =>
    setConfig(prev => {
      if (!prev) return prev
      const rows = prev.data.rows.map((row, i) => {
        if (i !== index || !isSeriesRow(row)) return row
        if (field === 'label') return { ...row, label: String(v ?? '') }
        return { ...row, values: v as (number | null)[] }
      })
      return { ...prev, data: { ...prev.data, rows } }
    })

  /** xy 行编辑（散点图）：横 / 纵轴数值 */
  const updateXyRow = (index: number, field: 'x' | 'y', v: number | null) =>
    setConfig(prev => {
      if (!prev) return prev
      const rows = prev.data.rows.map((row, i) => (i === index && isXyRow(row) ? { ...row, [field]: v } : row))
      return { ...prev, data: { ...prev.data, rows } }
    })

  /** 添加一行：按模板行结构给空行（系列值补 0，避免保存校验失败） */
  const addRow = () => {
    if (!template || !config) return
    if (config.data.rows.length >= template.row_max) return
    const emptyRow: ChartDataRowDraft =
      rowKind === 'series'
        ? {
          label: '',
          values: new Array(Math.max(labelsSeries.length, template.series_min)).fill(0),
        }
        : rowKind === 'xy'
          ? { x: null, y: null }
          : { label: '', value: null, growth: null }
    updateRows([...config.data.rows, emptyRow])
  }

  const removeRow = (index: number) => {
    if (!template || !config) return
    if (config.data.rows.length <= template.row_min) return
    updateRows(config.data.rows.filter((_, i) => i !== index))
    // 行号整体位移，受影响标记失效即清空（ADR 0056 C4）
    setAffected(new Set())
    // 双轴分界随之钳制到剩余行数内
    setConfig(prev => {
      if (!prev || prev.data.actualCount === undefined) return prev
      return {
        ...prev,
        data: { ...prev.data, actualCount: Math.max(1, Math.min(prev.data.actualCount, prev.data.rows.length)) },
      }
    })
  }

  /** labels.series（系列模板）：名称数组；增删系列同步扩缩每行的 values */
  const labelsSeries = isSeriesTemplate
    ? ((config?.labels.series as string[] | undefined) ?? [])
    : []

  const setLabelsSeries = (names: string[]) =>
    setConfig(prev => {
      if (!prev) return prev
      const rows = prev.data.rows.map(row =>
        isSeriesRow(row) ? { ...row, values: names.map((_, i) => row.values[i] ?? 0) } : row,
      )
      return { ...prev, labels: { ...prev.labels, series: names }, data: { ...prev.data, rows } }
    })

  const addSeries = () => {
    if (!template || !config) return
    if (labelsSeries.length >= template.series_max) return
    setLabelsSeries([...labelsSeries, `系列${labelsSeries.length + 1}`])
  }

  const removeSeries = (index: number) => {
    if (!template || !config) return
    if (labelsSeries.length <= template.series_min) return
    setLabelsSeries(labelsSeries.filter((_, i) => i !== index))
  }

  const setCaption = (key: string, value: string) =>
    setConfig(prev => (prev ? { ...prev, caption: { ...prev.caption, [key]: value } } : prev))

  const setLabel = (key: string, value: string) =>
    setConfig(prev => (prev ? { ...prev, labels: { ...prev.labels, [key]: value } } : prev))

  const setActualCount = (value: number | null) =>
    setConfig(prev => {
      if (!prev) return prev
      const clamped = value === null ? undefined : Math.max(1, Math.min(value, prev.data.rows.length || 1))
      return { ...prev, data: { ...prev.data, actualCount: clamped } }
    })

  const setPaletteColor = (index: number, color: string) =>
    setConfig(prev => {
      if (!prev) return prev
      const palette = prev.theme.palette.map((c, i) => (i === index ? color : c))
      return { ...prev, theme: { ...prev.theme, palette } }
    })

  const setPaper = (color: string) =>
    setConfig(prev => (prev ? { ...prev, theme: { ...prev.theme, paper: color } } : prev))

  /** 样式开关（需求卡片 0070 C3）：草稿无值时回退模板默认 */
  const defaultStyle = useMemo(() => {
    const raw = (template?.default_config.style ?? {}) as Record<string, unknown>
    const out: Record<string, boolean> = {}
    for (const [k, v] of Object.entries(raw)) {
      if (typeof v === 'boolean') out[k] = v
    }
    return out
  }, [template])
  const styleFlag = (key: string): boolean => {
    const draft = config?.style?.[key]
    if (typeof draft === 'boolean') return draft
    const fallback = defaultStyle[key]
    return typeof fallback === 'boolean' ? fallback : false
  }
  const setStyleFlag = (key: string, value: boolean) =>
    setConfig(prev => (prev ? { ...prev, style: { ...defaultStyle, ...(prev.style ?? {}), [key]: value } } : prev))

  /** 数据一键导入（需求卡片 0070 C3）：按行结构解析粘贴数据，整表替换数据行 */
  const applyImport = () => {
    if (!template || !config) return
    const parsed = parseImportedRows(importText, template)
    if (!parsed) {
      setImportError('未识别到有效数据行：请确认数值列为数字（可从 Excel / WPS 直接粘贴）')
      return
    }
    setImportError(null)
    setAffected(new Set())
    setConfig(prev => {
      if (!prev) return prev
      const next: ChartConfigDraft = { ...prev, data: { ...prev.data, rows: parsed.rows } }
      if (parsed.seriesNames && parsed.seriesNames.length > 0) {
        next.labels = { ...prev.labels, series: parsed.seriesNames }
      }
      if (prev.data.actualCount !== undefined) {
        next.data.actualCount = Math.max(1, Math.min(prev.data.actualCount, parsed.rows.length))
      }
      return next
    })
  }

  const saveMut = useMutation({
    mutationFn: async (): Promise<ChartDesignResult> => {
      if (!template || !config) throw new Error('设计器未就绪')
      // 行草稿按行结构序列化：value 行剔除 growth、xy 行只留 x/y，保存的 config 与模板 schema 同形
      const serializeRow = (row: ChartDataRowDraft): Record<string, unknown> => {
        if (isSeriesRow(row)) return { label: row.label, values: row.values }
        if (isXyRow(row)) return { x: row.x, y: row.y }
        if (rowKind === 'value') return { label: row.label, value: row.value }
        return { label: row.label, value: row.value, growth: row.growth }
      }
      const configPayload = {
        ...config,
        data: { ...config.data, rows: config.data.rows.map(serializeRow) },
      } as unknown as Record<string, unknown>
      const payload = {
        title: title.trim() || template.name,
        template_key: template.key,
        config: configPayload,
      }
      if (target?.kind === 'editBlock') {
        // 编辑正文块：只回传新定义，不写素材库（ADR 0052 D9）
        return {
          kind: 'block',
          spec: {
            ...target.spec,
            title: payload.title,
            templateKey: template.key,
            config: payload.config,
          },
        }
      }
      const chart = await chartApi.create(workspaceId, payload)
      return { kind: 'chart', chart }
    },
    onSuccess: result => {
      setSaveError(null)
      onSaved(result)
    },
    onError: (err: unknown) => {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setSaveError(detail ?? '保存失败，请稍后重试')
    },
  })

  const rows = config?.data.rows ?? []
  const canAddRow = template !== undefined && config !== null && rows.length < template.row_max
  const canRemoveRow = template !== undefined && config !== null && rows.length > template.row_min
  const canAddSeries = template !== undefined && labelsSeries.length < template.series_max
  const canRemoveSeries = template !== undefined && labelsSeries.length > template.series_min

  const labelFields = template?.label_fields ?? []
  const seriesUnit = isSeriesTemplate ? String(config?.labels.unitX ?? '') : ''

  return (
    <Modal
      title={target?.kind === 'editBlock' ? '编辑图表' : '设计图表'}
      open={open}
      onCancel={onCancel}
      width={1200}
      style={{ maxWidth: 'calc(100vw - 24px)' }}
      destroyOnHidden
      footer={[
        <Button key="cancel" onClick={onCancel}>取消</Button>,
        <Button
          key="save"
          type="primary"
          loading={saveMut.isPending}
          disabled={!template || !config}
          data-testid="chart-designer-save"
          onClick={() => saveMut.mutate()}
        >
          {target?.kind === 'editBlock' ? '保存修改' : '保存并插入'}
        </Button>,
      ]}
    >
      {open && !template && templatesQuery.isSuccess && (
        <Alert
          type="warning"
          showIcon
          message="模板已下线"
          description="该图表使用的模板已不存在，仅可查看；可在文档中删除引用。"
          data-testid="chart-designer-template-missing"
        />
      )}
      {open && !template && templatesQuery.isLoading && <Skeleton active paragraph={{ rows: 6 }} />}

      {template && config && (
        <div
          data-testid="chart-designer-body"
          style={{
            display: 'flex',
            flexDirection: isMobile ? 'column' : 'row',
            gap: 16,
            alignItems: 'stretch',
          }}
        >
          {/* 左列：标题 + 数据 + 文案 + 配色 */}
          <div
            style={{
              flex: isMobile ? 'none' : '1 1 44%',
              minWidth: 0,
              maxHeight: isMobile ? '40vh' : '62vh',
              overflowY: 'auto',
              paddingRight: 4,
            }}
          >
            <Space direction="vertical" size={16} style={{ width: '100%' }}>
              <div>
                <Text strong style={{ display: 'block', marginBottom: 4 }}>图表名称</Text>
                <Input
                  value={title}
                  onChange={e => setTitle(e.target.value)}
                  placeholder="实例名称（列表与插入弹窗展示）"
                  data-testid="chart-designer-title"
                  maxLength={255}
                />
              </div>

              <div>
                <Text strong style={{ display: 'block', marginBottom: 4 }}>图题信息</Text>
                <Space direction="vertical" size={4} style={{ width: '100%' }}>
                  {CAPTION_FIELDS.map(f => (
                    <Input
                      key={f.key}
                      addonBefore={f.label}
                      value={config.caption[f.key] ?? ''}
                      onChange={e => setCaption(f.key, e.target.value)}
                      placeholder={f.key === 'title' ? '（必填，渲染在图头）' : '可选'}
                      data-testid={`chart-designer-caption-${f.key}`}
                    />
                  ))}
                  <Text type="secondary" style={{ fontSize: 12 }}>图注</Text>
                  <Input.TextArea
                    value={config.caption.note ?? ''}
                    onChange={e => setCaption('note', e.target.value)}
                    placeholder="支持 {cagr} 等动态标记（随模板自动计算）"
                    autoSize={{ minRows: 2, maxRows: 4 }}
                    data-testid="chart-designer-caption-note"
                  />
                </Space>
              </div>

              <div>
                <Text strong style={{ display: 'block', marginBottom: 4 }}>
                  数据
                  <Text type="secondary" style={{ fontWeight: 'normal', marginLeft: 8, fontSize: 12 }}>
                    {template.row_min}–{template.row_max} 行
                  </Text>
                </Text>

                {/* 数据一键导入（需求卡片 0070 C3）：粘贴 TSV / CSV 整表替换 */}
                <div style={{ marginBottom: 8 }}>
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    导入数据（粘贴表格数据，可含表头行，一键替换下方数据行）
                  </Text>
                  <Input.TextArea
                    value={importText}
                    onChange={e => setImportText(e.target.value)}
                    placeholder={
                      rowKind === 'xy'
                        ? '横轴值 纵轴值（每行一个点，Tab / 逗号 / 空格分隔）'
                        : rowKind === 'series'
                          ? '行标签 系列值…（每行一条数据，首行可为系列名表头）'
                          : '名称 数值（每行一条数据）'
                    }
                    autoSize={{ minRows: 2, maxRows: 4 }}
                    style={{ marginTop: 4 }}
                    data-testid="chart-designer-import-text"
                  />
                  <Space style={{ marginTop: 4 }}>
                    <Button
                      size="small"
                      disabled={!importText.trim()}
                      onClick={applyImport}
                      data-testid="chart-designer-import-apply"
                    >
                      导入数据
                    </Button>
                    {importError && (
                      <Text type="danger" style={{ fontSize: 12 }} data-testid="chart-designer-import-error">
                        {importError}
                      </Text>
                    )}
                  </Space>
                </div>

                {isSeriesTemplate && (
                  <div style={{ marginBottom: 8 }}>
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      系列（{template.series_min}–{template.series_max} 个）
                    </Text>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 4 }}>
                      {labelsSeries.map((name, i) => (
                        <Space.Compact key={i}>
                          <Input
                            value={name}
                            onChange={e => {
                              const next = [...labelsSeries]
                              next[i] = e.target.value
                              setLabelsSeries(next)
                            }}
                            style={{ width: 110 }}
                            data-testid={`chart-designer-series-name-${i}`}
                          />
                          <Button
                            icon={<DeleteOutlined />}
                            disabled={!canRemoveSeries}
                            onClick={() => removeSeries(i)}
                          />
                        </Space.Compact>
                      ))}
                      <Button icon={<PlusOutlined />} disabled={!canAddSeries} onClick={addSeries}>
                        加系列
                      </Button>
                    </div>
                    {showSeriesUnitX && (
                      <Input
                        addonBefore="横轴单位"
                        value={seriesUnit}
                        onChange={e => setLabel('unitX', e.target.value)}
                        style={{ marginTop: 8, maxWidth: 280 }}
                        data-testid="chart-designer-unit-x"
                      />
                    )}
                  </div>
                )}

                {isSeriesTemplate ? (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                    {rows.map((row, i) =>
                      isSeriesRow(row) ? (
                        <div key={i} style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                          <Input
                            value={row.label}
                            onChange={e => updateSeriesRow(i, 'label', e.target.value)}
                            placeholder="行标签"
                            style={{ width: 130 }}
                            data-testid={`chart-designer-row-label-${i}`}
                          />
                          {row.values.map((v, j) => (
                            <InputNumber
                              key={j}
                              value={v}
                              onChange={val => updateSeriesRow(i, 'values', row.values.map((x, k) => (k === j ? val : x)))}
                              style={{ width: 90 }}
                              data-testid={`chart-designer-row-value-${i}-${j}`}
                            />
                          ))}
                          <Button
                            type="text"
                            danger
                            icon={<DeleteOutlined />}
                            disabled={!canRemoveRow}
                            onClick={() => removeRow(i)}
                          />
                        </div>
                      ) : null,
                    )}
                  </div>
                ) : isDualAxisTemplate ? (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      列：标签 / 主值（左轴）/ 次值（右轴，留空按主值推算显示为「(计算)」，点击可编辑；填写后本行主值联动变动）
                    </Text>
                    {rows.map((row, i) =>
                      isScalarRow(row) ? (() => {
                        // 联动态判定（ADR 0059 D5）：默认联动态（次值留空且可推算）+ 本轮联动重算（affected 集合）
                        const prevCandidate = i > 0 ? rows[i - 1] : undefined
                        const prevRow = prevCandidate && isScalarRow(prevCandidate) ? prevCandidate : undefined
                        const prevValue = prevRow ? (prevRow.value ?? null) : null
                        const gDisp = growthLinkedDisplay(row.growth ?? null, row.value ?? null, prevValue)
                        const growthLinked = i > 0 && (affected.has(`growth:${i}`) || gDisp.linked)
                        const growthShow = (row.growth ?? gDisp.display) ?? null
                        const valueLinked = affected.has(`value:${i}`)
                        const growthEditing = editingCell === `growth:${i}`
                        const valueEditing = editingCell === `value:${i}`
                        return (
                          <div key={i} style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                            <Input
                              value={row.label}
                              onChange={e => updateRowField(i, 'label', e.target.value)}
                              placeholder="年份"
                              style={{ width: 110 }}
                              data-testid={`chart-designer-row-label-${i}`}
                            />
                            <Tooltip title={valueLinked && !valueEditing ? '由次值联动重算' : undefined}>
                              {valueLinked && !valueEditing ? (
                                <Input
                                  readOnly
                                  value={`${row.value ?? ''}(计算)`}
                                  onClick={() => {
                                    setCellDraft(row.value ?? null)
                                    setEditingCell(`value:${i}`)
                                  }}
                                  style={{ width: 110, background: linkedCellBg, cursor: 'text' }}
                                  data-linked=""
                                  data-testid={`chart-designer-row-value-${i}`}
                                />
                              ) : (
                                <InputNumber
                                  {...(valueEditing
                                    ? {
                                        autoFocus: true,
                                        value: cellDraft,
                                        onChange: v => setCellDraft(typeof v === 'number' ? v : null),
                                        onBlur: () => commitLinkedCell('value', i, row.value ?? null),
                                        onPressEnter: () => commitLinkedCell('value', i, row.value ?? null),
                                      }
                                    : { value: row.value, onChange: v => updateRowField(i, 'value', v) })}
                                  placeholder="主值"
                                  style={{ width: 110 }}
                                  data-testid={`chart-designer-row-value-${i}`}
                                />
                              )}
                            </Tooltip>
                            <Tooltip
                              title={
                                i === 0
                                  ? '第 1 行无上年基数，次值不可填写'
                                  : growthLinked && !growthEditing
                                    ? affected.has(`growth:${i}`)
                                      ? '由主值联动重算'
                                      : '留空按主值推算'
                                    : undefined
                              }
                            >
                              {growthLinked && !growthEditing ? (
                                <Input
                                  readOnly
                                  value={`${growthShow ?? ''}(计算)`}
                                  onClick={() => {
                                    setCellDraft(growthShow)
                                    setEditingCell(`growth:${i}`)
                                  }}
                                  style={{ width: 120, background: linkedCellBg, cursor: 'text' }}
                                  data-linked=""
                                  data-testid={`chart-designer-row-growth-${i}`}
                                />
                              ) : (
                                <InputNumber
                                  {...(growthEditing
                                    ? {
                                        autoFocus: true,
                                        value: cellDraft,
                                        onChange: v => setCellDraft(typeof v === 'number' ? v : null),
                                        onBlur: () => commitLinkedCell('growth', i, growthShow),
                                        onPressEnter: () => commitLinkedCell('growth', i, growthShow),
                                      }
                                    : { value: row.growth, onChange: v => updateRowField(i, 'growth', v) })}
                                  placeholder="次值（可空）"
                                  disabled={i === 0}
                                  style={{ width: 120 }}
                                  data-testid={`chart-designer-row-growth-${i}`}
                                />
                              )}
                            </Tooltip>
                            <Button
                              type="text"
                              danger
                              icon={<DeleteOutlined />}
                              disabled={!canRemoveRow}
                              onClick={() => removeRow(i)}
                            />
                          </div>
                        )
                      })() : null,
                    )}
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <Text type="secondary" style={{ fontSize: 12 }}>实际值年份数（规划期分界）</Text>
                      <InputNumber
                        min={1}
                        max={Math.max(rows.length, 1)}
                        value={config.data.actualCount ?? null}
                        onChange={setActualCount}
                        style={{ width: 80 }}
                        data-testid="chart-designer-actual-count"
                      />
                    </div>
                  </div>
                ) : rowKind === 'xy' ? (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      列：横轴值 / 纵轴值（散点，每行一个点）
                    </Text>
                    {rows.map((row, i) =>
                      isXyRow(row) ? (
                        <div key={i} style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                          <InputNumber
                            value={row.x}
                            onChange={v => updateXyRow(i, 'x', typeof v === 'number' ? v : null)}
                            placeholder="横轴值"
                            style={{ width: 140 }}
                            data-testid={`chart-designer-row-x-${i}`}
                          />
                          <InputNumber
                            value={row.y}
                            onChange={v => updateXyRow(i, 'y', typeof v === 'number' ? v : null)}
                            placeholder="纵轴值"
                            style={{ width: 140 }}
                            data-testid={`chart-designer-row-y-${i}`}
                          />
                          <Button
                            type="text"
                            danger
                            icon={<DeleteOutlined />}
                            disabled={!canRemoveRow}
                            onClick={() => removeRow(i)}
                          />
                        </div>
                      ) : null,
                    )}
                  </div>
                ) : (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      列：名称 / 数值
                    </Text>
                    {rows.map((row, i) =>
                      isScalarRow(row) ? (
                        <div key={i} style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                          <Input
                            value={row.label}
                            onChange={e => updateRowField(i, 'label', e.target.value)}
                            placeholder="名称"
                            style={{ width: 150 }}
                            data-testid={`chart-designer-row-label-${i}`}
                          />
                          <InputNumber
                            value={row.value}
                            onChange={v => updateRowField(i, 'value', v)}
                            placeholder="数值"
                            style={{ width: 140 }}
                            data-testid={`chart-designer-row-value-${i}`}
                          />
                          <Button
                            type="text"
                            danger
                            icon={<DeleteOutlined />}
                            disabled={!canRemoveRow}
                            onClick={() => removeRow(i)}
                          />
                        </div>
                      ) : null,
                    )}
                  </div>
                )}
                <Button
                  icon={<PlusOutlined />}
                  size="small"
                  disabled={!canAddRow}
                  onClick={addRow}
                  style={{ marginTop: 8 }}
                  data-testid="chart-designer-add-row"
                >
                  添加一行
                </Button>
              </div>

              {labelFields.length > 0 && (
                <div>
                  <Text strong style={{ display: 'block', marginBottom: 4 }}>图例与文案</Text>
                  <Space direction="vertical" size={4} style={{ width: '100%' }}>
                    {labelFields.map(f => (
                      <Input
                        key={f.key}
                        addonBefore={f.label}
                        value={String(config.labels[f.key] ?? '')}
                        onChange={e => setLabel(f.key, e.target.value)}
                        data-testid={`chart-designer-label-${f.key}`}
                      />
                    ))}
                  </Space>
                </div>
              )}

              {(template.style_fields ?? []).length > 0 && (
                <div>
                  <Text strong style={{ display: 'block', marginBottom: 4 }}>样式</Text>
                  <Space direction="vertical" size={4}>
                    {(template.style_fields ?? []).map(f => (
                      <Checkbox
                        key={f.key}
                        checked={styleFlag(f.key)}
                        onChange={e => setStyleFlag(f.key, e.target.checked)}
                        data-testid={`chart-designer-style-${f.key}`}
                      >
                        {f.label}
                      </Checkbox>
                    ))}
                  </Space>
                </div>
              )}

              <div>
                <Text strong style={{ display: 'block', marginBottom: 4 }}>配色</Text>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center' }}>
                  {config.theme.palette.map((color, i) => (
                    <input
                      key={i}
                      type="color"
                      value={color}
                      onChange={e => setPaletteColor(i, e.target.value)}
                      style={{ width: 36, height: 28, border: '1px solid var(--cn-border, #ddd)', borderRadius: 4, padding: 0 }}
                      data-testid={`chart-designer-palette-${i}`}
                      aria-label={`调色板颜色 ${i + 1}`}
                    />
                  ))}
                  <Text type="secondary" style={{ fontSize: 12 }}>纸底</Text>
                  <input
                    type="color"
                    value={config.theme.paper}
                    onChange={e => setPaper(e.target.value)}
                    style={{ width: 36, height: 28, border: '1px solid var(--cn-border, #ddd)', borderRadius: 4, padding: 0 }}
                    data-testid="chart-designer-paper"
                    aria-label="纸底颜色"
                  />
                </div>
              </div>
            </Space>
          </div>

          {/* 右列：实时预览（300ms 防抖，与正式渲染同源）；预览列占比 ≥ 55%（ADR 0051） */}
          <div
            data-testid="chart-designer-preview"
            style={{
              flex: isMobile ? 'none' : '1 1 56%',
              minWidth: 0,
              width: isMobile ? '100%' : undefined,
            }}
          >
            <Paragraph type="secondary" style={{ fontSize: 12, marginBottom: 8 }}>
              实时预览（输入停顿 0.3 秒后刷新）
            </Paragraph>
            <DesignerPreview
              workspaceId={workspaceId}
              templateKey={template.key}
              config={config}
              open={open}
            />
          </div>
        </div>
      )}

      {saveError && (
        <Alert
          type="error"
          showIcon
          closable
          onClose={() => setSaveError(null)}
          message="保存失败"
          description={<Paragraph style={{ whiteSpace: 'pre-wrap', marginBottom: 0 }}>{saveError}</Paragraph>}
          style={{ marginTop: 12 }}
          data-testid="chart-designer-save-error"
        />
      )}
    </Modal>
  )
}
