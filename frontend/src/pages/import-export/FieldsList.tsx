/** 导入预览左侧：识别到的字段列表（可调整 field_type，点击选中某列）.
 *
 * 从 FileImportPreview 的 renderFieldsList 闭包抽出。
 */

import { Progress, Select, Tag, Tooltip } from 'antd'
import { CheckOutlined, ClockCircleOutlined, FileTextOutlined, SwapOutlined, WarningOutlined } from '@ant-design/icons'

import type { FileAnalyzeResult } from '@/api'
import { getFieldTypeColor } from '@/utils/fieldTypeMeta'

import { PREVIEW_TYPE_OPTIONS } from './importPreviewOptions'
import type { AnalyzeColumn, ColumnOverride } from './importPreviewTypes'


export default function FieldsList({
  analyzeResult,
  effectiveColumns,
  overrides,
  columnFailCounts,
  selectedField,
  setSelectedField,
  changeFieldType,
}: {
  analyzeResult: FileAnalyzeResult | null
  effectiveColumns: AnalyzeColumn[]
  overrides: Record<string, ColumnOverride>
  columnFailCounts: Record<string, number>
  selectedField: string | null
  setSelectedField: (name: string) => void
  changeFieldType: (name: string, fieldType: string) => void
}) {
  return (
    <div style={{ flex: 1, minHeight: 0, overflowY: 'auto', paddingRight: 6 }}>
      {effectiveColumns.map(col => {
        const failCnt = columnFailCounts[col.name] ?? 0
        const baseCol = analyzeResult?.columns.find(c => c.name === col.name)
        const isAutoType = !overrides[col.name]
        const isDate = col.field_type === 'date' || col.field_type === 'datetime'
        const isTimestamp = col.field_type === 'timestamp'
        const isLongtext = col.field_type === 'longtext'
        const isSelect = col.field_type === 'select' || col.field_type === 'multiselect'
        const hasError = failCnt > 0
        // 卡片背景：选中 > 有异常 > 无异常（绿色）
        let cardBg = 'var(--cn-bg-muted)'
        let cardBorder = 'var(--cn-border-soft)'
        if (selectedField === col.name) {
          cardBg = 'var(--cn-mix-blue-10-bg-container)'
          cardBorder = 'var(--cn-mix-blue-45-transparent)'
        } else if (hasError) {
          cardBg = 'var(--cn-mix-red-10-bg-container)'
          cardBorder = 'var(--cn-mix-red-40-transparent)'
        } else {
          cardBg = 'var(--cn-mix-green-10-bg-container)'
          cardBorder = 'var(--cn-mix-green-40-transparent)'
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
              <div style={{ fontSize: 11, color: 'var(--cn-text-muted)', marginBottom: 2, display: 'flex', alignItems: 'center', gap: 4 }}>
                <span>空值</span>
                <Progress
                  size="small"
                  percent={Math.round(baseCol.null_ratio * 100)}
                  strokeColor={baseCol.null_ratio > 0.5 ? '#ef4444' : baseCol.null_ratio > 0.2 ? '#f59e0b' : '#22c55e'}
                  style={{ flex: 1 }}
                />
              </div>
            )}

            {/* 类型识别提示（date/timestamp/longtext/select 特别提示） */}
            {isSelect && (
              <div style={{ fontSize: 11, color: '#f59e0b', marginBottom: 2 }}>
                <SwapOutlined /> 低基数 → select（{col.options?.length ?? 0}）
              </div>
            )}
            {isDate && (
              <div style={{ fontSize: 11, color: '#22c55e', marginBottom: 2 }}>
                <FileTextOutlined /> 识别为日期
              </div>
            )}
            {isTimestamp && (
              <div style={{ fontSize: 11, color: '#22c55e', marginBottom: 2 }}>
                <ClockCircleOutlined /> 识别为时间戳（秒/毫秒自动归一）
              </div>
            )}
            {isLongtext && (
              <div style={{ fontSize: 11, color: '#06b6d4', marginBottom: 2 }}>
                <FileTextOutlined /> 识别为长文本
              </div>
            )}

            {/* 样本值 */}
            <div style={{ fontSize: 11, color: 'var(--cn-text-muted)' }}>
              样本: {(col.sample_values ?? []).slice(0, 3).map((v, i) => (
                <Tag key={i} style={{ marginBottom: 1, background: 'var(--cn-bg-muted)' }}>{v}</Tag>
              ))}
            </div>
          </div>
        )
      })}
    </div>
  )
}
