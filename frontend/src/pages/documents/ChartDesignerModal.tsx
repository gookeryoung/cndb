/** 图表设计器弹窗（ADR 0048 C4 / D5，ADR 0052 D9）：按模板 schema 编辑数据与文案，实时预览.
 *
 * - 新建：从模板 default_config 起步，保存仍写图表素材库并回传实例（正文插入其定义副本）；
 * - 编辑正文块（`editBlock`）：以块内定义起步，保存只回传新定义，不写素材库、不查实例；
 * - 数据表按模板 schema 生成（行增删受 row_min/row_max 钳制，系列数受 series_min/max 钳制）；
 * - 实时预览走 POST /charts/render-preview（不落库），输入防抖 300ms；
 * - 保存走 POST，后端严格校验 400 时逐条回显；模板下线只读展示（边界 3）。
 */

import { useEffect, useMemo, useState } from 'react'
import {
  Alert,
  Button,
  Input,
  InputNumber,
  Modal,
  Skeleton,
  Space,
  Typography,
} from 'antd'
import { DeleteOutlined, PlusOutlined } from '@ant-design/icons'
import { useMutation, useQuery } from '@tanstack/react-query'
import { useDebouncedValue } from '@/hooks/useDebouncedValue'
import { useResponsive } from '@/hooks/useResponsive'
import { chartApi } from '@/api/charts'
import type { ChartInstance, ChartTemplateInfo } from '@/api/charts'
import { sanitizeSvg } from '@/components/Document/ChartEmbed'
import type { ChartBlockSpec } from '@/components/Document/chartBlock'

const { Text, Paragraph } = Typography

/** 设计目标：新建（模板 key）或编辑正文内嵌块（定义 + 出现序号） */
export type ChartDesignTarget =
  | { kind: 'create'; templateKey: string }
  | { kind: 'editBlock'; spec: ChartBlockSpec; occurrence: number }

/** 保存结果：新建返回素材库实例；编辑正文块返回替换用的定义 */
export type ChartDesignResult =
  | { kind: 'chart'; chart: ChartInstance }
  | { kind: 'block'; spec: ChartBlockSpec }

/** 行草稿：双轴模板（label/value/growth）或系列模板（label/values[]） */
type ChartDataRowDraft =
  | { label: string; value: number | null; growth: number | null }
  | { label: string; values: (number | null)[] }

/** config 草稿：与后端归一结构同形，前端全量编辑后整体提交 */
interface ChartConfigDraft {
  caption: Record<string, string>
  labels: Record<string, unknown>
  theme: { palette: string[]; paper: string }
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
  return {
    caption,
    labels: (obj.labels && typeof obj.labels === 'object' ? obj.labels : {}) as Record<string, unknown>,
    theme: {
      palette,
      paper: typeof themeRaw.paper === 'string' ? themeRaw.paper : '#FBFAF5',
    },
    data: actualCount !== undefined ? { actualCount, rows } : { rows },
  }
}

const isSeriesRow = (row: ChartDataRowDraft): row is { label: string; values: (number | null)[] } =>
  'values' in row

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

  const templateKey = target?.kind === 'create' ? target.templateKey : target?.spec.templateKey ?? null
  const template: ChartTemplateInfo | undefined = useMemo(
    () => templatesQuery.data?.templates.find(t => t.key === templateKey),
    [templatesQuery.data, templateKey],
  )
  /** 系列模板（堆叠 / 分组）行结构是 label + values[]；双轴是 label + value/growth */
  const isSeriesTemplate = (template?.series_max ?? 0) > 0

  const [title, setTitle] = useState('')
  const [config, setConfig] = useState<ChartConfigDraft | null>(null)
  const [saveError, setSaveError] = useState<string | null>(null)

  // 打开且模板就绪时初始化草稿：新建从 default_config 起步，编辑从实例 config 起步
  useEffect(() => {
    if (!open || !template || !templatesQuery.data) return
    const base = target?.kind === 'editBlock' ? target.spec.config : template.default_config
    setTitle(target?.kind === 'editBlock' ? target.spec.title : template.name)
    setConfig(toDraftConfig(base))
    setSaveError(null)
    // 依赖收敛到 templateKey 与清单数据：模板对象引用变化（重取）不重置编辑中的草稿
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, templateKey, templatesQuery.data, target])

  const updateRows = (rows: ChartDataRowDraft[]) =>
    setConfig(prev => (prev ? { ...prev, data: { ...prev.data, rows } } : prev))

  const updateRowField = (index: number, field: 'label' | 'value' | 'growth', v: string | number | null) =>
    setConfig(prev => {
      if (!prev) return prev
      const rows = prev.data.rows.map((row, i) => {
        if (i !== index || isSeriesRow(row)) return row
        if (field === 'label') return { ...row, label: String(v ?? '') }
        return { ...row, [field]: typeof v === 'number' ? v : null }
      })
      return { ...prev, data: { ...prev.data, rows } }
    })

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

  /** 添加一行：按模板行结构给空行（系列值补 0，避免保存校验失败） */
  const addRow = () => {
    if (!template || !config) return
    if (config.data.rows.length >= template.row_max) return
    const emptyRow: ChartDataRowDraft = isSeriesTemplate
      ? {
        label: '',
        values: new Array(Math.max(labelsSeries.length, template.series_min)).fill(0),
      }
      : { label: '', value: null, growth: null }
    updateRows([...config.data.rows, emptyRow])
  }

  const removeRow = (index: number) => {
    if (!template || !config) return
    if (config.data.rows.length <= template.row_min) return
    updateRows(config.data.rows.filter((_, i) => i !== index))
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

  const saveMut = useMutation({
    mutationFn: async (): Promise<ChartDesignResult> => {
      if (!template || !config) throw new Error('设计器未就绪')
      const payload = {
        title: title.trim() || template.name,
        template_key: template.key,
        config: config as unknown as Record<string, unknown>,
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
                    <Input
                      addonBefore="横轴单位"
                      value={seriesUnit}
                      onChange={e => setLabel('unitX', e.target.value)}
                      style={{ marginTop: 8, maxWidth: 280 }}
                      data-testid="chart-designer-unit-x"
                    />
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
                ) : (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      列：标签 / 主值（左轴）/ 次值（右轴，留空按主值自动推算）
                    </Text>
                    {rows.map((row, i) =>
                      !isSeriesRow(row) ? (
                        <div key={i} style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                          <Input
                            value={row.label}
                            onChange={e => updateRowField(i, 'label', e.target.value)}
                            placeholder="年份"
                            style={{ width: 110 }}
                            data-testid={`chart-designer-row-label-${i}`}
                          />
                          <InputNumber
                            value={row.value}
                            onChange={v => updateRowField(i, 'value', v)}
                            placeholder="主值"
                            style={{ width: 110 }}
                            data-testid={`chart-designer-row-value-${i}`}
                          />
                          <InputNumber
                            value={row.growth}
                            onChange={v => updateRowField(i, 'growth', v)}
                            placeholder="次值（可空）"
                            style={{ width: 120 }}
                            data-testid={`chart-designer-row-growth-${i}`}
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
