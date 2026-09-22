/** 导出面板 — 多格式选择 + 视图筛选开关 + Blob 下载.
 *
 * 从 ImportExportDialog 拆出：导出状态（格式 / 是否按视图筛选 / loading）内聚于此.
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

export default function ExportPanel({ wid, tid, viewId, viewName }: ExportPanelProps) {
  const { message } = AntApp.useApp()
  const [exporting, setExporting] = useState(false)
  const [selectedFormat, setSelectedFormat] = useState<'json' | 'csv' | 'xlsx'>('csv')
  const [useViewFilter, setUseViewFilter] = useState(true)

  const handleExport = useCallback(async () => {
    try {
      setExporting(true)
      const vid = useViewFilter && viewId != null ? viewId : undefined
      const blob = await exportApi.download(wid, tid, selectedFormat, vid)
      const url = URL.createObjectURL(blob as Blob)
      const a = document.createElement('a')
      const tableName = `table-${tid}`
      const extMap: Record<string, string> = { json: '.json', csv: '.csv', xlsx: '.xlsx' }
      a.download = `${tableName}-export${extMap[selectedFormat]}`
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
