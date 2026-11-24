/** 导出面板 — 多格式选择 + 视图筛选开关 + Blob 下载.
 *
 * 从合并版「导入/导出」对话框拆出：导出状态（格式 / 是否按视图筛选 / loading）
 * 内聚于此，外层 Modal 由独立入口 `ExportDialog` 负责.
 * 格式默认 XLSX，并记住上次选择（`exportPrefs.ts`）；
 * 文件名优先从后端 Content-Disposition 头解析（支持 RFC 5987 filename* 中文编码），
 * 格式为「工作区-数据表-视图-YYYYMMDD_HHMMSS.扩展名」；解析失败降级为 table-{tid}-export.{ext}.
 * PDF 格式为前端视觉快照（exportViewToPdf），不调用后端导出接口、不受范围开关影响.
 */
import { useCallback, useState } from 'react'
import { Alert, Button, Select, Switch } from 'antd'
import { DownloadOutlined } from '@ant-design/icons'
import { App as AntApp } from 'antd'
import { exportApi } from '@/api'
import { exportViewToPdf } from './exportPdf'
import { loadExportFormat, saveExportFormat, type ExportFormat } from './exportPrefs'

interface ExportPanelProps {
  wid: string
  tid: string
  /** 当前激活的视图 ID（用于按视图筛选导出） */
  viewId?: number | string | null
  /** 当前激活的视图名称（仅用于提示） */
  viewName?: string
  /** 进入 PDF 导出模式（GridPage 关闭虚拟滚动、全量渲染）并返回视图内容区根元素，resolve 前已等待重渲染完成 */
  getPdfTarget?: () => Promise<HTMLElement | null>
  /** PDF 导出结束后调用（GridPage 退出导出模式，恢复虚拟滚动） */
  releasePdfTarget?: () => void
  /** 关闭对话框（底部动作条与 Modal 的关闭共用同一回调） */
  onClose: () => void
}

/** 生成本地时间戳 YYYYMMDD_HHMMSS（PDF 文件名用） */
function formatTimestamp(date: Date): string {
  const p = (n: number) => String(n).padStart(2, '0')
  return `${date.getFullYear()}${p(date.getMonth() + 1)}${p(date.getDate())}_${p(date.getHours())}${p(date.getMinutes())}${p(date.getSeconds())}`
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

export default function ExportPanel({ wid, tid, viewId, viewName, getPdfTarget, releasePdfTarget, onClose }: ExportPanelProps) {
  const { message } = AntApp.useApp()
  const [exporting, setExporting] = useState(false)
  // 默认 XLSX，并记住上次选择（localStorage 单键 `cndb_export_format`）
  const [selectedFormat, setSelectedFormat] = useState<ExportFormat>(() => loadExportFormat())
  const [useViewFilter, setUseViewFilter] = useState(true)

  /** 格式切换：立即落偏好，下次打开弹窗沿用 */
  const handleFormatChange = useCallback((format: ExportFormat) => {
    setSelectedFormat(format)
    saveExportFormat(format)
  }, [])

  /** PDF 视觉快照导出：进入导出模式取目标 → 生成 PDF → 触发下载 → 退出导出模式 */
  const handleExportPdf = useCallback(async () => {
    let target: HTMLElement | null = null
    try {
      setExporting(true)
      // getPdfTarget 内部先切换导出模式（关闭虚拟滚动、全量渲染）再返回目标元素
      target = (await getPdfTarget?.()) ?? null
      if (!target) {
        message.error('未找到可导出的视图内容')
        return
      }
      const ts = formatTimestamp(new Date())
      const filename = viewName ? `view-${viewName}-${ts}.pdf` : `table-${tid}-view.pdf`
      await exportViewToPdf(target, filename)
      message.success('导出完成')
    } catch (err) {
      message.error(err instanceof Error ? err.message : '导出失败')
    } finally {
      releasePdfTarget?.()
      setExporting(false)
    }
  }, [getPdfTarget, releasePdfTarget, viewName, tid, message])

  const handleExport = useCallback(async () => {
    if (selectedFormat === 'pdf') {
      await handleExportPdf()
      return
    }
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
  }, [wid, tid, selectedFormat, useViewFilter, viewId, handleExportPdf, message])

  return (
    <div className="cn-export-panel">
      {/* 格式：标签定宽，与备份/恢复等表单行同口径 */}
      <div className="cn-field">
        <span className="cn-field-label">导出格式</span>
        <Select
          value={selectedFormat}
          onChange={handleFormatChange}
          style={{ width: 'min(240px, 100%)' }}
          options={[
            { value: 'xlsx', label: 'XLSX' },
            { value: 'csv', label: 'CSV（Excel 兼容）' },
            { value: 'pdf', label: 'PDF（当前视图画面）' },
            { value: 'json', label: 'JSON' },
          ]}
          disabled={exporting}
        />
      </div>
      <div className="cn-dialog-hint">将表中的数据导出为所选格式（单次上限 50 万行，超限请收窄筛选后分批导出）</div>

      {/* 范围：仅非 PDF 且存在激活视图时可选；PDF 走视觉快照，范围固定为当前画面 */}
      {selectedFormat === 'pdf' ? (
        <Alert
          type="info"
          showIcon
          className="cn-dialog-hint cn-dialog-hint-block"
          title="PDF 导出当前视图可见内容画面（不含顶部栏），按屏幕实际大小输出：内容较宽时纸张会相应变宽，字号不会缩小"
        />
      ) : viewId != null && (
        <div className="cn-field cn-field-spaced">
          <span className="cn-field-label">导出范围</span>
          <Switch size="small" checked={useViewFilter} onChange={setUseViewFilter} />
          <span className="cn-export-note">
            {useViewFilter
              ? `按当前视图「${viewName || ''}」筛选后导出`
              : '导出全表数据（忽略视图筛选）'}
          </span>
        </div>
      )}

      {/* 底部动作条：关闭 + 下载（主操作靠右，与弹窗表单口径一致） */}
      <div className="cn-export-actions">
        <Button onClick={onClose}>关闭</Button>
        <Button
          type="primary"
          icon={<DownloadOutlined />}
          loading={exporting}
          onClick={handleExport}
        >下载</Button>
      </div>
    </div>
  )
}
