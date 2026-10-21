/** 分析结果视图 —— 图表 + 分组汇总 + 描述统计 + 派生数据预览（含 CSV / PNG 导出）. */

import { useEffect, useMemo, useState } from 'react'
import { App as AntApp, Button, Empty, Table, Tag, Tooltip, Typography } from 'antd'
import { DownloadOutlined, LineChartOutlined, PictureOutlined, TableOutlined } from '@ant-design/icons'
import * as echarts from 'echarts/core'
import type { Field } from '@/api'
import type { AnalyticsChart, AnalyticsComputeResponse } from '@/api/analytics'
import { ChartCard } from '@/pages/grid/views/ChartView'
import { AnalyticsBox } from './AnalyticsBox'
import {
  downloadTextFile,
  formatNumber,
  nonNullRatio,
  safeFileName,
  toChartConfig,
  toCsv,
  triggerDownload,
} from './analyticsModel'

const { Text } = Typography

/** 预览表分页大小候选 */
const PAGE_SIZE_OPTIONS = [20, 50, 100]

const NUMERIC_TYPES = new Set(['number', 'decimal', 'float', 'percentage'])

interface FormulaLabel {
  key: string
  label: string
}

interface Props {
  result: AnalyticsComputeResponse
  chart: AnalyticsChart
  /** 当前公式（含展示名），用于派生列标题 */
  formulas: FormulaLabel[]
  /** 表字段元信息（决定预览列的数值格式化 / 排序方式） */
  fields: Field[]
  /** 模板名或图表标题，用于导出文件名 */
  title: string
}

/** 数值列排序器（空值排最后） */
function numericSorter(key: string) {
  return (a: Record<string, unknown>, b: Record<string, unknown>) => {
    const av = typeof a[key] === 'number' ? (a[key] as number) : null
    const bv = typeof b[key] === 'number' ? (b[key] as number) : null
    if (av === null && bv === null) return 0
    if (av === null) return 1
    if (bv === null) return -1
    return av - bv
  }
}

/** 文本列排序器（本地化比较） */
function textSorter(key: string) {
  return (a: Record<string, unknown>, b: Record<string, unknown>) =>
    String(a[key] ?? '').localeCompare(String(b[key] ?? ''), 'zh-Hans-CN')
}

/** 分析结果：图表、汇总表、统计表、数据预览与导出 */
export function AnalyticsResultView({ result, chart, formulas, fields, title }: Props) {
  const { message } = AntApp.useApp()
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(PAGE_SIZE_OPTIONS[0])

  // 新结果回到第一页
  useEffect(() => { setPage(1) }, [result])

  const fieldType = useMemo(() => {
    const map: Record<string, string> = {}
    for (const field of fields) map[field.name] = field.field_type
    return map
  }, [fields])

  const numericFieldNames = useMemo(
    () => result.table_fields.filter(name => NUMERIC_TYPES.has(fieldType[name] ?? '')),
    [result.table_fields, fieldType],
  )

  const formulaKeys = useMemo(() => formulas.map(f => f.key), [formulas])
  const formulaLabelMap = useMemo(
    () => Object.fromEntries(formulas.map(f => [f.key, f.label || f.key])),
    [formulas],
  )

  const chartCfg = useMemo(() => toChartConfig(chart), [chart])

  const exportStats = () => {
    const headers = ['列', '类型', '计数', '缺失', '非空率', '均值', '标准差', '方差', '最小值', '极差', 'P25', '中位数', 'P75', '最大值', '求和']
    const rows = result.columns.map(col => {
      const ratio = nonNullRatio(col.count, col.missing)
      return [
        col.label || col.key,
        col.kind === 'formula' ? '公式' : '字段',
        col.count,
        col.missing,
        ratio === null ? '' : `${(ratio * 100).toFixed(1)}%`,
        col.mean, col.stdev, col.variance, col.min, col.range,
        col.q1, col.median, col.q3, col.max, col.sum,
      ]
    })
    downloadTextFile(`${safeFileName(title)}-描述统计.csv`, toCsv(headers, rows))
    message.success('描述统计已导出 CSV')
  }

  const exportRows = () => {
    const headers = [...result.table_fields, ...formulas.map(f => f.label || f.key)]
    const rows = result.rows.map(row => [
      ...result.table_fields.map(name => row[name]),
      ...formulaKeys.map(key => row[key]),
    ])
    downloadTextFile(`${safeFileName(title)}-派生数据.csv`, toCsv(headers, rows))
    message.success(`已导出 ${rows.length} 行派生数据`)
  }

  const exportSummary = () => {
    const summary = result.summary
    if (!summary) return
    const headers = [summary.group_label, ...summary.columns.map(col => col.label)]
    const rows = summary.rows.map(row => [
      row.group,
      ...summary.columns.map(col => row[col.key]),
    ])
    downloadTextFile(`${safeFileName(title)}-分组汇总.csv`, toCsv(headers, rows))
    message.success('分组汇总已导出 CSV')
  }

  const exportChart = () => {
    const container = document.querySelector('[data-testid="chart-container"]') as HTMLElement | null
    const instance = container ? echarts.getInstanceByDom(container) : undefined
    if (!instance) {
      message.warning('图表尚未渲染完成，请稍后再试')
      return
    }
    const dataUrl = instance.getDataURL({ type: 'png', pixelRatio: 2, backgroundColor: '#ffffff' })
    if (!dataUrl) {
      message.warning('图表导出失败')
      return
    }
    triggerDownload(`${safeFileName(title)}-图表.png`, dataUrl)
    message.success('图表已导出 PNG')
  }

  const previewColumns = [
    ...result.table_fields.map(name => {
      const isNumeric = numericFieldNames.includes(name)
      return {
        title: name,
        dataIndex: name,
        render: (value: unknown) => (isNumeric ? formatNumber(value) : String(value ?? '—')),
        sorter: isNumeric ? numericSorter(name) : textSorter(name),
      }
    }),
    ...formulas.map(formula => ({
      title: `${formula.label || formula.key}（公式）`,
      dataIndex: formula.key,
      render: (value: unknown) => formatNumber(value),
      sorter: numericSorter(formula.key),
    })),
  ]

  return (
    <>
      <Card
        size="small"
        title={chart.title || '可视化结果'}
        extra={
          <Space size={8}>
            <Text type="secondary" style={{ fontSize: 12 }}>
              共 {result.total} 行{result.truncated ? '（超出单次扫描上限，已截断；可在「分析范围」限定区间）' : ''}
            </Text>
            <Tooltip title="把当前图表导出为 PNG（2x 清晰度）">
              <Button size="small" icon={<PictureOutlined />} data-testid="analytics-export-chart" onClick={exportChart}>
                导出图表
              </Button>
            </Tooltip>
          </Space>
        }
      >
        {result.rows.length === 0 ? (
          <Empty description="该表暂无数据" />
        ) : (
          <ChartCard cfg={chartCfg} rows={result.rows} fields={fields} total={result.total} />
        )}
      </Card>

      {result.summary && (
        <Card
          size="small"
          title={`分组汇总（按 ${result.summary.group_label}）`}
          extra={
            <Space size={8}>
              <Text type="secondary" style={{ fontSize: 12 }}>
                共 {result.summary.group_count} 组
                {result.summary.truncated ? `，已按 Top ${result.summary.rows.length} 截断` : ''}
              </Text>
              <Button size="small" icon={<DownloadOutlined />} data-testid="analytics-export-summary" onClick={exportSummary}>
                导出汇总
              </Button>
            </Space>
          }
        >
          <Table
            data-testid="analytics-summary-table"
            size="small"
            rowKey="group"
            pagination={false}
            scroll={{ x: 'max-content', y: 320 }}
            dataSource={result.summary.rows}
            columns={[
              { title: result.summary.group_label, dataIndex: 'group', fixed: 'left' as const },
              ...result.summary.columns.map(col => ({
                title: col.label,
                dataIndex: col.key,
                render: (value: unknown) => formatNumber(value),
                sorter: numericSorter(col.key),
              })),
            ]}
          />
        </Card>
      )}

      <Card
        size="small"
        title="描述统计（含派生指标）"
        extra={
          <Button size="small" icon={<DownloadOutlined />} data-testid="analytics-export-stats" onClick={exportStats}>
            导出 CSV
          </Button>
        }
      >
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
            {
              title: '非空率',
              key: 'non_null_ratio',
              render: (_v, row) => {
                const ratio = nonNullRatio(row.count, row.missing)
                return ratio === null ? '—' : `${(ratio * 100).toFixed(1)}%`
              },
            },
            { title: '均值', dataIndex: 'mean', render: formatNumber },
            { title: '标准差', dataIndex: 'stdev', render: formatNumber },
            { title: '方差', dataIndex: 'variance', render: formatNumber },
            { title: '最小值', dataIndex: 'min', render: formatNumber },
            { title: '极差', dataIndex: 'range', render: formatNumber },
            { title: 'P25', dataIndex: 'q1', render: formatNumber },
            { title: '中位数', dataIndex: 'median', render: formatNumber },
            { title: 'P75', dataIndex: 'q3', render: formatNumber },
            { title: '最大值', dataIndex: 'max', render: formatNumber },
            { title: '求和', dataIndex: 'sum', render: formatNumber },
          ]}
        />
      </Card>

      <Card
        size="small"
        title="派生数据预览"
        extra={
          <Button size="small" icon={<DownloadOutlined />} data-testid="analytics-export-rows" onClick={exportRows}>
            导出 CSV
          </Button>
        }
      >
        <Table
          data-testid="analytics-rows-table"
          size="small"
          rowKey="id"
          dataSource={result.rows}
          columns={previewColumns}
          pagination={{
            current: page,
            pageSize,
            total: result.rows.length,
            showSizeChanger: true,
            pageSizeOptions: PAGE_SIZE_OPTIONS,
            showTotal: total => `共 ${total} 行`,
            onChange: (nextPage, nextSize) => {
              setPage(nextSize !== pageSize ? 1 : nextPage)
              setPageSize(nextSize)
            },
          }}
          scroll={{ x: 'max-content' }}
        />
        <Text type="secondary" style={{ fontSize: 12 }}>
          派生列：{formulas.map(f => formulaLabelMap[f.key] ?? f.key).join('、') || '（无公式）'}
          {result.rows.length < result.total ? `；返回前 ${result.rows.length} 行，统计基于全部 ${result.total} 行` : ''}
        </Text>
      </Card>
    </>
  )
}
