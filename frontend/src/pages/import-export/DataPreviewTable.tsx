/** 导入预览右侧：带实时转换的数据预览表（统计栏 + 转换结果着色）.
 *
 * 从 FileImportPreview 的 renderDataPreview 闭包抽出。
 */

import { Empty, Table, Tag, Tooltip } from 'antd'
import type { TableProps } from 'antd'
import { CheckOutlined, ExclamationCircleOutlined, WarningOutlined } from '@ant-design/icons'

import type { FileAnalyzeResult } from '@/api'
import { getFieldTypeColor, getFieldTypeLabel } from '@/utils/fieldTypeMeta'

import { tryConvert } from './importPreviewConvert'
import type { AnalyzeColumn } from './importPreviewTypes'
import { WEIGHT } from '@/theme/tokens'

export default function DataPreviewTable({
  analyzeResult,
  effectiveColumns,
  columnFailCounts,
  sampleRows,
}: {
  analyzeResult: FileAnalyzeResult | null
  effectiveColumns: AnalyzeColumn[]
  columnFailCounts: Record<string, number>
  sampleRows: Array<Record<string, unknown>>
}) {
    if (!analyzeResult) return <Empty description="请先上传文件" />
    const cols = effectiveColumns
    if (cols.length === 0) return <Empty description="没有有效列" />

    const columns = cols.map(col => {
      const failCnt = columnFailCounts[col.name] ?? 0
      return {
        title: (
          <div style={{ display: 'flex', alignItems: 'center', gap: 4, whiteSpace: 'nowrap' }}>
            <span style={{ fontWeight: WEIGHT.semibold, overflow: 'hidden', textOverflow: 'ellipsis' }}>{col.name}</span>
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
            return <span style={{ color: 'var(--cn-text-disabled)', fontStyle: 'italic' }}>(空)</span>
          }
          if (t.failed) {
            return (
              <Tooltip title={`原始值 "${t.rawText}" 无法转为 ${col.field_type}`}>
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                  <span style={{ color: '#ef4444', textDecoration: 'line-through' }}>{t.rawText}</span>
                  <WarningOutlined style={{ color: '#ef4444', fontSize: 12 }} />
                </span>
              </Tooltip>
            )
          }
          // 转换成功且与原始不同才显示"→"对比
          if (t.convertedText !== t.rawText) {
            return (
              <span>
                <span style={{ color: 'var(--cn-text-muted)', textDecoration: 'line-through', fontSize: 11 }}>{t.rawText}</span>
                <span style={{ color: '#22c55e', marginLeft: 4, fontWeight: WEIGHT.medium }}>→ {t.convertedText}</span>
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
    const statBox = (bg: string, numColor = 'var(--cn-text-primary)', icon: any = null, num: any = 0, label = '') => (
      <div style={{ padding: '4px 6px', background: bg, borderRadius: 4, textAlign: 'center' }}>
        <div style={{ fontSize: 14, fontWeight: WEIGHT.bold, color: numColor, lineHeight: 1.2 }}>
          {icon}{num}
        </div>
        <div style={{ fontSize: 10, color: 'var(--cn-text-muted)', marginTop: 1 }}>{label}</div>
      </div>
    )

    return (
      <div style={{ display: 'flex', flexDirection: 'column', flex: 1, minHeight: 0, overflow: 'hidden' }}>
        {/* 汇总栏：6 项统计（固定高度，不随表滚动） */}
        <div style={{ display: 'flex', gap: 6, marginBottom: 6, flexShrink: 0 }}>
          {statBox('var(--cn-bg-muted)', 'var(--cn-text-primary)', null, analyzeResult.total_rows, '总行数')}
          {statBox('var(--cn-bg-muted)', 'var(--cn-text-primary)', null, cols.length, '字段数')}
          {statBox('var(--cn-bg-muted)', 'var(--cn-text-primary)', null, sampleRows.length, '预览行')}
          {statBox(okFieldCount > 0 ? 'var(--cn-mix-green-10-bg-container)' : 'var(--cn-bg-muted)', okFieldCount > 0 ? '#22c55e' : 'var(--cn-text-primary)', <CheckOutlined style={{ marginRight: 1 }} />, okFieldCount, '正常')}
          {statBox(errorFieldCount > 0 ? 'var(--cn-mix-red-10-bg-container)' : 'var(--cn-bg-muted)', errorFieldCount > 0 ? '#ef4444' : 'var(--cn-text-primary)', <WarningOutlined style={{ marginRight: 1 }} />, errorFieldCount, '异常')}
          {statBox(failedRows.length > 0 ? 'var(--cn-mix-red-10-bg-container)' : 'var(--cn-mix-green-10-bg-container)', failedRows.length > 0 ? '#ef4444' : '#22c55e', null, failedRows.length, '异常行')}
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
