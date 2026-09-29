/** 导出面板 — 多格式选择 + 视图筛选开关 + Blob 下载.
 *
 * 从 ImportExportDialog 拆出：导出状态（格式 / 是否按视图筛选 / loading）内聚于此.
 * 文件名优先从后端 Content-Disposition 头解析（支持 RFC 5987 filename* 中文编码），
 * 格式为「工作区-数据表-视图-YYYYMMDD_HHMMSS.扩展名」；解析失败降级为 table-{tid}-export.{ext}.
 */
import { useCallback, useState } from 'react'
import { Button, Empty, Select, Space, Switch } from 'antd'
import { DownloadOutlined } from '@ant-design/icons'
import { App as AntApp } from 'antd'
import { exportApi } from '@/api'

interface ExportPanelProps {
  wid: string
  tid: string
  /** 当前激活的视图 ID（用于按视图筛选导出） */
  viewId?: number | string | null
  /** 当前激活的视图名称（仅用于提示） */
  viewName?: string
}

/** 从 Content-Disposition 头解析文件名.
 *
 * 优先级：filename*=UTF-8''...（RFC 5987 编码，支持中文）> filename="..."（ASCII fallback）.
 * 找不到时返回 null.
 */
function parseContentDispositionFilename(header: string | undefined): string | null {
  if (!header) return null
  // 优先 filename*（RFC 5987）
  const utf8Match = header.match(/filename\*=UTF-8''([^;]+)/i)
  if (utf8Match?.[1]) {
    try {
      return decodeURIComponent(utf8Match[1].trim())
    } catch {
      // fall through
    }
  }
  // 再试 filename（带引号）
  const quotedMatch = header.match(/filename="?([^";]+)"?/i)
  if (quotedMatch?.[1]) return quotedMatch[1].trim()
  return null
}

export default function ExportPanel({ wid, tid, viewId, viewName }: ExportPanelProps) {
  const { message } = AntApp.useApp()
  const [exporting, setExporting] = useState(false)
  const [selectedFormat, setSelectedFormat] = useState<'json' | 'csv' | 'xlsx'>('csv')
  const [useViewFilter, setUseViewFilter] = useState(true)

  const handleExport = useCallback(async () => {
    try {
      setExporting(true)
      const vid = useViewFilter && viewId != null ? viewId : undefined
      const resp = await exportApi.download(wid, tid, selectedFormat, vid)
      const blob = resp.data as Blob
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      // 优先用后端 Content-Disposition 里的文件名（含工作区/数据表/视图名+时间戳）
      const backendFilename = parseContentDispositionFilename(
        resp.headers?.['content-disposition'] ?? resp.headers?.['Content-Disposition']
      )
      const extMap: Record<string, string> = { json: '.json', csv: '.csv', xlsx: '.xlsx' }
      a.download = backendFilename || `table-${tid}-export${extMap[selectedFormat]}`
      a.href = url
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)
      message.success('导出完成')
    } catch (err) {
      message.error(err instanceof Error ? err.message : '导出失败')
    } finally {
      setExporting(false)
    }
  }, [wid, tid, selectedFormat, useViewFilter, viewId, message])

  return (
    <div>
      <Empty
        description={
          <span style={{ color: 'var(--cn-text-muted)' }}>
            将表中的数据导出为所选格式（最多 10000 行）
          </span>
        }
      />
      {viewId != null && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '8px 12px', background: 'var(--cn-bg-subtle)', borderRadius: 6, marginBottom: 8 }}>
          <Switch size="small" checked={useViewFilter} onChange={setUseViewFilter} />
          <span style={{ fontSize: 13, color: 'var(--cn-text-secondary)' }}>
            {useViewFilter
              ? `按当前视图「${viewName || ''}」筛选后导出`
              : '导出全表数据（忽略视图筛选）'}
          </span>
        </div>
      )}
      <Space style={{ justifyContent: 'center', width: '100%', marginTop: 8 }}>
        <Select
          value={selectedFormat}
          onChange={setSelectedFormat}
          style={{ width: 160 }}
          options={[
            { value: 'csv', label: 'CSV（Excel 兼容）' },
            { value: 'json', label: 'JSON' },
            { value: 'xlsx', label: 'XLSX' },
          ]}
          disabled={exporting}
        />
        <Button
          type="primary"
          icon={<DownloadOutlined />}
          loading={exporting}
          onClick={handleExport}
        >下载</Button>
      </Space>
    </div>
  )
}
