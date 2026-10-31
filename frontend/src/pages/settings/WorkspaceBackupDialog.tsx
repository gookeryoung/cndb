/** 工作区备份对话框 — JSON 备份 / 全量归档备份（v9）/ 归档覆盖恢复（仅 owner）. */

import { useState } from 'react'
import { Modal, Button, App as AntApp, Space, Alert, Switch, Divider, Upload, Checkbox, Input, Typography } from 'antd'
import { DownloadOutlined, UploadOutlined, WarningOutlined } from '@ant-design/icons'
import { workspaceApi } from '@/api'
import type { WorkspaceRole } from '@/api/types'

const { Text } = Typography

interface Props {
  open: boolean
  wid: string
  workspaceName?: string
  /** 当前用户在该工作区的角色 — owner 才显示「恢复到本工作区」 */
  currentUserRole?: WorkspaceRole | null
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

export default function WorkspaceBackupDialog({
  open, wid, workspaceName, currentUserRole, onClose,
}: Props) {
  const { message } = AntApp.useApp()
  const [exporting, setExporting] = useState(false)
  const [includeSecrets, setIncludeSecrets] = useState(true)
  const [exportingArchive, setExportingArchive] = useState(false)
  const [restoring, setRestoring] = useState(false)
  const [restoreFile, setRestoreFile] = useState<File | null>(null)
  const [confirmChecked, setConfirmChecked] = useState(false)
  const [confirmName, setConfirmName] = useState('')

  const safeName = (workspaceName || `workspace-${wid}`).replace(/[^\w\u4e00-\u9fa5-]/g, '_')
  const isOwner = currentUserRole === 'owner'
  const restoreReady = !!restoreFile && confirmChecked && confirmName === (workspaceName || '')

  const handleExport = async () => {
    try {
      setExporting(true)
      const data = await workspaceApi.exportWorkspace(wid)
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
      downloadBlob(blob, `${safeName}-backup-${Date.now()}.json`)
      const docCount = data.documents?.length ?? 0
      message.success(`已备份 ${data.tables.length} 张表${docCount ? ` · ${docCount} 篇文档` : ''}`)
    } catch (err) {
      message.error(err instanceof Error ? err.message : '备份失败')
    } finally {
      setExporting(false)
    }
  }

  const handleExportArchive = async () => {
    try {
      setExportingArchive(true)
      const blob = await workspaceApi.exportWorkspaceArchive(wid, includeSecrets)
      downloadBlob(blob, `${safeName}-archive-${Date.now()}.tar.gz`)
      message.success(includeSecrets
        ? '已下载全量归档（含密钥，请妥善保管）'
        : '已下载全量归档（密钥已剔除）')
    } catch (err) {
      message.error(err instanceof Error ? err.message : '归档备份失败')
    } finally {
      setExportingArchive(false)
    }
  }

  const handleRestore = async () => {
    if (!restoreFile) return
    try {
      setRestoring(true)
      const resp = await workspaceApi.restoreWorkspace(wid, restoreFile)
      message.success(
        `恢复完成：${resp.imported_tables} 张表 · ${resp.imported_rows} 行${resp.errors?.length ? ` · ${resp.errors.length} 条警告` : ''}`,
      )
      setRestoreFile(null)
      setConfirmChecked(false)
      setConfirmName('')
      onClose()
    } catch (err) {
      message.error(err instanceof Error ? err.message : '恢复失败')
    } finally {
      setRestoring(false)
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
          description="包含所有数据表结构、字段配置、数据行、视图配置、表权限配置，以及文档（含标签与最新正文）。导出为 JSON 文件，可在工作区列表页通过「导入工作区」恢复。"
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

        <Divider plain>全量归档备份</Divider>

        <Alert
          type="success"
          showIcon
          title="归档备份（推荐）— 包含工作区全部内容"
          description="除 JSON 备份内容外，还包含：文档版本历史、草稿、回收站、置顶/分享/议题、数据源会话与同步游标、表成员、附件与外存正文。恢复时优先使用归档。"
          style={{ marginBottom: 12 }}
        />
        <Space style={{ width: '100%', justifyContent: 'space-between', marginBottom: 8 }}>
          <Space>
            <Switch checked={includeSecrets} onChange={setIncludeSecrets} />
            <Text type={includeSecrets ? 'warning' : 'secondary'} style={{ fontSize: 13 }}>
              包含数据源密钥{includeSecrets ? '（导出文件含敏感信息）' : '（导出后密钥为空）'}
            </Text>
          </Space>
          <Button
            icon={<DownloadOutlined />}
            loading={exportingArchive}
            onClick={handleExportArchive}
          >下载全量归档（.tar.gz）</Button>
        </Space>

        {isOwner && (
          <>
            <Divider plain>恢复到本工作区</Divider>
            <Alert
              type="error"
              showIcon
              icon={<WarningOutlined />}
              title="危险操作：覆盖恢复"
              description="将从归档全量重建本工作区：现有表、文档、数据源等业务数据会被全部删除后由归档内容替换，工作区名称与成员保持不变。仅工作区 owner 可执行。"
              style={{ marginBottom: 12 }}
            />
            <Space direction="vertical" style={{ width: '100%' }} size={8}>
              <Upload
                accept=".tar.gz,.gz"
                maxCount={1}
                beforeUpload={(file) => { setRestoreFile(file); return false }}
                onRemove={() => setRestoreFile(null)}
                fileList={restoreFile ? [{ uid: '-1', name: restoreFile.name }] : []}
              >
                <Button icon={<UploadOutlined />}>选择备份归档（.tar.gz）</Button>
              </Upload>
              <Checkbox
                checked={confirmChecked}
                onChange={(e) => setConfirmChecked(e.target.checked)}
              >我已知晓：恢复将清空本工作区现有全部业务数据，且不可撤销</Checkbox>
              <Input
                placeholder={`输入工作区名称「${workspaceName || ''}」以确认`}
                value={confirmName}
                onChange={(e) => setConfirmName(e.target.value)}
              />
              <Button
                type="primary"
                danger
                icon={<WarningOutlined />}
                disabled={!restoreReady}
                loading={restoring}
                onClick={handleRestore}
              >覆盖恢复本工作区</Button>
            </Space>
          </>
        )}
      </div>
    </Modal>
  )
}
