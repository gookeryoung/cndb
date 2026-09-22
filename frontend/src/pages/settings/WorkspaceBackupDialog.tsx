/** 工作区级整体导入/导出对话框 — JSON 格式备份与恢复. */

import { useState } from 'react'
import { Modal, Tabs, Button, App as AntApp, Upload, Space, Alert, Progress } from 'antd'
import { DownloadOutlined, UploadOutlined, InboxOutlined, FileTextOutlined } from '@ant-design/icons'
import { workspaceApi } from '@/api'
import type { WorkspaceExportData } from '@/api'

const { Dragger } = Upload

interface Props {
  open: boolean
  wid: string
  workspaceName?: string
  onClose: () => void
  /** 导入成功后刷新工作区列表 */
  onImported?: () => void
}

/** 允许导入的文件扩展名 */
const ACCEPTED_EXT = ['.json']

export default function WorkspaceBackupDialog({ open, wid, workspaceName, onClose, onImported }: Props) {
  const { message } = AntApp.useApp()
  const [exporting, setExporting] = useState(false)
  const [importing, setImporting] = useState(false)
  const [importResult, setImportResult] = useState<{ tables: number; rows: number; views: number } | null>(null)
  
  // 导出
  const handleExport = async () => {
    try {
      setExporting(true)
      const data: WorkspaceExportData = await workspaceApi.exportWorkspace(wid)
      // 触发浏览器下载
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      const safeName = (workspaceName || `workspace-${wid}`).replace(/[^\w\u4e00-\u9fa5-]/g, '_')
      a.download = `${safeName}-backup-${Date.now()}.json`
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)
      message.success(`已导出 ${data.tables.length} 张表`)
    } catch (err) {
      message.error(err instanceof Error ? err.message : '导出失败')
    } finally {
      setExporting(false)
    }
  }

  // 导入
  const beforeUpload = async (file: File) => {
    const name = file.name.toLowerCase()
    if (!ACCEPTED_EXT.some(ext => name.endsWith(ext))) {
      message.error('仅支持 JSON 文件')
      return false
    }

    try {
      setImporting(true)
      setImportResult(null)
      const text = await file.text()
      const json = JSON.parse(text)
      const result = await workspaceApi.importWorkspace(wid, json)
      setImportResult({
        tables: result.imported_tables,
        rows: result.imported_rows,
        views: result.imported_views,
      })
      message.success(`导入完成：${result.imported_tables} 表 / ${result.imported_rows} 行 / ${result.imported_views} 视图`)
      onImported?.()
    } catch (err) {
      const msg = err instanceof Error ? err.message : '导入失败'
      message.error(msg)
    } finally {
      setImporting(false)
    }
    // 返回 false 阻止 Upload 组件自动上传
    return false
  }

  return (
    <Modal
      title="工作区导入 / 导出"
      open={open}
      onCancel={() => { setImportResult(null); onClose() }}
      footer={[<Button key="close" onClick={() => { setImportResult(null); onClose() }}>关闭</Button>]}
      width={600}
      destroyOnHidden
    >
      <Tabs
        items={[
          {
            key: 'export',
            label: <span><DownloadOutlined /> 导出工作区</span>,
            children: (
              <div style={{ padding: '16px 0' }}>
                <Alert
                  type="info"
                  showIcon
                  message="将导出整个工作区的完整数据"
                  description="包含所有数据表结构、字段配置、数据行和视图配置，导出为 JSON 文件。"
                  style={{ marginBottom: 16 }}
                />
                <Space style={{ width: '100%', justifyContent: 'center' }}>
                  <Button
                    type="primary"
                    icon={<DownloadOutlined />}
                    loading={exporting}
                    size="large"
                    onClick={handleExport}
                  >下载 JSON 备份</Button>
                </Space>
              </div>
            ),
          },
          {
            key: 'import',
            label: <span><UploadOutlined /> 导入到工作区</span>,
            children: (
              <div style={{ padding: '16px 0' }}>
                <Alert
                  type="warning"
                  showIcon
                  message="导入注意事项"
                  description="同名的表会被跳过，不会覆盖现有数据。导入后可在工作区内查看新增的表。"
                  style={{ marginBottom: 16 }}
                />

                <Dragger
                  multiple={false}
                  accept={ACCEPTED_EXT.join(',')}
                  beforeUpload={beforeUpload}
                  disabled={importing}
                  showUploadList={false}
                >
                  <p className="ant-upload-drag-icon"><InboxOutlined /></p>
                  <p className="ant-upload-text">点击或拖拽 JSON 备份文件到此处</p>
                  <p className="ant-upload-hint">从之前导出的 JSON 备份恢复工作区数据</p>
                </Dragger>

                {importing && (
                  <div style={{ marginTop: 16 }}>
                    <Progress percent={100} status="active" showInfo={false} />
                    <div style={{ textAlign: 'center', marginTop: 8, color: '#64748b' }}>正在导入...</div>
                  </div>
                )}

                {importResult && !importing && (
                  <div style={{ marginTop: 16, padding: 16, background: '#f0fdf4', borderRadius: 8 }}>
                    <FileTextOutlined style={{ color: '#22c55e', fontSize: 20 }} />
                    <span style={{ marginLeft: 8, color: '#15803d' }}>
                      导入完成：{importResult.tables} 表 / {importResult.rows} 行 / {importResult.views} 视图
                    </span>
                  </div>
                )}
              </div>
            ),
          },
        ]}
      />
    </Modal>
  )
}
