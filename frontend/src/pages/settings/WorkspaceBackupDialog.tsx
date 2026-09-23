/** 工作区备份对话框 — 仅保留 JSON 导出功能，导入工作区统一移至工作区列表页顶部按钮. */

import { useState } from 'react'
import { Modal, Button, App as AntApp, Space, Alert } from 'antd'
import { DownloadOutlined } from '@ant-design/icons'
import { workspaceApi } from '@/api'

interface Props {
  open: boolean
  wid: string
  workspaceName?: string
  onClose: () => void
}

export default function WorkspaceBackupDialog({ open, wid, workspaceName, onClose }: Props) {
  const { message } = AntApp.useApp()
  const [exporting, setExporting] = useState(false)

  const handleExport = async () => {
    try {
      setExporting(true)
      const data = await workspaceApi.exportWorkspace(wid)
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
      message.success(`已备份 ${data.tables.length} 张表`)
    } catch (err) {
      message.error(err instanceof Error ? err.message : '备份失败')
    } finally {
      setExporting(false)
    }
  }

  return (
    <Modal
      title="备份工作区"
      open={open}
      onCancel={onClose}
      footer={[<Button key="close" onClick={onClose}>关闭</Button>]}
      width={520}
      destroyOnHidden
    >
      <div style={{ padding: '8px 0' }}>
        <Alert
          type="info"
          showIcon
          message={`将备份整个工作区「${workspaceName || ''}」的完整数据`}
          description="包含所有数据表结构、字段配置、数据行和视图配置，导出为 JSON 文件。可在工作区列表页通过「导入工作区」恢复。"
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
    </Modal>
  )
}
