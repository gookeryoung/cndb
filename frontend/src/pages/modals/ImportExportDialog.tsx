/** 导入/导出对话框 — 文件上传 + 异步进度轮询 + 多格式导出. */

import { useCallback, useEffect, useRef, useState } from 'react'
import { Modal, Tabs, Button, Progress, message, Space, Select, Alert, Empty, Upload } from 'antd'
import { InboxOutlined, UploadOutlined, DownloadOutlined, FileTextOutlined } from '@ant-design/icons'
import { importApi, exportApi } from '@/api'
import type { ImportTaskInfo } from '@/api'

const { Dragger } = Upload

interface Props {
  open: boolean
  wid: string
  tid: string
  onClose: () => void
  /** 导入成功后调用（刷新列表等） */
  onImported?: () => void
}

/** 允许的导入文件扩展名 */
const ACCEPTED_EXT = ['.csv', '.json', '.xlsx', '.xls']

export default function ImportExportDialog({ open, wid, tid, onClose, onImported }: Props) {
  const [task, setTask] = useState<ImportTaskInfo | null>(null)
  const [polling, setPolling] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [selectedFormat, setSelectedFormat] = useState<'json' | 'csv' | 'xlsx'>('csv')
  const pollTimer = useRef<number | null>(null)

  // 关闭时清理轮询
  useEffect(() => {
    if (!open) {
      if (pollTimer.current) {
        clearInterval(pollTimer.current)
        pollTimer.current = null
      }
      setTask(null)
      setPolling(false)
    }
  }, [open])

  // 轮询任务进度
  useEffect(() => {
    if (!polling || !task) return
    pollTimer.current = window.setInterval(async () => {
      try {
        const info = await importApi.getTask(wid, tid, task.task_id)
        setTask(info)
        if (info.status === 'done' || info.status === 'failed') {
          setPolling(false)
          if (pollTimer.current) {
            clearInterval(pollTimer.current)
            pollTimer.current = null
          }
          if (info.status === 'done') {
            message.success(`导入完成：${info.imported_rows ?? 0} 行`)
            onImported?.()
          } else {
            message.error(`导入失败：${info.error_message ?? '未知错误'}`)
          }
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

  // 用 any 绕过 antd Upload 复杂类型（运行时行为正确）
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const beforeUpload = useCallback((file: any) => {
    const name: string = file?.name?.toLowerCase() || ''
    if (!ACCEPTED_EXT.some(ext => name.endsWith(ext))) {
      message.error(`仅支持 ${ACCEPTED_EXT.join(' / ')} 文件`)
      return false
    }
    // 手动发起上传
    importApi.asyncImport(wid, tid, file as File)
      .then((info) => {
        setTask(info)
        setPolling(true)
      })
      .catch((err: unknown) => {
        const msg = err instanceof Error ? err.message : '导入失败'
        message.error(msg)
      })
    // 返回 false 阻止自动上传
    return false
  }, [wid, tid])

  const handleExport = useCallback(async () => {
    try {
      setExporting(true)
      const blob = await exportApi.download(wid, tid, selectedFormat)
      // 触发浏览器下载
      const url = URL.createObjectURL(blob as Blob)
      const a = document.createElement('a')
      a.href = url
      const tableName = `table-${tid}`
      const extMap: Record<string, string> = { json: '.json', csv: '.csv', xlsx: '.xlsx' }
      a.download = `${tableName}-export${extMap[selectedFormat]}`
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
  }, [wid, tid, selectedFormat])

  // ── 导入进度视图 ──
  const renderProgress = () => {
    if (!task) return null
    const statusColorMap: Record<string, 'success' | 'exception' | 'active' | 'normal'> = {
      pending: 'active',
      running: 'active',
      done: 'success',
      failed: 'exception',
    }
    const statusTextMap: Record<string, string> = {
      pending: '排队中',
      running: '导入中',
      done: '已完成',
      failed: '失败',
    }
    return (
      <div style={{ marginTop: 16, padding: 16, background: '#f6f8fa', borderRadius: 8 }}>
        <div style={{ marginBottom: 8, fontSize: 13, color: '#475569' }}>
          <FileTextOutlined /> <span style={{ marginLeft: 6 }}>{task.filename}</span>
          <span style={{ marginLeft: 12, color: '#94a3b8' }}>· {task.format.toUpperCase()}</span>
        </div>
        <Progress percent={task.progress} status={statusColorMap[task.status]} />
        <div style={{ marginTop: 8, fontSize: 12, color: '#64748b' }}>
          {statusTextMap[task.status]} · 已导入 {task.imported_rows ?? 0} / {task.total_rows ?? '?'} 行
        </div>
        {task.error_message && (
          <Alert type="error" message={task.error_message} style={{ marginTop: 8 }} showIcon />
        )}
      </div>
    )
  }

  return (
    <Modal
      title="导入 / 导出"
      open={open}
      onCancel={onClose}
      footer={[<Button key="close" onClick={onClose}>关闭</Button>]}
      width={620}
      destroyOnHidden
    >
      <Tabs
        items={[
          {
            key: 'import',
            label: <span><UploadOutlined /> 导入到当前表</span>,
            children: (
              <div>
                <Dragger
                  multiple={false}
                  accept={ACCEPTED_EXT.join(',')}
                  beforeUpload={beforeUpload}
                  disabled={polling}
                  showUploadList={!polling && !task}
                >
                  <p className="ant-upload-drag-icon"><InboxOutlined /></p>
                  <p className="ant-upload-text">点击或拖拽文件到此处</p>
                  <p className="ant-upload-hint">支持 CSV / JSON / XLSX，将追加到当前表</p>
                </Dragger>

                {polling && (
                  <Alert
                    type="info"
                    message="导入进行中，可关闭此对话框，返回列表查看进度"
                    style={{ marginTop: 12 }}
                    showIcon
                  />
                )}
                {renderProgress()}
              </div>
            ),
          },
          {
            key: 'export',
            label: <span><DownloadOutlined /> 导出</span>,
            children: (
              <div>
                <Empty
                  description={
                    <span style={{ color: '#64748b' }}>
                      将当前表的全部行数据导出为所选格式（最多 10000 行）
                    </span>
                  }
                />
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
        ]}
      />
    </Modal>
  )
}
