import { useMemo } from 'react'
import nunjucks from 'nunjucks'
import dayjs from 'dayjs'
import { useDebouncedValue } from '@/hooks'
import { Alert, Empty, Spin, Typography } from 'antd'

export interface PreviewPanelProps {
  /** 当前模板内容 */
  template: string
  /** 模拟行数据（records — 主表） */
  records: Array<Record<string, unknown>>
  /** 表名 */
  tableName?: string
  /** 用户参数 */
  params?: Record<string, unknown>
  /** 数据源加载状态 */
  loading?: boolean
  /** 额外表预览数据 (tableName -> records[]) */
  recordsByTable?: Record<string, Array<Record<string, unknown>>>
}

/**
 * 前端 nunjucks 渲染器（Jinja2 兼容子集）。
 * 设置为 autoescape=false 与后端保持一致。
 * 浏览器端直接渲染字符串，不需要 Node.js 专用的 FileSystemLoader。
 */
// 浏览器端不需要 FileSystemLoader（Node 专属），renderString 直接用 null loader 即可
const renderer = new nunjucks.Environment(null, {
  autoescape: false,
  trimBlocks: true,
  lstripBlocks: true,
})

/**
 * 把字段值转为数字；null/非数字/空串返回 null —— 与后端 _coerce_numeric 同语义
 */
function coerceNumeric(v: unknown): number | null {
  if (v === null || v === undefined || v === '') return null
  const n = Number(v)
  return Number.isFinite(n) ? n : null
}

/**
 * 给前端渲染上下文注入 Jinja2 dict 的 .get(key, default) 方法。
 *
 * 后端使用 Jinja2（Python dict 原生支持 .get），前端预览使用 Nunjucks
 * （JS plain object 没有 .get）。此包装让双端对 `params.get('key', '默认值')`
 * 语法行为一致 —— key 存在返回值，不存在或值为 null/undefined 时返回默认值。
 */
function wrapParams(raw: Record<string, unknown> | undefined): Record<string, unknown> {
  const obj: Record<string, unknown> = { ...(raw || {}) }
  obj.get = function (key: string, defaultValue?: unknown): unknown {
    const v = this[key]
    return v === null || v === undefined ? defaultValue : v
  }
  return obj
}

/** 单列统计 —— 与后端 stats 同语义；non_empty 统计原始值非空行数（可用于文本字段计数） */
renderer.addGlobal('stats', (records: Array<Record<string, unknown>>, field: string) => {
  const rawValues = records.map(r => r[field])
  const nums = rawValues.map(coerceNumeric).filter((v): v is number => v !== null)
  const nonEmpty = rawValues.filter(v => v !== null && v !== undefined && v !== '').length
  if (nums.length === 0) return { count: 0, sum: 0, avg: 0, min: null, max: null, non_empty: nonEmpty }
  const total = nums.reduce((a, b) => a + b, 0)
  return { count: nums.length, sum: total, avg: total / nums.length, min: Math.min(...nums), max: Math.max(...nums), non_empty: nonEmpty }
})

/** 分组统计 —— 与后端 group_stats 同语义 */
renderer.addGlobal('group_stats', (records: Array<Record<string, unknown>>, keyField: string, valueField: string) => {
  const groups: Record<string, unknown[]> = {}
  for (const r of records) {
    const k = String(r[keyField] ?? '')
    if (!groups[k]) groups[k] = []
    groups[k].push(r[valueField])
  }
  const result: Array<Record<string, unknown>> = []
  for (const [key, vals] of Object.entries(groups)) {
    const nums = vals.map(coerceNumeric).filter((v): v is number => v !== null)
    if (nums.length > 0) {
      const total = nums.reduce((a, b) => a + b, 0)
      result.push({ key, count: nums.length, sum: total, avg: total / nums.length, min: Math.min(...nums), max: Math.max(...nums) })
    } else {
      result.push({ key, count: 0, sum: 0, avg: 0, min: null, max: null })
    }
  }
  return result
})

interface RenderResult {
  output: string
  error: string | null
  elapsed: number
}

function tryRender(template: string, ctx: Record<string, unknown>): RenderResult {
  const start = performance.now()
  try {
    const output = renderer.renderString(template, ctx)
    return { output, error: null, elapsed: performance.now() - start }
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err)
    return { output: '', error: msg, elapsed: performance.now() - start }
  }
}

export default function PreviewPanel({
  template,
  records,
  tableName,
  params = {},
  loading = false,
  recordsByTable,
}: PreviewPanelProps) {
  // 渲染结果防抖 300ms（通用 useDebouncedValue，收敛原手写 setTimeout 实现）
  const result = useMemo<RenderResult>(() => {
    if (!template.trim()) {
      return { output: '', error: null, elapsed: 0 }
    }
    const ctx = { records, table_name: tableName || '', params: wrapParams(params), records_by_table: recordsByTable || {}, generated_at: dayjs().format('YYYY-MM-DD HH:mm') }
    return tryRender(template, ctx)
  }, [template, records, tableName, params, recordsByTable])

  const debouncedResult = useDebouncedValue(result, 300)

  return (
    <div className="report-preview-panel">
      <div className="report-preview-header">
        <Typography.Title level={5} style={{ margin: 0 }}>
          实时预览
        </Typography.Title>
        <div className="report-preview-meta">
          {loading && <Spin size="small" />}
          {!loading && tableName && (
            <Typography.Text type="secondary" style={{ fontSize: 11 }}>
              {tableName} · {records.length} 行 · {debouncedResult.elapsed.toFixed(0)}ms
            </Typography.Text>
          )}
        </div>
      </div>

      <div className="report-preview-body">
        {!template.trim() ? (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description={<span style={{ fontSize: 12 }}>在左侧编辑器输入模板后，这里会显示渲染结果</span>}
          />
        ) : debouncedResult.error ? (
          <Alert
            type="error"
            showIcon
            message="渲染错误"
            description={
              <pre style={{ margin: 0, fontSize: 12, whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>
                {debouncedResult.error}
              </pre>
            }
          />
        ) : (
          <pre className="report-preview-output">{debouncedResult.output || '(空输出)'}</pre>
        )}
      </div>
    </div>
  )
}
