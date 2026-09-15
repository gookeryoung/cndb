/** 导入/导出对话框 — 文件上传 + 两阶段预览 + 异步进度轮询 + 多格式导出 + API 抓取追加. */

import { useCallback, useEffect, useRef, useState } from 'react'
import { Modal, Tabs, Button, Progress, message, Space, Select, Alert, Empty, Upload, Switch, Table, Tag, Collapse } from 'antd'
import { InboxOutlined, UploadOutlined, DownloadOutlined, FileTextOutlined, ApiOutlined, CheckCircleOutlined, ExclamationCircleOutlined, CloseCircleOutlined } from '@ant-design/icons'
import { importApi, exportApi } from '@/api'
import type { ImportTaskInfo } from '@/api'
import ApiImportDialog from './ApiImportDialog'

const { Dragger } = Upload

interface Props {
  open: boolean
  wid: string
  tid: string
  onClose: () => void
  /** 导入成功后调用（刷新列表等） */
  onImported?: () => void
  /** 当前激活的视图 ID（用于按视图筛选导出） */
  viewId?: number | string | null
  /** 当前激活的视图名称（仅用于提示） */
  viewName?: string
}

/** 允许的导入文件扩展名 */
const ACCEPTED_EXT = ['.csv', '.json', '.xlsx', '.xls']

interface ValidationReport {
  total: number
  valid_count: number
  warning_count: number
  error_count: number
  skipped_columns: string[]
  missing_required: string[]
  warnings: Array<{ row_number: number; field: string; message: string }>
  errors: Array<{ row_number: number; field: string; message: string }>
  actually_imported?: number
}

type Phase = 'idle' | 'analyzing' | 'preview' | 'importing' | 'done' | 'failed'

export default function ImportExportDialog({ open, wid, tid, onClose, onImported, viewId, viewName }: Props) {
  const [task, setTask] = useState<ImportTaskInfo | null>(null)
  const [phase, setPhase] = useState<Phase>('idle')
  const [polling, setPolling] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [selectedFormat, setSelectedFormat] = useState<'json' | 'csv' | 'xlsx'>('csv')
  const [useViewFilter, setUseViewFilter] = useState(true)
  const pollTimer = useRef<number | null>(null)

  // 关闭时清理
  useEffect(() => {
    if (!open) {
      if (pollTimer.current) {
        clearInterval(pollTimer.current)
        pollTimer.current = null
      }
      setTask(null)
      setPolling(false)
      setPhase('idle')
    }
  }, [open])

  // 轮询任务状态
  useEffect(() => {
    if (!polling || !task) return
    pollTimer.current = window.setInterval(async () => {
      try {
        const info = await importApi.getTask(wid, tid, task.task_id)
        setTask(info)
        // analyze 完成 → pending_confirm → 展示预览
        if (info.status === 'pending_confirm') {
          setPolling(false)
          setPhase('preview')
          const report = (info as ImportTaskInfo & { validation_report?: ValidationReport }).validation_report
          if (report) {
            // file_columns 在后端报告里没有单独存，但 skipped_columns 能给提示
          }
        } else if (info.status === 'done') {
          setPolling(false)
          setPhase('done')
          if (info.imported_rows && info.imported_rows > 0) {
            message.success(`导入完成：${info.imported_rows} 行`)
          }
          onImported?.()
        } else if (info.status === 'failed') {
          setPolling(false)
          setPhase('failed')
          message.error(`导入失败：${info.error_message ?? '未知错误'}`)
        }
      } catch {
        // 忽略轮询错误，下次继续
      }
    }, 800)
    return () => {
      if (pollTimer.current) {
        clearInterval(pollTimer.current)
        pollTimer.current = null
      }
    }
  }, [polling, task, wid, tid, onImported])

  // 用 any 绕过 antd Upload 复杂类型
  const beforeUpload = useCallback((file: any) => {
    const name: string = file?.name?.toLowerCase() || ''
    if (!ACCEPTED_EXT.some(ext => name.endsWith(ext))) {
      message.error(`仅支持 ${ACCEPTED_EXT.join(' / ')} 文件`)
      return false
    }
    // 调 previewAnalyze（两阶段）
    importApi.previewAnalyze(wid, tid, file as File)
      .then((info) => {
        setTask(info)
        setPhase('analyzing')
        setPolling(true)
      })
      .catch((err: unknown) => {
        const msg = err instanceof Error ? err.message : '上传失败'
        message.error(msg)
      })
    return false
  }, [wid, tid])

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
  }, [wid, tid, selectedFormat, useViewFilter, viewId])

  // ── 确认导入 ──
  const handleConfirm = async () => {
    if (!task) return
    try {
      await importApi.confirmImport(wid, tid, task.task_id)
      setPhase('importing')
      setPolling(true)
    } catch (err) {
      message.error(err instanceof Error ? err.message : '确认失败')
    }
  }

  // ── 取消/重置 ──
  const handleReset = () => {
    if (pollTimer.current) {
      clearInterval(pollTimer.current)
      pollTimer.current = null
    }
    setTask(null)
    setPhase('idle')
    setPolling(false)
  }

  // ── 下载失败行 ──
  const handleDownloadFailed = async () => {
    if (!task) return
    try {
      const blob = await importApi.downloadFailedRows(wid, tid, task.task_id, 'csv')
      const url = URL.createObjectURL(blob as unknown as Blob)
      const a = document.createElement('a')
      a.download = `failed-rows-${task.task_id}.csv`
      a.href = url
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)
    } catch (err) {
      message.error(err instanceof Error ? err.message : '下载失败')
    }
  }

  // ── 渲染：状态条 ──
  const renderStatusBar = () => {
    if (!task) return null
    const colorMap: Record<string, 'success' | 'exception' | 'active' | 'normal'> = {
      pending_confirm: 'active',
      running: 'active',
      done: 'success',
      failed: 'exception',
      pending_validation: 'active',
      pending: 'active',
    }
    const textMap: Record<string, string> = {
      pending_confirm: '校验完成，等待确认',
      pending_validation: '校验中...',
      running: '导入中...',
      done: '已完成',
      failed: '失败',
      pending: '排队中',
    }
    return (
      <div style={{ marginTop: 12, padding: 12, background: '#f6f8fa', borderRadius: 8 }}>
        <div style={{ fontSize: 13, color: '#475569', marginBottom: 6 }}>
          <FileTextOutlined /> <span style={{ marginLeft: 6 }}>{task.filename}</span>
          <span style={{ marginLeft: 12, color: '#94a3b8' }}>· {task.format.toUpperCase()}</span>
        </div>
        <Progress
          percent={task.progress}
          status={colorMap[task.status] || 'normal'}
          size="small"
        />
        <div style={{ marginTop: 6, fontSize: 12, color: '#64748b' }}>
          {textMap[task.status] || task.status}
          {task.imported_rows != null && task.status === 'done' && ` · 已导入 ${task.imported_rows} 行`}
        </div>
        {task.error_message && (
          <Alert type="error" message={task.error_message} style={{ marginTop: 8, padding: '4px 10px' }} showIcon />
        )}
      </div>
    )
  }

  // ── 渲染：预览面板 ──
  const renderPreview = () => {
    if (!task || phase !== 'preview') return null
    const report = (task as ImportTaskInfo & { validation_report?: ValidationReport }).validation_report
    if (!report) return null

    const hasErrors = report.error_count > 0

    const valid = report.valid_count
    const warning = report.warning_count
    const error = report.error_count

    return (
      <div style={{ marginTop: 16 }}>
        {/* 统计卡片 */}
        <div style={{ display: 'flex', gap: 12, marginBottom: 16 }}>
          <div style={{ flex: 1, padding: 12, background: '#f0fdf4', borderRadius: 8, textAlign: 'center' }}>
            <div style={{ fontSize: 20, fontWeight: 700, color: '#16a34a' }}>{valid}</div>
            <div style={{ fontSize: 12, color: '#166534' }}><CheckCircleOutlined /> 可导入</div>
          </div>
          {warning > 0 && (
            <div style={{ flex: 1, padding: 12, background: '#fffbeb', borderRadius: 8, textAlign: 'center' }}>
              <div style={{ fontSize: 20, fontWeight: 700, color: '#d97706' }}>{warning}</div>
              <div style={{ fontSize: 12, color: '#92400e' }}><ExclamationCircleOutlined /> 警告</div>
            </div>
          )}
          {hasErrors && (
            <div style={{ flex: 1, padding: 12, background: '#fef2f2', borderRadius: 8, textAlign: 'center' }}>
              <div style={{ fontSize: 20, fontWeight: 700, color: '#dc2626' }}>{error}</div>
              <div style={{ fontSize: 12, color: '#991b1b' }}><CloseCircleOutlined /> 错误</div>
            </div>
          )}
        </div>

        {/* 跳过的列 */}
        {(report.skipped_columns.length > 0 || report.missing_required.length > 0) && (
          <Alert
            type="warning"
            style={{ marginBottom: 12 }}
            showIcon
            message={
              <div style={{ fontSize: 12 }}>
                {report.skipped_columns.length > 0 && (
                  <div>
                    <Tag color="orange">已忽略的文件列</Tag>
                    {report.skipped_columns.join(', ')}
                  </div>
                )}
                {report.missing_required.length > 0 && (
                  <div>
                    <Tag color="red">必填但文件缺失</Tag>
                    {report.missing_required.join(', ')}
                  </div>
                )}
              </div>
            }
          />
        )}

        {/* 错误/警告折叠列表 */}
        {(report.errors.length > 0 || report.warnings.length > 0) && (
          <Collapse
            size="small"
            style={{ marginBottom: 12 }}
            items={[
              {
                key: 'errors',
                label: `错误明细 (${report.errors.length})`,
                children: (
                  <Table
                    size="small"
                    pagination={{ pageSize: 10 }}
                    dataSource={report.errors}
                    rowKey={(_, i) => `e${i}`}
                    columns={[
                      { title: '行号', dataIndex: 'row_number', width: 80 },
                      { title: '字段', dataIndex: 'field', width: 120 },
                      { title: '原因', dataIndex: 'message' },
                    ]}
                  />
                ),
              },
              ...(report.warnings.length > 0 ? [{
                key: 'warnings',
                label: `警告明细 (${report.warnings.length})`,
                children: (
                  <Table
                    size="small"
                    pagination={{ pageSize: 10 }}
                    dataSource={report.warnings}
                    rowKey={(_, i) => `w${i}`}
                    columns={[
                      { title: '行号', dataIndex: 'row_number', width: 80 },
                      { title: '字段', dataIndex: 'field', width: 120 },
                      { title: '原因', dataIndex: 'message' },
                    ]}
                  />
                ),
              }] : []),
            ]}
          />
        )}

        {/* 操作按钮 */}
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 12 }}>
          <Button onClick={handleReset}>取消</Button>
          {hasErrors && (
            <Button onClick={handleDownloadFailed} icon={<DownloadOutlined />}>下载失败行</Button>
          )}
          <Button
            type="primary"
            onClick={handleConfirm}
            disabled={valid === 0}
          >
            确认导入（{valid} 行）
          </Button>
        </div>
      </div>
    )
  }

  // ── 导入 Tab 内容 ──
  const importTab = (
    <div>
      {phase === 'idle' && (
        <>
          <Dragger
            multiple={false}
            accept={ACCEPTED_EXT.join(',')}
            beforeUpload={beforeUpload}
          >
            <p className="ant-upload-drag-icon"><InboxOutlined /></p>
            <p className="ant-upload-text">点击或拖拽文件到此处</p>
            <p className="ant-upload-hint">支持 CSV / JSON / XLSX — 导入前会先校验并展示预览</p>
          </Dragger>
        </>
      )}

      {(phase === 'analyzing' || phase === 'importing') && (
        <Alert
          type="info"
          message="处理中..."
          style={{ marginTop: 12 }}
          showIcon
        />
      )}

      {renderStatusBar()}
      {phase === 'preview' && renderPreview()}

      {(phase === 'done' || phase === 'failed') && (
        <div style={{ marginTop: 16, textAlign: 'center' }}>
          <Space>
            <Button onClick={handleReset}>导入另一份</Button>
            <Button type="primary" onClick={onClose}>关闭</Button>
          </Space>
        </div>
      )}
    </div>
  )

  return (
    <Modal
      title="导入 / 导出"
      open={open}
      onCancel={onClose}
      footer={[<Button key="close" onClick={onClose}>关闭</Button>]}
      width={720}
      destroyOnHidden
    >
      <Tabs
        items={[
          {
            key: 'import',
            label: <span><UploadOutlined /> 导入到当前表</span>,
            children: importTab,
          },
          {
            key: 'export',
            label: <span><DownloadOutlined /> 导出</span>,
            children: (
              <div>
                <Empty
                  description={
                    <span style={{ color: '#64748b' }}>
                      将表中的数据导出为所选格式（最多 10000 行）
                    </span>
                  }
                />
                {viewId != null && (
                  <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '8px 12px', background: '#f1f5f9', borderRadius: 6, marginBottom: 8 }}>
                    <Switch size="small" checked={useViewFilter} onChange={setUseViewFilter} />
                    <span style={{ fontSize: 13, color: '#334155' }}>
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
            ),
          },
          {
            key: 'api',
            label: <span><ApiOutlined /> API 抓取追加</span>,
            children: (
              <ApiImportDialog
                embed
                wid={wid}
                tid={tid}
                title="API 抓取 · 追加到当前表"
                onSuccess={() => onImported?.()}
              />
            ),
          },
        ]}
      />
    </Modal>
  )
}
