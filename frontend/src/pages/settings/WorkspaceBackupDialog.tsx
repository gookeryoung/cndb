/** 工作区备份对话框 — 全量归档备份（tar.gz；恢复入口已移入「导入工作区」，仅保留备份）.
 *
 * 归档包含工作区全部内容（表 / 数据 / 视图 / 文档及版本历史 / 草稿 / 回收站 / 议题 /
 * 附件 / 设计 / 采集策略等）；恢复或导入统一走工作区列表页的「导入工作区」：
 * 导入为新工作区（推荐），或当同名工作区已存在且当前用户为 owner 时覆盖恢复。
 */

import { useState } from 'react'
import { Modal, Button, App as AntApp, Space, Alert, Switch, Typography } from 'antd'
import { DownloadOutlined } from '@ant-design/icons'
import { workspaceApi } from '@/api'

const { Text } = Typography

interface Props {
  open: boolean
  wid: string
  workspaceName?: string
  onClose: () => void
}

/** 触发浏览器下载 Blob 文件 */
function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

export default function WorkspaceBackupDialog({ open, wid, workspaceName, onClose }: Props) {
  const { message } = AntApp.useApp()
  const [includeSecrets, setIncludeSecrets] = useState(true)
  const [exporting, setExporting] = useState(false)

  const safeName = (workspaceName || `workspace-${wid}`).replace(/[^\w\u4e00-\u9fa5-]/g, '_')

  const handleExport = async () => {
    try {
      setExporting(true)
      const blob = await workspaceApi.exportWorkspaceArchive(wid, includeSecrets)
      downloadBlob(blob, `${safeName}-archive-${Date.now()}.tar.gz`)
      message.success(includeSecrets
        ? '已下载全量归档（含密钥，请妥善保管）'
        : '已下载全量归档（密钥已剔除）')
    } catch (err) {
      message.error(err instanceof Error ? err.message : '归档备份失败')
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
      width={560}
      destroyOnHidden
    >
      <div style={{ padding: '8px 0' }}>
        <Alert
          type="info"
          showIcon
          title={`将备份整个工作区「${workspaceName || ''}」的完整数据`}
          description="备份格式为全量归档（.tar.gz），包含：数据表结构与数据、字段 / 视图 / 表权限配置，文档（含标签、版本历史、草稿、回收站）、置顶 / 分享 / 议题、数据源会话与同步游标、设计文件与采集策略、附件与外存正文。"
          style={{ marginBottom: 12 }}
        />
        <Space style={{ width: '100%', justifyContent: 'space-between', marginBottom: 8 }}>
          <Space>
            <Switch checked={includeSecrets} onChange={setIncludeSecrets} />
            <Text type={includeSecrets ? 'warning' : 'secondary'} style={{ fontSize: 'var(--cn-text-sm)' }}>
              包含数据源密钥{includeSecrets ? '（导出文件含敏感信息）' : '（导出后密钥为空）'}
            </Text>
          </Space>
          <Button
            type="primary"
            icon={<DownloadOutlined />}
            loading={exporting}
            onClick={handleExport}
          >下载全量归档（.tar.gz）</Button>
        </Space>
      </div>
    </Modal>
  )
}
