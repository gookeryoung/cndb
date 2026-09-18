/** 文件导入预览 Modal —— 左右分栏.
 *
 * 左侧：识别到的字段列表，可调整 field_type；
 * 右侧：数据实时转换预览表（sample_rows），当用户调整左侧字段类型时，
 *       右侧对应列的值以"原始 → 转换后"形式实时展示。
 *
 * 性能策略：
 * - 所有行×列的 tryConvert 在 useMemo 中一次性计算，渲染阶段只读缓存；
 * - Table dataSource 用分页 + 可选"仅显示异常"过滤，避免一次渲染过多行。
 *
 * 支持的交互：
 * - 改变字段类型（下拉）
 * - select 类型可编辑 options（自动填充推测值，可增删）
 * - 数值/日期/boolean 等类型在右侧显示转换结果与失败警示
 * - 勾选"仅显示异常"聚焦问题行
 */

import { useCallback, useMemo, useState } from 'react'
import { Modal, Input, Table, Select, Tag, Progress, Button, Empty, Tooltip, Row, Col, Checkbox, message } from 'antd'
import { FileTextOutlined, SwapOutlined, WarningOutlined, PlusOutlined, ExclamationCircleOutlined, CheckOutlined, DownOutlined, UpOutlined } from '@ant-design/icons'
import { importApi } from '@/api'
import type { FileAnalyzeResult, FileImportResult } from '@/api'

/** 预览里允许切换的字段类型子集（过滤掉 link/attachment/formula 等不适合从原始数据推断的类型） */
const PREVIEW_FIELD_TYPES = [
  { value: 'text', label: '文本 text' },
  { value: 'number', label: '整数 number' },
  { value: 'float', label: '小数 float' },
  { value: 'boolean', label: '布尔 boolean' },
  { value: 'date', label: '日期 date' },
  { value: 'datetime', label: '日期时间 datetime' },
  { value: 'select', label: '单选 select' },
  { value: 'multiselect', label: '多选 multiselect' },
  { value: 'email', label: '邮箱 email' },
  { value: 'url', label: '链接 url' },
  { value: 'phone', label: '电话 phone' },
  { value: 'percentage', label: '百分比 percentage' },
]

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

/** 字段类型颜色映射. */
const TYPE_COLOR: Record<string, string> = {
  text: 'default', longtext: 'default', number: 'blue', float: 'blue',
  boolean: 'purple', date: 'green', datetime: 'green',
  select: 'orange', multiselect: 'orange',
  email: 'cyan', url: 'cyan', phone: 'cyan', percentage: 'magenta',
}

export default function FileImportPreview({ open, wid, file, analyzeResult, onClose, onSuccess }: Props) {
  const [overrides, setOverrides] = useState<Record<string, ColumnOverride>>({})
  const [tableName, setTableName] = useState('')
  const [creating, setCreating] = useState(false)
  const [selectedField, setSelectedField] = useState<string | null>(null)
  /** 右侧预览区图例面板是否折叠 */
  const [legendCollapsed, setLegendCollapsed] = useState(false)
  /** 仅显示异常行 —— 方便聚焦问题 */
  const [onlyShowFailed, setOnlyShowFailed] = useState(false)

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

  /** 所有行×列的转换结果 —— 一次性算完，渲染只读，避免重复 tryConvert 热点.
   *  rowTransforms[i][colName] = CellTransform
   *  rowHasError[i] = 该行是否有任意转换失败
   *  columnFailCounts[colName] = 该列失败数
   *  failedRowIndices = 有失败的行在 sample_rows 里的下标
   */
  const { rowTransforms, rowHasError, columnFailCounts, failedRowIndices } = useMemo(() => {
    const cols = effectiveColumns
    const rows = sampleRows
    const rowT: Array<Record<string, CellTransform>> = rows.map(() => ({}))
    const rowE: boolean[] = rows.map(() => false)
    const colF: Record<string, number> = {}
    const failedIdx: number[] = []
    for (let ci = 0; ci < cols.length; ci++) {
      const col = cols[ci]
      let fail = 0
      for (let ri = 0; ri < rows.length; ri++) {
        const t = tryConvert(rows[ri][col.name], col.field_type)
        rowT[ri][col.name] = t
        if (t.failed) {
          fail++
          rowE[ri] = true
        }
      }
      colF[col.name] = fail
    }
    for (let ri = 0; ri < rowE.length; ri++) {
      if (rowE[ri]) failedIdx.push(ri)
    }
    return { rowTransforms: rowT, rowHasError: rowE, columnFailCounts: colF, failedRowIndices: failedIdx }
  }, [effectiveColumns, sampleRows])

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
    <div style={{ height: '60vh', overflowY: 'auto', borderRight: '1px solid #f0f0f0', paddingRight: 8 }}>
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
              padding: 10,
              marginBottom: 8,
              background: cardBg,
              border: `1px solid ${cardBorder}`,
              borderRadius: 6,
              cursor: 'pointer',
            }}
          >
            {/* 字段名 + 类型选择 + 置信度 */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
              <div style={{ fontWeight: 600, flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {col.name}
                {!isAutoType && <Tag color="purple" style={{ marginLeft: 6 }}>已调整</Tag>}
              </div>
              {isSelect && <Tag color="orange">select</Tag>}
              {isDate && <Tag color="green">日期</Tag>}
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
              options={PREVIEW_FIELD_TYPES}
              style={{ width: '100%', marginBottom: 6 }}
            />

            {/* 空值率进度条 */}
            {baseCol?.null_ratio != null && baseCol.null_ratio > 0 && (
              <div style={{ fontSize: 11, color: '#64748b', marginBottom: 4, display: 'flex', alignItems: 'center', gap: 6 }}>
                <span>空值率</span>
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
              <div style={{ fontSize: 11, color: '#d97706', marginBottom: 4 }}>
                <SwapOutlined /> 低基数文本列 → 识别为 select（{col.options?.length ?? 0} 个选项）
              </div>
            )}
            {isDate && (
              <div style={{ fontSize: 11, color: '#16a34a', marginBottom: 4 }}>
                <FileTextOutlined /> 识别为日期格式
              </div>
            )}

            {/* 样本值 */}
            <div style={{ fontSize: 11, color: '#64748b' }}>
              样本: {(col.sample_values ?? []).slice(0, 3).map((v, i) => (
                <Tag key={i} style={{ marginBottom: 2, background: '#f1f5f9' }}>{v}</Tag>
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

    // 构造列定义：首列固定行号，后跟业务列
    const columns = [
      {
        title: '#',
        key: '__row_number__',
        width: 64,
        fixed: 'left' as const,
        render: (_v: unknown, _row: unknown, idx: number) => {
          const realIdx = onlyShowFailed ? (failedRowIndices[idx] ?? idx) : idx
          const hasErr = rowHasError[realIdx]
          return (
            <span style={{
              display: 'inline-flex', alignItems: 'center', gap: 4,
              color: hasErr ? '#dc2626' : '#64748b', fontWeight: hasErr ? 600 : 500,
            }}>
              {hasErr && <WarningOutlined style={{ fontSize: 11 }} />}
              {realIdx + 1}
            </span>
          )
        },
      },
      ...cols.map(col => {
        const failCnt = columnFailCounts[col.name] ?? 0
        return {
          title: (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
              <span style={{ fontWeight: 600 }}>{col.name}</span>
              <div>
                <Tag color={TYPE_COLOR[col.field_type] ?? 'default'} style={{ margin: 0 }}>{col.field_type}</Tag>
                {failCnt > 0 && (
                  <Tooltip title={`有 ${failCnt} 行无法转换`}>
                    <ExclamationCircleOutlined style={{ color: '#ef4444', marginLeft: 4 }} />
                  </Tooltip>
                )}
              </div>
            </div>
          ),
          dataIndex: col.name,
          width: 180,
          render: (_v: unknown, _row: unknown, idx: number) => {
            // 直接读缓存，不再 tryConvert
            const realIdx = onlyShowFailed ? (failedRowIndices[idx] ?? idx) : idx
            const t = rowTransforms[realIdx]?.[col.name]
            if (!t) return null
            if (t.rawText === '' || t.convertedText === '') {
              return <span style={{ color: '#cbd5e1', fontStyle: 'italic' }}>(空)</span>
            }
            if (t.failed) {
              return (
                <Tooltip title={`原始值 "${t.rawText}" 无法转为 ${col.field_type}`}>
                  <span style={{
                    display: 'inline-block',
                    background: '#fee2e2',
                    color: '#b91c1c',
                    padding: '2px 6px',
                    borderRadius: 4,
                    border: '1px solid #fecaca',
                    textDecoration: 'line-through',
                    fontSize: 12,
                  }}>{t.rawText}</span>
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
      }),
    ]

    // 异常统计
    const errorFieldCount = cols.filter(c => (columnFailCounts[c.name] ?? 0) > 0).length
    const okFieldCount = cols.length - errorFieldCount

    // 实际展示的 dataSource（用索引保持映射，Table 用 rowKey + 真实行号）
    const displaySource: Array<Record<string, unknown> & { __real_idx__: number }> = (onlyShowFailed
      ? failedRowIndices.map(i => ({ ...(sampleRows[i] as any), __real_idx__: i }))
      : sampleRows.map((r, i) => ({ ...(r as any), __real_idx__: i })))

    const rowClassName = (_record: Record<string, unknown>, idx: number) => {
      const realIdx = onlyShowFailed ? (failedRowIndices[idx] ?? idx) : idx
      return rowHasError[realIdx] ? 'ant-table-row-warning' : ''
    }

    const rowKey = (_record: Record<string, unknown>, i: number) => {
      if (!onlyShowFailed) return `r-${i}`
      return `r-${(failedRowIndices[i] ?? i)}`
    }

    return (
      <div>
        {/* 汇总栏：6 项统计 */}
        <Row gutter={[8, 8]} style={{ marginBottom: 10 }}>
          <Col span={4}>
            <div style={{ padding: '6px 8px', background: '#f1f5f9', borderRadius: 6, textAlign: 'center' }}>
              <div style={{ fontSize: 16, fontWeight: 700, color: '#0f172a' }}>{analyzeResult.total_rows}</div>
              <div style={{ fontSize: 11, color: '#64748b' }}>总行数</div>
            </div>
          </Col>
          <Col span={4}>
            <div style={{ padding: '6px 8px', background: '#f1f5f9', borderRadius: 6, textAlign: 'center' }}>
              <div style={{ fontSize: 16, fontWeight: 700, color: '#0f172a' }}>{cols.length}</div>
              <div style={{ fontSize: 11, color: '#64748b' }}>字段数</div>
            </div>
          </Col>
          <Col span={4}>
            <div style={{ padding: '6px 8px', background: '#f1f5f9', borderRadius: 6, textAlign: 'center' }}>
              <div style={{ fontSize: 16, fontWeight: 700, color: '#0f172a' }}>{sampleRows.length}</div>
              <div style={{ fontSize: 11, color: '#64748b' }}>预览行</div>
            </div>
          </Col>
          <Col span={4}>
            <div style={{ padding: '6px 8px', background: okFieldCount > 0 ? '#f0fdf4' : '#f1f5f9', borderRadius: 6, textAlign: 'center' }}>
              <div style={{ fontSize: 16, fontWeight: 700, color: '#16a34a' }}>
                <CheckOutlined style={{ marginRight: 2 }} />{okFieldCount}
              </div>
              <div style={{ fontSize: 11, color: '#64748b' }}>无异常字段</div>
            </div>
          </Col>
          <Col span={4}>
            <div style={{ padding: '6px 8px', background: errorFieldCount > 0 ? '#fef2f2' : '#f1f5f9', borderRadius: 6, textAlign: 'center' }}>
              <div style={{ fontSize: 16, fontWeight: 700, color: '#dc2626' }}>
                <WarningOutlined style={{ marginRight: 2 }} />{errorFieldCount}
              </div>
              <div style={{ fontSize: 11, color: '#64748b' }}>异常字段</div>
            </div>
          </Col>
          <Col span={4}>
            <div style={{ padding: '6px 8px', background: failedRowIndices.length > 0 ? '#fef2f2' : '#f0fdf4', borderRadius: 6, textAlign: 'center' }}>
              <div style={{ fontSize: 16, fontWeight: 700, color: failedRowIndices.length > 0 ? '#dc2626' : '#16a34a' }}>
                {failedRowIndices.length}
              </div>
              <div style={{ fontSize: 11, color: '#64748b' }}>异常行</div>
            </div>
          </Col>
        </Row>

        {/* 过滤控制条 */}
        <div style={{
          marginBottom: 8,
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '6px 12px', background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: 6,
        }}>
          <Checkbox
            checked={onlyShowFailed}
            onChange={e => setOnlyShowFailed(e.target.checked)}
            disabled={failedRowIndices.length === 0}
          >
            仅显示异常行
            <span style={{ marginLeft: 4, color: '#64748b', fontSize: 12 }}>
              ({failedRowIndices.length}/{sampleRows.length})
            </span>
          </Checkbox>
          <div style={{ fontSize: 12, color: '#64748b' }}>
            共 {displaySource.length} 行 · 全部分页显示
          </div>
        </div>

        <Table
          size="small"
          rowKey={rowKey as any}
          rowClassName={rowClassName}
          dataSource={displaySource}
          columns={columns as any}
          scroll={{ x: 80 + cols.length * 180, y: '55vh' }}
          pagination={{
            pageSize: 20,
            pageSizeOptions: [10, 20, 50],
            showSizeChanger: true,
            showTotal: (total, range) => `${range[0]}-${range[1]} / ${total} 行`,
          }}
        />

        {/* 注入异常行背景样式（ant-table-row-warning） */}
        <style>{`
          .ant-table-tbody > tr.ant-table-row-warning > td {
            background-color: #fef2f2 !important;
          }
          .ant-table-tbody > tr.ant-table-row-warning:hover > td {
            background-color: #fee2e2 !important;
          }
        `}</style>
      </div>
    )
  }

  const overriddenCount = Object.keys(overrides).length
  const hasSelectFields = effectiveColumns.some(c => c.field_type === 'select' || c.field_type === 'multiselect')
  const hasDateFields = effectiveColumns.some(c => c.field_type === 'date' || c.field_type === 'datetime')

  return (
    <Modal
      title={
        <span>
          <FileTextOutlined style={{ marginRight: 6 }} />
          导入数据预览
          {analyzeResult?.filename && (
            <Tag color="blue" style={{ marginLeft: 8 }}>{analyzeResult.filename}</Tag>
          )}
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
      {/* 表名输入 */}
      <div style={{ marginBottom: 12, display: 'flex', alignItems: 'center', gap: 12 }}>
        <span style={{ fontWeight: 500, whiteSpace: 'nowrap' }}>表名：</span>
        <Input value={tableName} onChange={e => setTableName(e.target.value)} style={{ flex: 1 }} placeholder="自动使用文件名" />
        <span style={{ color: '#64748b', fontSize: 12 }}>
          格式：{analyzeResult?.format?.toUpperCase() ?? '-'} · 共 {analyzeResult?.total_rows ?? 0} 行
        </span>
      </div>

      {/* 主体：左右分栏 */}
      <Row gutter={16}>
        {/* 左栏：字段列表 */}
        <Col span={8}>
          <div style={{ fontSize: 13, fontWeight: 600, color: '#334155', marginBottom: 8 }}>
            字段与类型（{effectiveColumns.length}）
          </div>
          {renderFieldsList()}
          {renderSelectedFieldEditor()}
        </Col>
        {/* 右栏：数据预览 */}
        <Col span={16}>
          <div style={{ fontSize: 13, fontWeight: 600, color: '#334155', marginBottom: 8, display: 'flex', alignItems: 'center', gap: 8 }}>
            数据实时转换预览
          </div>

          {/* 图例面板（可折叠） */}
          <div
            style={{
              marginBottom: 10,
              border: '1px solid #e5e7eb',
              borderRadius: 6,
              background: '#fafafa',
              overflow: 'hidden',
            }}
          >
            <div
              onClick={() => setLegendCollapsed(c => !c)}
              style={{
                padding: '6px 12px',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                fontSize: 12,
                color: '#475569',
                fontWeight: 500,
                background: '#f1f5f9',
                userSelect: 'none',
              }}
            >
              <span>图例说明</span>
              {legendCollapsed ? <DownOutlined style={{ fontSize: 10 }} /> : <UpOutlined style={{ fontSize: 10 }} />}
            </div>
            {!legendCollapsed && (
              <div style={{ padding: '8px 12px', display: 'flex', flexDirection: 'column', gap: 8 }}>
                {/* 数据类型颜色图例 */}
                <div>
                  <div style={{ fontSize: 11, color: '#64748b', marginBottom: 4, fontWeight: 500 }}>数据类型</div>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                    {PREVIEW_FIELD_TYPES.map(t => (
                      <Tag key={t.value} color={TYPE_COLOR[t.value] ?? 'default'} style={{ margin: 0 }}>
                        {t.label}
                      </Tag>
                    ))}
                  </div>
                </div>
                {/* 转换状态图例 */}
                <div>
                  <div style={{ fontSize: 11, color: '#64748b', marginBottom: 4, fontWeight: 500 }}>转换状态</div>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12, fontSize: 11, color: '#475569' }}>
                    <span><Tag color="success" icon={<CheckOutlined />} style={{ margin: 0 }} /> 无异常</span>
                    <span><Tag color="red" icon={<WarningOutlined />} style={{ margin: 0 }} /> 转换异常</span>
                    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 2 }}>
                      <span style={{ color: '#cbd5e1', fontStyle: 'italic' }}>(空)</span> 空值
                    </span>
                    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 2 }}>
                      <span style={{ color: '#9ca3af', textDecoration: 'line-through' }}>原始</span>
                      <span style={{ color: '#16a34a' }}>→ 转换后</span> 格式变化
                    </span>
                  </div>
                </div>
              </div>
            )}
          </div>

          {renderDataPreview()}
        </Col>
      </Row>
    </Modal>
  )
}
