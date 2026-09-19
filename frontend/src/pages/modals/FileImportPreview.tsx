/** 文件导入预览 Modal —— 左右分栏（flex 等高布局）.
 *
 * 左侧：识别到的字段列表，可调整 field_type；
 * 右侧：典型数据表（sample_rows），当用户调整左侧字段类型时，
 *       右侧对应列的值以"原始 → 转换后"形式实时展示。
 *
 * 布局策略（避免左右高度错位）：
 * - Modal body 为 flex-col，max-height = calc(100vh - 160px)，整体在视口内滚动受控；
 * - 主体为 flex-row，两栏共享同一父高度 → 天然等高；
 * - 每栏内部 flex-col：标题 flex-shrink:0（永远可见），内容 flex:1 min-height:0（滚动）；
 * - 左栏字段列表 flex:1 滚动，select 选项编辑区贴底；
 * - 右栏统计栏 + Table 容器 flex:1 滚动，antd Table 通过 CSS 撑满剩余空间。
 *
 * 支持的交互：
 * - 改变字段类型（下拉）
 * - select 类型可编辑 options（自动填充推测值，可增删）
 * - 数值/日期/boolean 等类型在右侧显示转换结果与失败警示
 */

import { useCallback, useMemo, useState, useEffect } from 'react'
import { Modal, Input, Table, Select, Tag, Progress, Button, Empty, Tooltip, Popover, message } from 'antd'
import type { TableProps } from 'antd'
import { FileTextOutlined, SwapOutlined, WarningOutlined, PlusOutlined, ExclamationCircleOutlined, CheckOutlined, InfoCircleOutlined } from '@ant-design/icons'
import { importApi } from '@/api'
import type { FileAnalyzeResult, FileImportResult } from '@/api'
import { PREVIEW_FIELD_TYPE_VALUES, FIELD_TYPE_META, getFieldTypeColor, getFieldTypeLabel } from '@/utils/fieldTypeMeta'

/** antd Table 在 flex 容器中自适应高度所需的全局样式（仅注入一次）. */
function useTableFlexFillStyle() {
  useEffect(() => {
    const id = '__import_preview_table_flex__'
    if (document.getElementById(id)) return
    const style = document.createElement('style')
    style.id = id
    style.textContent = `
      .import-preview-table-wrapper { flex: 1; min-height: 0; overflow: hidden; display: flex; flex-direction: column; }
      .import-preview-table-wrapper .ant-table { flex: 1; min-height: 0; display: flex; flex-direction: column; background: transparent; }
      .import-preview-table-wrapper .ant-table-container { flex: 1; min-height: 0; display: flex; flex-direction: column; }
      .import-preview-table-wrapper .ant-table-content { flex: 1; min-height: 0; overflow: hidden; }
      .import-preview-table-wrapper .ant-table-body { overflow-y: auto !important; flex: 1; min-height: 0; }
      .import-preview-table-wrapper .ant-table-placeholder { height: auto !important; }
    `
    document.head.appendChild(style)
    return () => { /* 保留样式供其他实例复用 */ }
  }, [])
}

/** 类型下拉选项：由共享字段类型元数据生成（纯中文标签，value 保持后端英文类型不变） */
const PREVIEW_TYPE_OPTIONS = PREVIEW_FIELD_TYPE_VALUES.map(v => ({
  value: v,
  label: FIELD_TYPE_META[v]?.label ?? v,
}))

/** 列分析项（后端 analyze 返回） */
interface AnalyzeColumn {
  name: string
  field_type: string
  sample_values?: string[]
  null_ratio?: number
  options?: string[]
}

/** 用户编辑的覆盖项 —— 与后端 column_overrides 同结构 */
interface ColumnOverride {
  field_type: string
  options?: string[]
}

/** 单个单元格转换结果 */
interface CellTransform {
  /** 原始显示文本 */
  rawText: string
  /** 转换后显示文本（失败则为 null） */
  convertedText: string | null
  /** 是否转换失败 */
  failed: boolean
}

interface Props {
  open: boolean
  wid: number | string
  file: File | null
  /** analyze 结果（来自 importApi.analyzeFile） */
  analyzeResult: FileAnalyzeResult | null
  onClose: () => void
  onSuccess?: (result: FileImportResult) => void
}

/** 判断原始值能否转为目标类型 —— 返回转换后的字符串或 null（失败） */
function tryConvert(raw: unknown, targetType: string): CellTransform {
  const rawText = raw == null ? '' : String(raw)
  const stripped = rawText.trim()
  if (!stripped) return { rawText, convertedText: '', failed: false }

  switch (targetType) {
    case 'text':
    case 'longtext':
      return { rawText, convertedText: stripped, failed: false }

    case 'number': {
      const s = stripped.replace(/[,%¥$￥]/g, '').replace(/,/g, '')
      const n = Number(s)
      if (!Number.isFinite(n) || !Number.isInteger(n)) return { rawText, convertedText: null, failed: true }
      return { rawText, convertedText: String(n), failed: false }
    }
    case 'float': {
      const s = stripped.replace(/[¥$￥]/g, '').replace(/,/g, '')
      const n = Number(s)
      if (!Number.isFinite(n)) return { rawText, convertedText: null, failed: true }
      return { rawText, convertedText: String(n), failed: false }
    }
    case 'percentage': {
      const hasPct = stripped.endsWith('%')
      const s = hasPct ? stripped.slice(0, -1).trim() : stripped
      const n = Number(s.replace(/,/g, ''))
      if (!Number.isFinite(n)) return { rawText, convertedText: null, failed: true }
      return { rawText, convertedText: hasPct ? `${n}%` : `${n}%`, failed: false }
    }
    case 'boolean': {
      const low = stripped.toLowerCase()
      const truthy = new Set(['true', 'yes', 'y', '1', 'on', '是'])
      const falsy = new Set(['false', 'no', 'n', '0', 'off', '否'])
      if (truthy.has(low)) return { rawText, convertedText: 'true', failed: false }
      if (falsy.has(low)) return { rawText, convertedText: 'false', failed: false }
      // 数值 1/0 也接受
      if (stripped === '1') return { rawText, convertedText: 'true', failed: false }
      if (stripped === '0') return { rawText, convertedText: 'false', failed: false }
      return { rawText, convertedText: null, failed: true }
    }
    case 'date':
    case 'datetime': {
      // ISO / CN / 通用日期
      const d = tryParseDate(stripped)
      if (!d) return { rawText, convertedText: null, failed: true }
      if (targetType === 'date') return { rawText, convertedText: d.toISOString().slice(0, 10), failed: false }
      return { rawText, convertedText: d.toISOString().slice(0, 19).replace('T', ' '), failed: false }
    }
    case 'select':
    case 'multiselect':
      return { rawText, convertedText: stripped, failed: false }
    case 'email':
      return { rawText, convertedText: stripped, failed: false }
    case 'url':
      return { rawText, convertedText: stripped, failed: false }
    case 'phone':
      return { rawText, convertedText: stripped, failed: false }
    default:
      return { rawText, convertedText: stripped, failed: false }
  }
}

/** 尝试解析日期字符串 —— 覆盖常见格式. */
function tryParseDate(s: string): Date | null {
  // ISO 8601
  let d = new Date(s)
  if (!Number.isNaN(d.getTime())) return d
  // 中文日期 2024/01/05 或 2024-01-05 或 2024.01.05
  const cn1 = s.match(/^(\d{4})[/\-.](\d{1,2})[/\-.](\d{1,2})$/)
  if (cn1) {
    d = new Date(Number(cn1[1]), Number(cn1[2]) - 1, Number(cn1[3]))
    if (!Number.isNaN(d.getTime())) return d
  }
  // 带时间 2024-01-05 12:34:56
  const cn2 = s.match(/^(\d{4})[/\-.](\d{1,2})[/\-.](\d{1,2})[\sT]+(\d{1,2}):(\d{1,2})(?::(\d{1,2}))?$/)
  if (cn2) {
    d = new Date(Number(cn2[1]), Number(cn2[2]) - 1, Number(cn2[3]), Number(cn2[4]), Number(cn2[5]), Number(cn2[6] || 0))
    if (!Number.isNaN(d.getTime())) return d
  }
  return null
}

/** 从多批 sample_rows 中提取原始唯一值 —— 作为 select 默认 options. */
function collectUniqueValues(rows: Array<Record<string, unknown>>, colName: string): string[] {
  const seen = new Set<string>()
  const out: string[] = []
  for (const r of rows) {
    const v = r[colName]
    if (v == null) continue
    const s = String(v).trim()
    if (!s) continue
    if (!seen.has(s)) {
      seen.add(s)
      out.push(s)
    }
    if (out.length >= 200) break
  }
  return out
}

export default function FileImportPreview({ open, wid, file, analyzeResult, onClose, onSuccess }: Props) {
  const [overrides, setOverrides] = useState<Record<string, ColumnOverride>>({})
  const [tableName, setTableName] = useState('')
  const [creating, setCreating] = useState(false)
  const [selectedField, setSelectedField] = useState<string | null>(null)

  // 重置内部状态（open 变化时）
  useMemo(() => {
    if (open && analyzeResult) {
      setOverrides({})
      // 默认表名 = 文件名去扩展名
      const fn = analyzeResult.filename || ''
      const name = fn.replace(/\.[^.]+$/, '') || '导入数据表'
      setTableName(name)
      // 默认选中第一个列
      const firstCol = analyzeResult.columns.find(c => c.name.trim())
      setSelectedField(firstCol?.name ?? null)
    }
  }, [open, analyzeResult])

  /** 当前生效的列定义 = 后端原始 + 用户 overrides. */
  const effectiveColumns: AnalyzeColumn[] = useMemo(() => {
    if (!analyzeResult) return []
    return analyzeResult.columns.map(col => {
      const ov = overrides[col.name]
      if (!ov) return col
      return {
        ...col,
        field_type: ov.field_type,
        options: ov.options ?? col.options,
      }
    })
  }, [analyzeResult, overrides])

  const sampleRows = useMemo(() => analyzeResult?.sample_rows ?? [], [analyzeResult])

  /** 某列的类型转换失败计数 —— 用于左侧字段卡片上的警示. */
  const columnFailCounts = useMemo(() => {
    const res: Record<string, number> = {}
    if (!analyzeResult) return res
    for (const col of effectiveColumns) {
      let fail = 0
      for (const row of sampleRows) {
        const t = tryConvert(row[col.name], col.field_type)
        if (t.failed) fail++
      }
      res[col.name] = fail
    }
    return res
  }, [effectiveColumns, sampleRows, analyzeResult])

  /** 判断 override 是否与后端原始完全一致 —— 一致则应清除. */
  const isOverrideRedundant = useCallback((colName: string, ov: ColumnOverride): boolean => {
    const original = analyzeResult?.columns.find(c => c.name === colName)
    if (!original) return false
    if (ov.field_type !== original.field_type) return false
    // 非 select 类型，options 总是 undefined，与原始的空数组/undefined 视为一致
    if (ov.field_type !== 'select' && ov.field_type !== 'multiselect') {
      return true
    }
    // select/multiselect 比较 options 内容
    const origOpts = original.options ?? []
    const ovOpts = ov.options ?? []
    return JSON.stringify([...origOpts].sort()) === JSON.stringify([...ovOpts].sort())
  }, [analyzeResult])

  /** 改变字段类型 —— 自动填 options 如果是 select. */
  const changeFieldType = useCallback((colName: string, newType: string) => {
    setOverrides(prev => {
      const baseCol = analyzeResult?.columns.find(c => c.name === colName)
      const prevOv = prev[colName]
      const base: ColumnOverride = prevOv ?? {
        field_type: baseCol?.field_type ?? 'text',
        options: baseCol?.options ?? [],
      }
      const next: ColumnOverride = { ...base, field_type: newType }
      // 切到 select/multiselect 时若没 options，用 sample_rows 自动填充
      if ((newType === 'select' || newType === 'multiselect') && (!next.options || next.options.length === 0)) {
        next.options = collectUniqueValues(sampleRows, colName)
      } else if (newType !== 'select' && newType !== 'multiselect') {
        next.options = undefined
      }
      // 若回退到原始值，则清除 override
      if (isOverrideRedundant(colName, next)) {
        const { [colName]: _removed, ...rest } = prev
        return rest
      }
      return { ...prev, [colName]: next }
    })
  }, [analyzeResult, sampleRows, isOverrideRedundant])

  /** 更新某列的 options（select/multiselect 场景）. */
  const updateOptions = useCallback((colName: string, options: string[]) => {
    setOverrides(prev => {
      const base = prev[colName] ?? {
        field_type: effectiveColumns.find(c => c.name === colName)?.field_type ?? 'text',
      }
      const next: ColumnOverride = { ...base, options }
      if (isOverrideRedundant(colName, next)) {
        const { [colName]: _removed, ...rest } = prev
        return rest
      }
      return { ...prev, [colName]: next }
    })
  }, [effectiveColumns, isOverrideRedundant])

  /** 组装 column_overrides payload —— 与后端同结构. */
  const buildColumnOverrides = (): Record<string, ColumnOverride> => {
    const out: Record<string, ColumnOverride> = {}
    if (!analyzeResult) return out
    for (const col of analyzeResult.columns) {
      const ov = overrides[col.name]
      if (!ov) continue
      // 只有与后端原始推断不同才提交
      const baseOptions = col.options ?? []
      const optsDiff = JSON.stringify(ov.options ?? []) !== JSON.stringify(baseOptions)
      if (ov.field_type !== col.field_type || optsDiff) {
        out[col.name] = ov
      }
    }
    return out
  }

  const handleCreate = async () => {
    if (!file) return
    if (!tableName.trim()) { message.error('请输入表名'); return }
    setCreating(true)
    try {
      const ov = buildColumnOverrides()
      const result = await importApi.createFromFile(wid, file, tableName.trim(), ov)
      message.success(`已创建表 "${result.table_name}"，导入 ${result.imported_rows} 行`)
      onSuccess?.(result)
      onClose()
    } catch (err) {
      message.error(err instanceof Error ? err.message : '建表失败')
    } finally {
      setCreating(false)
    }
  }

  // ── 左侧：字段列表 ──
  const renderFieldsList = () => (
    <div style={{ flex: 1, minHeight: 0, overflowY: 'auto', paddingRight: 6 }}>
      {effectiveColumns.map(col => {
        const failCnt = columnFailCounts[col.name] ?? 0
        const baseCol = analyzeResult?.columns.find(c => c.name === col.name)
        const isAutoType = !overrides[col.name]
        const isDate = col.field_type === 'date' || col.field_type === 'datetime'
        const isSelect = col.field_type === 'select' || col.field_type === 'multiselect'
        const hasError = failCnt > 0
        // 卡片背景：选中 > 有异常 > 无异常（绿色）
        let cardBg = '#fafafa'
        let cardBorder = '#e5e7eb'
        if (selectedField === col.name) {
          cardBg = '#eff6ff'; cardBorder = '#93c5fd'
        } else if (hasError) {
          cardBg = '#fef2f2'; cardBorder = '#fecaca'
        } else {
          cardBg = '#f0fdf4'; cardBorder = '#bbf7d0'
        }
        return (
          <div
            key={col.name}
            onClick={() => setSelectedField(col.name)}
            style={{
              padding: 8,
              marginBottom: 6,
              background: cardBg,
              border: `1px solid ${cardBorder}`,
              borderRadius: 5,
              cursor: 'pointer',
            }}
          >
            {/* 字段名 + 类型选择 + 置信度 */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
              <div style={{ fontWeight: 600, flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {col.name}
                {!isAutoType && <Tag color="purple" style={{ marginLeft: 4 }}>已调</Tag>}
              </div>
              {isSelect && <Tag color={getFieldTypeColor('select')}>单选</Tag>}
              {isDate && <Tag color={getFieldTypeColor('date')}>日期</Tag>}
              {hasError ? (
                <Tooltip title={`有 ${failCnt} 行无法转换为此类型`}>
                  <Tag color="red" icon={<WarningOutlined />}>{failCnt}</Tag>
                </Tooltip>
              ) : (
                <Tooltip title="无转换异常">
                  <Tag color="success" icon={<CheckOutlined />} style={{ margin: 0 }} />
                </Tooltip>
              )}
            </div>

            {/* 类型选择下拉 */}
            <Select
              size="small"
              value={col.field_type}
              onChange={(v) => changeFieldType(col.name, v)}
              options={PREVIEW_TYPE_OPTIONS}
              style={{ width: '100%', marginBottom: 4 }}
            />

            {/* 空值率进度条 */}
            {baseCol?.null_ratio != null && baseCol.null_ratio > 0 && (
              <div style={{ fontSize: 11, color: '#64748b', marginBottom: 2, display: 'flex', alignItems: 'center', gap: 4 }}>
                <span>空值</span>
                <Progress
                  size="small"
                  percent={Math.round(baseCol.null_ratio * 100)}
                  strokeColor={baseCol.null_ratio > 0.5 ? '#ef4444' : baseCol.null_ratio > 0.2 ? '#f59e0b' : '#22c55e'}
                  style={{ flex: 1 }}
                />
              </div>
            )}

            {/* 类型识别提示（date/select 特别提示） */}
            {isSelect && (
              <div style={{ fontSize: 11, color: '#d97706', marginBottom: 2 }}>
                <SwapOutlined /> 低基数 → select（{col.options?.length ?? 0}）
              </div>
            )}
            {isDate && (
              <div style={{ fontSize: 11, color: '#16a34a', marginBottom: 2 }}>
                <FileTextOutlined /> 识别为日期
              </div>
            )}

            {/* 样本值 */}
            <div style={{ fontSize: 11, color: '#64748b' }}>
              样本: {(col.sample_values ?? []).slice(0, 3).map((v, i) => (
                <Tag key={i} style={{ marginBottom: 1, background: '#f1f5f9' }}>{v}</Tag>
              ))}
            </div>
          </div>
        )
      })}
    </div>
  )

  // ── 左侧：选中字段的 select options 编辑区 ──
  const renderSelectedFieldEditor = () => {
    if (!selectedField) return null
    const col = effectiveColumns.find(c => c.name === selectedField)
    if (!col) return null

    const isSelect = col.field_type === 'select' || col.field_type === 'multiselect'
    if (!isSelect) return null

    const options = overrides[col.name]?.options ?? col.options ?? []

    return (
      <div style={{ marginTop: 8, padding: 12, background: '#fffbeb', border: '1px solid #fcd34d', borderRadius: 6 }}>
        <div style={{ fontSize: 12, fontWeight: 600, color: '#92400e', marginBottom: 8 }}>
          <SwapOutlined /> 编辑 {col.name} 的选项（{options.length} 个）
        </div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, alignItems: 'center' }}>
          {options.map((opt, i) => (
            <Tag
              key={i}
              closable
              style={{ padding: '2px 8px', fontSize: 12 }}
              onClose={() => updateOptions(col.name, options.filter((_, idx) => idx !== i))}
            >
              {opt}
            </Tag>
          ))}
          <Button
            size="small"
            type="dashed"
            icon={<PlusOutlined />}
            onClick={() => {
              const v = window.prompt('输入新选项值')
              if (v && v.trim() && !options.includes(v.trim())) {
                updateOptions(col.name, [...options, v.trim()])
              }
            }}
          >
            添加
          </Button>
        </div>
      </div>
    )
  }

  // ── 右侧：带实时转换的数据预览表 ──
  const renderDataPreview = () => {
    if (!analyzeResult) return <Empty description="请先上传文件" />
    const cols = effectiveColumns
    if (cols.length === 0) return <Empty description="没有有效列" />

    const columns = cols.map(col => {
      const failCnt = columnFailCounts[col.name] ?? 0
      return {
        title: (
          <div style={{ display: 'flex', alignItems: 'center', gap: 4, whiteSpace: 'nowrap' }}>
            <span style={{ fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis' }}>{col.name}</span>
            <Tag color={getFieldTypeColor(col.field_type)} style={{ margin: 0 }}>{getFieldTypeLabel(col.field_type)}</Tag>
            {failCnt > 0 && (
              <Tooltip title={`有 ${failCnt} 行无法转换`}>
                <ExclamationCircleOutlined style={{ color: '#ef4444' }} />
              </Tooltip>
            )}
          </div>
        ),
        dataIndex: col.name,
        width: 160,
        render: (_v: unknown, row: Record<string, unknown>) => {
          const raw = row[col.name]
          const t = tryConvert(raw, col.field_type)
          if (t.rawText === '' || t.convertedText === '') {
            return <span style={{ color: '#cbd5e1', fontStyle: 'italic' }}>(空)</span>
          }
          if (t.failed) {
            return (
              <Tooltip title={`原始值 "${t.rawText}" 无法转为 ${col.field_type}`}>
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                  <span style={{ color: '#dc2626', textDecoration: 'line-through' }}>{t.rawText}</span>
                  <WarningOutlined style={{ color: '#ef4444', fontSize: 12 }} />
                </span>
              </Tooltip>
            )
          }
          // 转换成功且与原始不同才显示"→"对比
          if (t.convertedText !== t.rawText) {
            return (
              <span>
                <span style={{ color: '#9ca3af', textDecoration: 'line-through', fontSize: 11 }}>{t.rawText}</span>
                <span style={{ color: '#16a34a', marginLeft: 4, fontWeight: 500 }}>→ {t.convertedText}</span>
              </span>
            )
          }
          return <span>{t.rawText}</span>
        },
      }
    })

    const failedRows = sampleRows.filter(row =>
      cols.some(col => tryConvert(row[col.name], col.field_type).failed)
    )

    const errorFieldCount = cols.filter(c => (columnFailCounts[c.name] ?? 0) > 0).length
    const okFieldCount = cols.length - errorFieldCount

    // 统计卡片公共样式
    const statBox = (bg: string, numColor = '#0f172a', icon: any = null, num: any = 0, label = '') => (
      <div style={{ padding: '4px 6px', background: bg, borderRadius: 4, textAlign: 'center' }}>
        <div style={{ fontSize: 14, fontWeight: 700, color: numColor, lineHeight: 1.2 }}>
          {icon}{num}
        </div>
        <div style={{ fontSize: 10, color: '#64748b', marginTop: 1 }}>{label}</div>
      </div>
    )

    return (
      <div style={{ display: 'flex', flexDirection: 'column', flex: 1, minHeight: 0, overflow: 'hidden' }}>
        {/* 汇总栏：6 项统计（固定高度，不随表滚动） */}
        <div style={{ display: 'flex', gap: 6, marginBottom: 6, flexShrink: 0 }}>
          {statBox('#f1f5f9', '#0f172a', null, analyzeResult.total_rows, '总行数')}
          {statBox('#f1f5f9', '#0f172a', null, cols.length, '字段数')}
          {statBox('#f1f5f9', '#0f172a', null, sampleRows.length, '预览行')}
          {statBox(okFieldCount > 0 ? '#f0fdf4' : '#f1f5f9', '#16a34a', <CheckOutlined style={{ marginRight: 1 }} />, okFieldCount, '正常')}
          {statBox(errorFieldCount > 0 ? '#fef2f2' : '#f1f5f9', '#dc2626', <WarningOutlined style={{ marginRight: 1 }} />, errorFieldCount, '异常')}
          {statBox(failedRows.length > 0 ? '#fef2f2' : '#f0fdf4', failedRows.length > 0 ? '#dc2626' : '#16a34a', null, failedRows.length, '异常行')}
        </div>

        {/* Table 容器 —— 用 flex 撑满剩余空间，通过注入样式让 antd 内层 body 滚动 */}
        <div className="import-preview-table-wrapper">
          <Table
            size="small"
            dataSource={(sampleRows as any[]).map((r, i) => ({ ...r, __key: `r-${i}` }))}
            rowKey="__key"
            columns={columns as TableProps['columns']}
            scroll={{ x: cols.length * 160 }}
            pagination={{ pageSize: 20, size: 'small' }}
          />
        </div>
      </div>
    )
  }

  const overriddenCount = Object.keys(overrides).length
  const hasSelectFields = effectiveColumns.some(c => c.field_type === 'select' || c.field_type === 'multiselect')
  const hasDateFields = effectiveColumns.some(c => c.field_type === 'date' || c.field_type === 'datetime')

  // 注入 antd Table flex 自适应样式（仅一次）
  useTableFlexFillStyle()

  return (
    <Modal
      title={
        <span>
          <FileTextOutlined style={{ marginRight: 6 }} />
          导入数据预览
          {overriddenCount > 0 && (
            <Tag color="purple" style={{ marginLeft: 4 }}>{overriddenCount} 个字段已调整</Tag>
          )}
          {hasSelectFields && <Tag color="orange" style={{ marginLeft: 4 }}>含 select</Tag>}
          {hasDateFields && <Tag color="green" style={{ marginLeft: 4 }}>含日期</Tag>}
        </span>
      }
      open={open}
      onCancel={onClose}
      width={1280}
      destroyOnHidden
      style={{ top: 24 }}
      styles={{
        body: {
          maxHeight: 'calc(100vh - 180px)',
          overflow: 'hidden',
          display: 'flex',
          flexDirection: 'column',
        },
      }}
      footer={[
        <Button key="cancel" onClick={onClose}>取消</Button>,
        <Button
          key="create"
          type="primary"
          loading={creating}
          disabled={!file}
          onClick={handleCreate}
          icon={<PlusOutlined />}
        >
          建表并导入
        </Button>,
      ]}
    >
      {/* 表名输入（固定，不随主体滚动） */}
      <div style={{ flexShrink: 0, marginBottom: 8, display: 'flex', alignItems: 'center', gap: 8 }}>
        <span style={{ fontWeight: 500, whiteSpace: 'nowrap' }}>表名：</span>
        <Input value={tableName} onChange={e => setTableName(e.target.value)} style={{ flex: 1 }} placeholder="自动使用文件名" />
        <span style={{ color: '#64748b', fontSize: 12 }}>
          {analyzeResult?.format?.toUpperCase() ?? '-'} · {analyzeResult?.total_rows ?? 0} 行
        </span>
      </div>

      {/* 主体：左右 flex 等高分栏，两栏共享父容器高度 */}
      <div style={{ display: 'flex', gap: 10, flex: 1, minHeight: 0, overflow: 'hidden' }}>
        {/* 左栏：字段与类型 */}
        <div style={{
          width: '32%',
          flexShrink: 0,
          display: 'flex',
          flexDirection: 'column',
          minHeight: 0,
          borderRight: '1px solid #f0f0f0',
          paddingRight: 10,
        }}>
          {/* 左栏标题（固定） */}
          <div style={{ fontSize: 13, fontWeight: 600, color: '#334155', marginBottom: 6, flexShrink: 0 }}>
            字段与类型（{effectiveColumns.length}）
          </div>
          {/* 字段列表（滚动） */}
          {renderFieldsList()}
          {/* 选中字段的 select 选项编辑区（贴底，flex-shrink 防被挤掉） */}
          <div style={{ flexShrink: 0 }}>
            {renderSelectedFieldEditor()}
          </div>
        </div>

        {/* 右栏：典型数据 & 实时转换预览 */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0, overflow: 'hidden' }}>
          {/* 右栏标题（固定） */}
          <div style={{
            fontSize: 13,
            fontWeight: 600,
            color: '#334155',
            marginBottom: 6,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            flexShrink: 0,
          }}>
            <span>典型数据 & 实时转换预览</span>
            <Popover
              placement="bottomRight"
              trigger="click"
              content={
                <div style={{ maxWidth: 360, display: 'flex', flexDirection: 'column', gap: 10 }}>
                  {/* 数据类型颜色图例 */}
                  <div>
                    <div style={{ fontSize: 11, color: '#64748b', marginBottom: 6, fontWeight: 600 }}>数据类型颜色</div>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                      {PREVIEW_TYPE_OPTIONS.map(t => (
                        <Tag key={t.value} color={getFieldTypeColor(t.value)} style={{ margin: 0 }}>
                          {t.label}
                        </Tag>
                      ))}
                    </div>
                  </div>
                  {/* 转换状态图例 */}
                  <div>
                    <div style={{ fontSize: 11, color: '#64748b', marginBottom: 6, fontWeight: 600 }}>转换状态</div>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 6, fontSize: 12, color: '#475569' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <Tag color="success" icon={<CheckOutlined />} style={{ margin: 0 }} />
                        <span>字段无类型转换异常</span>
                      </div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <Tag color="red" icon={<WarningOutlined />} style={{ margin: 0 }} />
                        <span>部分行无法转换为此类型</span>
                      </div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <span style={{ color: '#cbd5e1', fontStyle: 'italic' }}>(空)</span>
                        <span>该单元格原始值为空</span>
                      </div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <span style={{ color: '#9ca3af', textDecoration: 'line-through' }}>原始</span>
                        <span style={{ color: '#16a34a' }}>→ 转换后</span>
                        <span>格式发生变化（如 2024/01/05 → 2024-01-05）</span>
                      </div>
                    </div>
                  </div>
                </div>
              }
            >
              <Button size="small" type="text" icon={<InfoCircleOutlined />}>图例说明</Button>
            </Popover>
          </div>

          {/* 数据预览（内部 flex:1 撑满） */}
          {renderDataPreview()}
        </div>
      </div>
    </Modal>
  )
}
