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

import { useCallback, useEffect, useMemo, useState } from 'react'
import { Modal, Input, Tag, Button, Popover, Select, Alert, App as AntApp } from 'antd'
import { CheckOutlined, FileTextOutlined, InfoCircleOutlined, PlusOutlined, WarningOutlined } from '@ant-design/icons'
import { importApi } from '@/api'
import type { FileAnalyzeResult, FileImportResult, HeaderDetectionCandidate } from '@/api'


interface Props {
  open: boolean
  wid: number | string
  file: File | null
  /** analyze 结果（来自 importApi.analyzeFile） */
  analyzeResult: FileAnalyzeResult | null
  onClose: () => void
  onSuccess?: (result: FileImportResult) => void
}

/** timestamp 候选值域常量 —— 与后端 TimestampFieldType/transfer 推断层双向锁定：
 * 秒级 [1e9, 4102444800]，毫秒级 (4102444800, 4102444800000]（预览时 //1000 归一为秒显示） */

import { getFieldTypeColor } from '@/utils/fieldTypeMeta'

import { collectUniqueValues, tryConvert } from './importPreviewConvert'
import { PREVIEW_TYPE_OPTIONS } from './importPreviewOptions'
import { useTableFlexFillStyle } from './useTableFlexFillStyle'

import DataPreviewTable from './DataPreviewTable'
import FieldsList from './FieldsList'
import SelectedFieldEditor from './SelectedFieldEditor'
import type { AnalyzeColumn, ColumnOverride } from './importPreviewTypes'
import { WEIGHT } from '@/theme/tokens'

export default function FileImportPreview({ open, wid, file, analyzeResult, onClose, onSuccess }: Props) {
  const { message } = AntApp.useApp()
  const [overrides, setOverrides] = useState<Record<string, ColumnOverride>>({})
  const [tableName, setTableName] = useState('')
  const [creating, setCreating] = useState(false)
  const [selectedField, setSelectedField] = useState<string | null>(null)
  /** 当前生效的分析结果：初值来自 analyzeResult prop，用户改选表头行后由重新 analyze 的结果替换 */
  const [currentResult, setCurrentResult] = useState<FileAnalyzeResult | null>(analyzeResult)
  /** 当前选中的表头行（1-based）；header_detection 为 null 时不使用 */
  const [headerRow, setHeaderRow] = useState<number | null>(null)
  const [headerLoading, setHeaderLoading] = useState(false)

  /** 把一次 analyze 结果同步为内部状态（列/表头/样本预览都基于它渲染） */
  const applyAnalyzeResult = useCallback((result: FileAnalyzeResult) => {
    setCurrentResult(result)
    setHeaderRow(result.header_detection?.row ?? result.header_row ?? null)
    setOverrides({})
    const firstCol = result.columns.find(c => c.name.trim())
    setSelectedField(firstCol?.name ?? null)
  }, [])

  // 重置内部状态（open / prop 分析结果变化时）
  useEffect(() => {
    if (!open || !analyzeResult) return
    applyAnalyzeResult(analyzeResult)
    // 默认表名 = 文件名去扩展名
    const fn = analyzeResult.filename || ''
    setTableName(fn.replace(/\.[^.]+$/, '') || '导入数据表')
  }, [open, analyzeResult, applyAnalyzeResult])

  /** 用户改选表头行：重新 analyze，成功后整体替换内部结果并重置字段 overrides. */
  const handleHeaderRowChange = async (row: number) => {
    if (!file || headerLoading) return
    setHeaderLoading(true)
    try {
      const result = await importApi.analyzeFile(wid, file, row)
      applyAnalyzeResult(result)
    } catch (err) {
      message.error(err instanceof Error ? err.message : '重新识别表头失败')
    } finally {
      setHeaderLoading(false)
    }
  }

  /** 表头行下拉选项：第 N 行 · 置信度 · 前几个单元格文本预览 */
  const headerDetection = currentResult?.header_detection ?? null
  const headerCandidateOptions = useMemo(
    () => (headerDetection?.candidates ?? []).map((c: HeaderDetectionCandidate) => ({
      value: c.row,
      label: `第 ${c.row} 行 · ${Math.round(c.confidence * 100)}% · ${c.values.filter(Boolean).slice(0, 3).join(' / ')}`,
    })),
    [headerDetection],
  )

  /** 当前生效的列定义 = 后端原始 + 用户 overrides. */
  const effectiveColumns: AnalyzeColumn[] = useMemo(() => {
    if (!currentResult) return []
    return currentResult.columns.map(col => {
      const ov = overrides[col.name]
      if (!ov) return col
      return {
        ...col,
        field_type: ov.field_type,
        options: ov.options ?? col.options,
      }
    })
  }, [currentResult, overrides])

  const sampleRows = useMemo(() => currentResult?.sample_rows ?? [], [currentResult])

  /** 某列的类型转换失败计数 —— 用于左侧字段卡片上的警示. */
  const columnFailCounts = useMemo(() => {
    const res: Record<string, number> = {}
    if (!currentResult) return res
    for (const col of effectiveColumns) {
      let fail = 0
      for (const row of sampleRows) {
        const t = tryConvert(row[col.name], col.field_type)
        if (t.failed) fail++
      }
      res[col.name] = fail
    }
    return res
  }, [effectiveColumns, sampleRows, currentResult])

  /** 判断 override 是否与后端原始完全一致 —— 一致则应清除. */
  const isOverrideRedundant = useCallback((colName: string, ov: ColumnOverride): boolean => {
    const original = currentResult?.columns.find(c => c.name === colName)
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
  }, [currentResult])

  /** 改变字段类型 —— 自动填 options 如果是 select. */
  const changeFieldType = useCallback((colName: string, newType: string) => {
    setOverrides(prev => {
      const baseCol = currentResult?.columns.find(c => c.name === colName)
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
  }, [currentResult, sampleRows, isOverrideRedundant])

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
    if (!currentResult) return out
    for (const col of currentResult.columns) {
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
      // 表头行仅在自动识别可用时提交（JSON 无表头概念，不传该参数）
      const result = headerDetection
        ? await importApi.createFromFile(wid, file, tableName.trim(), ov, headerRow ?? undefined)
        : await importApi.createFromFile(wid, file, tableName.trim(), ov)
      message.success(`已创建表 "${result.table_name}"，导入 ${result.imported_rows} 行`)
      onSuccess?.(result)
      onClose()
    } catch (err) {
      message.error(err instanceof Error ? err.message : '建表失败')
    } finally {
      setCreating(false)
    }
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
        <span style={{ fontWeight: WEIGHT.medium, whiteSpace: 'nowrap' }}>表名：</span>
        <Input value={tableName} onChange={e => setTableName(e.target.value)} style={{ flex: 1 }} placeholder="自动使用文件名" />
        <span style={{ color: 'var(--cn-text-muted)', fontSize: 12 }}>
          {currentResult?.format?.toUpperCase() ?? '-'} · {currentResult?.total_rows ?? 0} 行
        </span>
      </div>

      {/* 表头行自动识别结果（JSON 无表头概念时不渲染） */}
      {headerDetection && (
        <div style={{ flexShrink: 0, marginBottom: 8, display: 'flex', alignItems: 'flex-start', gap: 8, flexWrap: 'wrap' }}>
          <Alert
            data-testid="header-detection-alert"
            type={headerDetection.requires_review ? 'warning' : 'info'}
            showIcon
            style={{ flex: '1 1 480px', minWidth: 280, padding: '4px 10px' }}
            message={
              <span>
                {headerDetection.message}
                {headerDetection.requires_review && (
                  <span style={{ marginLeft: 6 }}>建议人工确认识别到的表头行</span>
                )}
              </span>
            }
          />
          <Tag
            color={headerDetection.requires_review ? 'orange' : 'blue'}
            style={{ margin: '2px 0 0', flexShrink: 0 }}
          >
            置信度 {Math.round(headerDetection.confidence * 100)}%
          </Tag>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexShrink: 0 }}>
            <span style={{ fontSize: 13, color: 'var(--cn-text-secondary)', whiteSpace: 'nowrap' }}>表头行：</span>
            <Select
              data-testid="header-row-select"
              size="small"
              style={{ minWidth: 260 }}
              value={headerRow ?? headerDetection.row}
              options={headerCandidateOptions}
              loading={headerLoading}
              disabled={headerLoading || headerCandidateOptions.length === 0}
              onChange={(row: number) => { void handleHeaderRowChange(row) }}
            />
          </div>
        </div>
      )}

      {/* 主体：左右 flex 等高分栏，两栏共享父容器高度 */}
      <div style={{ display: 'flex', gap: 10, flex: 1, minHeight: 0, overflow: 'hidden' }}>
        {/* 左栏：字段与类型 */}
        <div style={{
          width: '32%',
          flexShrink: 0,
          display: 'flex',
          flexDirection: 'column',
          minHeight: 0,
          borderRight: '1px solid var(--cn-border-soft)',
          paddingRight: 10,
        }}>
          {/* 左栏标题（固定） */}
          <div style={{ fontSize: 13, fontWeight: WEIGHT.semibold, color: 'var(--cn-text-secondary)', marginBottom: 6, flexShrink: 0 }}>
            字段与类型（{effectiveColumns.length}）
          </div>
          {/* 字段列表（滚动） */}
          <FieldsList
        analyzeResult={currentResult}
        effectiveColumns={effectiveColumns}
        overrides={overrides}
        columnFailCounts={columnFailCounts}
        selectedField={selectedField}
        setSelectedField={setSelectedField}
        changeFieldType={changeFieldType}
      />
          {/* 选中字段的 select 选项编辑区（贴底，flex-shrink 防被挤掉） */}
          <div style={{ flexShrink: 0 }}>
            <SelectedFieldEditor
        effectiveColumns={effectiveColumns}
        overrides={overrides}
        selectedField={selectedField}
        updateOptions={updateOptions}
      />
          </div>
        </div>

        {/* 右栏：典型数据 & 实时转换预览 */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0, overflow: 'hidden' }}>
          {/* 右栏标题（固定） */}
          <div style={{
            fontSize: 13,
            fontWeight: WEIGHT.semibold,
            color: 'var(--cn-text-secondary)',
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
                    <div style={{ fontSize: 11, color: 'var(--cn-text-muted)', marginBottom: 6, fontWeight: WEIGHT.semibold }}>数据类型颜色</div>
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
                    <div style={{ fontSize: 11, color: 'var(--cn-text-muted)', marginBottom: 6, fontWeight: WEIGHT.semibold }}>转换状态</div>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 6, fontSize: 12, color: 'var(--cn-text-secondary)' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <Tag color="success" icon={<CheckOutlined />} style={{ margin: 0 }} />
                        <span>字段无类型转换异常</span>
                      </div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <Tag color="red" icon={<WarningOutlined />} style={{ margin: 0 }} />
                        <span>部分行无法转换为此类型</span>
                      </div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <span style={{ color: 'var(--cn-text-disabled)', fontStyle: 'italic' }}>(空)</span>
                        <span>该单元格原始值为空</span>
                      </div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <span style={{ color: 'var(--cn-text-muted)', textDecoration: 'line-through' }}>原始</span>
                        <span style={{ color: '#22c55e' }}>→ 转换后</span>
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
          <DataPreviewTable
        analyzeResult={currentResult}
        effectiveColumns={effectiveColumns}
        columnFailCounts={columnFailCounts}
        sampleRows={sampleRows}
      />
        </div>
      </div>
    </Modal>
  )
}
