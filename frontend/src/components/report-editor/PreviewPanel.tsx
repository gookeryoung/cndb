import { useEffect, useMemo, useState } from 'react'
import nunjucks from 'nunjucks'
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
  // debounce 300ms
  const result = useMemo<RenderResult>(() => {
    if (!template.trim()) {
      return { output: '', error: null, elapsed: 0 }
    }
    const ctx = { records, table_name: tableName || '', params, records_by_table: recordsByTable || {} }
    return tryRender(template, ctx)
  }, [template, records, tableName, params, recordsByTable])

  const [debouncedResult, setDebouncedResult] = useState<RenderResult>(result)

  useEffect(() => {
    const id = setTimeout(() => setDebouncedResult(result), 300)
    return () => clearTimeout(id)
  }, [result])

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
