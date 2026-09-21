/** 系统管理台 — 系统信息 / 完整备份 / 完整恢复. */

import { useState } from 'react'
import { Tabs, Card, Descriptions, Button, Switch, Select, Upload, Alert, App as AntApp, Progress, Typography, Space, Divider, Popconfirm, Tag, Result } from 'antd'
import {
  DatabaseOutlined, CloudUploadOutlined, CloudDownloadOutlined,
  InfoCircleOutlined, InboxOutlined, ExclamationCircleOutlined,
  ReloadOutlined, FileZipOutlined, WarningOutlined, SafetyOutlined,
} from '@ant-design/icons'
import { useQuery, useMutation } from '@tanstack/react-query'
import { adminApi } from '@/api'
import { useAuthStore } from '@/store'
import type { BackupManifest } from '@/api'

const { Text, Title } = Typography

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(2)} MB`
}

export default function AdminPanel() {
  const { message, modal } = AntApp.useApp()
  const user = useAuthStore(s => s.user)
  const isAdmin = !!user && (user.is_superuser || user.role === 'system_admin')

  // ── 所有 Hook 必须在任何条件 return 之前声明 ──
  // ── 系统信息 ──
  const { data: info, isLoading: infoLoading } = useQuery({
    queryKey: ['admin-system-info'],
    queryFn: adminApi.info,
    enabled: isAdmin,
  })

  // ── 备份表单状态 ──
  const [includeUploads, setIncludeUploads] = useState(true)
  const [backupMode, setBackupMode] = useState('auto')
  const [backupProgress, setBackupProgress] = useState(false)

  const backupMutation = useMutation({
    mutationFn: () => adminApi.backup({ include_uploads: includeUploads, mode: backupMode }),
    onMutate: () => { setBackupProgress(true) },
    onSuccess: (blob) => {
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      const ts = new Date().toISOString().replace(/[:.]/g, '-')
      a.download = `cndb-backup-${ts}.tar.gz`
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)
      message.success('系统备份已生成并开始下载')
      setBackupProgress(false)
    },
    onError: (err) => {
      message.error(err instanceof Error ? err.message : '备份失败')
      setBackupProgress(false)
    },
  })

  // ── 恢复表单状态 ──
  const [restoreFile, setRestoreFile] = useState<File | null>(null)
  const [manifest, setManifest] = useState<BackupManifest | null>(null)
  const [restoring, setRestoring] = useState(false)
  // 恢复模式：auto 跟随备份标记；备份 schema 领先时校验通过自动切 sqlalchemy 降级
  const [restoreMode, setRestoreMode] = useState('auto')

  const inspectMutation = useMutation({
    mutationFn: (file: File) => adminApi.restoreInspect(file),
    onSuccess: (data) => {
      setManifest(data)
      if (data.backup_ahead) setRestoreMode('sqlalchemy')
      message.success('备份文件校验通过')
    },
    onError: (err) => {
      setManifest(null)
      message.error(err instanceof Error ? err.message : '备份文件校验失败')
    },
  })

  const restoreMutation = useMutation({
    mutationFn: (file: File) =>
      adminApi.restore(file, true, restoreMode === 'auto' ? undefined : restoreMode),
    onMutate: () => { setRestoring(true) },
    onSuccess: (data) => {
      setRestoring(false)
      setRestoreFile(null)
      setManifest(null)
      setRestoreMode('auto')
      if (data.loss_report) {
        // 降级恢复：交集导入裁剪了数据，弹窗显式呈现丢失面
        modal.warning({
          title: '降级恢复完成 — 已裁剪部分数据',
          width: 560,
          content: (
            <div style={{ whiteSpace: 'pre-wrap', fontSize: 13 }}>
              {data.loss_report.summary}
            </div>
          ),
          okText: '知道了',
        })
      } else {
        message.success(data.message || '系统恢复完成')
      }
    },
    onError: (err) => {
      message.error(err instanceof Error ? err.message : '恢复失败')
      setRestoring(false)
    },
  })

  // 权限检查 —— 非系统管理员无权访问（所有 Hook 已声明完毕）
  if (!isAdmin) {
    return (
      <div style={{ padding: 48, display: 'flex', justifyContent: 'center' }} data-testid="admin-panel">
        <Result
          status="403"
          icon={<SafetyOutlined />}
          title="无权访问系统管理台"
          subTitle="系统备份与恢复需要 system_admin 或 superuser 权限。请联系系统管理员。"
        />
      </div>
    )
  }

  const handleRestoreFile = async (file: File) => {
    setRestoreFile(file)
    setManifest(null)
    await inspectMutation.mutateAsync(file)
    return false  // 阻止自动上传
  }

  const backupTab = (
    <div style={{ padding: '8px 0' }}>
      <Alert
        type="info"
        showIcon
        icon={<InfoCircleOutlined />}
        message="系统级完整备份"
        description="将打包整个数据库（全部工作区、表、数据行、配置）以及附件目录 uploads/。导出为 .tar.gz 文件，包含 manifest.json 元信息。"
        style={{ marginBottom: 16 }}
      />

      <Card size="small" title={<span><FileZipOutlined /> 备份选项</span>} style={{ marginBottom: 16 }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <Text>备份模式：</Text>
            <Select
              value={backupMode}
              onChange={setBackupMode}
              style={{ width: 200 }}
              options={[
                { value: 'auto', label: 'auto（自动选择，推荐）' },
                { value: 'native', label: 'native（SQLite 直接文件复制，最快）' },
                { value: 'sqlalchemy', label: 'sqlalchemy（跨数据库兼容）' },
              ]}
            />
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <Switch checked={includeUploads} onChange={setIncludeUploads} />
            <span>包含 uploads 附件目录（{info?.data_dir ? `位于 ${info.upload_dir}` : '…'}）</span>
          </div>
        </div>
      </Card>

      <Space>
        <Button
          type="primary"
          size="large"
          icon={<CloudDownloadOutlined />}
          loading={backupProgress}
          onClick={() => backupMutation.mutate()}
        >
          立即备份并下载
        </Button>
        <Text type="secondary" style={{ fontSize: 12 }}>
          备份文件为 .tar.gz 格式，恢复时可直接上传
        </Text>
      </Space>

      {backupProgress && (
        <div style={{ marginTop: 16 }}>
          <Progress percent={100} status="active" showInfo={false} />
          <Text type="secondary" style={{ fontSize: 12 }}>服务器正在生成备份，请稍候…</Text>
        </div>
      )}

      <Divider />

      <Alert
        type="warning"
        showIcon
        icon={<WarningOutlined />}
        message="备份也可以通过 CLI 完成"
        description={
          <div style={{ fontSize: 13 }}>
            Web 管理台输出 .tar.gz 方便下载；若需要直接备份到服务器文件夹（不压缩），请在服务器终端执行：
            <br />
            <code style={{ background: '#f5f5f5', padding: '2px 6px', borderRadius: 4 }}>cndb backup --dir -o /path/to/backup_dir</code>
          </div>
        }
      />
    </div>
  )

  const restoreTab = (
    <div style={{ padding: '8px 0' }}>
      <Alert
        type="error"
        showIcon
        icon={<ExclamationCircleOutlined />}
        message="破坏性操作 — 恢复将覆盖当前数据库"
        description="请确保已备份当前数据。恢复后原有工作区、表结构、数据行将全部被替换为备份中的内容。"
        style={{ marginBottom: 16 }}
      />

      {!restoreFile ? (
        <Upload.Dragger
          multiple={false}
          accept=".tar.gz,.tgz"
          beforeUpload={handleRestoreFile}
          disabled={restoring}
          showUploadList={false}
          style={{ padding: 24 }}
        >
          <p className="ant-upload-drag-icon"><InboxOutlined /></p>
          <p className="ant-upload-text">点击或拖拽备份文件到此处</p>
          <p className="ant-upload-hint">
            支持 .tar.gz / .tgz 格式 — 将先校验完整性并展示内容摘要，确认后再执行恢复
          </p>
        </Upload.Dragger>
      ) : (
        <Card
          size="small"
          title={<span><DatabaseOutlined /> 已选择备份文件：{restoreFile.name}</span>}
          extra={
            <Button size="small" onClick={() => { setRestoreFile(null); setManifest(null) }}>
              重新选择
            </Button>
          }
        >
          {manifest ? (
            <>
              {manifest.backup_ahead && (
                <Alert
                  type="warning"
                  showIcon
                  icon={<WarningOutlined />}
                  message="备份 schema 新于当前程序"
                  description="该备份由更新版本的程序生成，native 模式恢复将失败。已自动选择 sqlalchemy 模式降级恢复（按交集导入，丢弃备份中新增表/列的数据）。"
                  style={{ marginBottom: 12 }}
                />
              )}
              <Descriptions column={2} size="small" bordered>
                <Descriptions.Item label="备份版本">{manifest.version}</Descriptions.Item>
                <Descriptions.Item label="应用版本">{manifest.app_version}</Descriptions.Item>
                <Descriptions.Item label="创建时间">
                  {new Date(manifest.created_at).toLocaleString()}
                </Descriptions.Item>
                <Descriptions.Item label="数据库类型">
                  {manifest.database.db_type}（{manifest.database.backup_mode}）
                </Descriptions.Item>
                <Descriptions.Item label="Schema 版本">
                  {manifest.database.schema_version || <Tag>未知（旧版备份）</Tag>}
                </Descriptions.Item>
                <Descriptions.Item label="内嵌兜底导出">
                  {manifest.database.fallback_mode
                    ? <Tag color="blue">有（{manifest.database.fallback_mode}）</Tag>
                    : <Tag>无</Tag>}
                </Descriptions.Item>
                <Descriptions.Item label="数据表数">{manifest.database.tables.length}</Descriptions.Item>
                <Descriptions.Item label="总行数">
                  {Object.values(manifest.database.row_counts).reduce((a, b) => a + b, 0).toLocaleString()}
                </Descriptions.Item>
                <Descriptions.Item label="附件" span={2}>
                  {manifest.uploads.included
                    ? `${manifest.uploads.file_count} 个文件，共 ${formatSize(manifest.uploads.total_size)}`
                    : <Tag>未包含</Tag>}
                </Descriptions.Item>
              </Descriptions>

              <div style={{ marginTop: 12, display: 'flex', alignItems: 'center', gap: 12 }}>
                <Text>恢复模式：</Text>
                <Select
                  value={restoreMode}
                  onChange={setRestoreMode}
                  disabled={restoring}
                  style={{ width: 320 }}
                  options={[
                    { value: 'auto', label: 'auto（跟随备份模式，推荐）' },
                    { value: 'native', label: 'native（SQLite 直接文件覆盖）' },
                    { value: 'sqlalchemy', label: 'sqlalchemy（交集导入，可降级恢复）' },
                  ]}
                />
              </div>

              {manifest.database.tables.length > 0 && (
                <div style={{ marginTop: 12 }}>
                  <Text strong style={{ fontSize: 12 }}>表清单：</Text>
                  <div style={{ marginTop: 4, display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                    {manifest.database.tables.map(t => (
                      <Tag key={t} style={{ marginRight: 0 }}>
                        {t} ({manifest.database.row_counts[t] ?? 0})
                      </Tag>
                    ))}
                  </div>
                </div>
              )}

              <Divider />

              <Popconfirm
                title={<span style={{ color: '#dc2626' }}>确认覆盖当前数据库？</span>}
                description="此操作不可撤销，所有现有数据将被替换为备份内容。建议先做一次备份。"
                okText="确认恢复"
                okType="danger"
                cancelText="取消"
                icon={<ExclamationCircleOutlined style={{ color: '#dc2626' }} />}
                onConfirm={() => restoreMutation.mutate(restoreFile)}
                disabled={restoring}
              >
                <Button
                  danger
                  type="primary"
                  size="large"
                  icon={<ReloadOutlined />}
                  loading={restoring}
                >
                  {restoring ? '正在恢复…' : '执行系统恢复（覆盖）'}
                </Button>
              </Popconfirm>
            </>
          ) : (
            <div style={{ color: '#64748b', padding: '24px 0', textAlign: 'center' }}>
              正在校验备份文件…
            </div>
          )}
        </Card>
      )}

      {(inspectMutation.isPending) && (
        <div style={{ marginTop: 16 }}>
          <Progress percent={100} status="active" showInfo={false} />
        </div>
      )}
      {restoring && (
        <div style={{ marginTop: 16 }}>
          <Alert type="info" message="正在恢复系统数据，请勿关闭页面…" showIcon />
        </div>
      )}

      <Divider />
      <Alert
        type="info"
        showIcon
        message="从文件夹恢复（CLI）"
        description="如果你是用 `cndb backup --dir -o <路径>` 备份到服务器文件夹的，可以直接恢复："
        style={{ marginTop: 12 }}
      />
      <div style={{ marginTop: 8, fontSize: 13 }}>
        <code style={{ background: '#f5f5f5', padding: '2px 6px', borderRadius: 4 }}>cndb restore /path/to/backup_dir --force</code>
      </div>
    </div>
  )

  const infoTab = (
    <div style={{ padding: '8px 0' }}>
      <Card size="small" title={<span><InfoCircleOutlined /> 系统运行信息</span>} loading={infoLoading}>
        {info && (
          <Descriptions column={2} size="small" bordered>
            <Descriptions.Item label="应用名称">{info.app_name}</Descriptions.Item>
            <Descriptions.Item label="版本">{info.app_version}</Descriptions.Item>
            <Descriptions.Item label="数据库" span={2}>
              <code>{info.database_url}</code>
            </Descriptions.Item>
            <Descriptions.Item label="数据目录" span={2}>
              <code>{info.data_dir}</code>
            </Descriptions.Item>
            <Descriptions.Item label="附件目录" span={2}>
              <code>{info.upload_dir}</code>
            </Descriptions.Item>
            <Descriptions.Item label="认证">
              {info.auth_enabled ? <Tag color="green">已启用</Tag> : <Tag>未启用（开放访问）</Tag>}
            </Descriptions.Item>
            <Descriptions.Item label="时区">{info.timezone}</Descriptions.Item>
          </Descriptions>
        )}
      </Card>
    </div>
  )

  return (
    <div style={{ padding: 24, maxWidth: 960 }} data-testid="admin-panel">
      <Title level={3} style={{ marginBottom: 4 }}>系统管理台</Title>
      <Text type="secondary">完整备份、恢复与系统运行信息查看。以下操作需要系统管理员权限。</Text>

      <Card style={{ marginTop: 16 }}>
        <Tabs
          items={[
            {
              key: 'info',
              label: <span><InfoCircleOutlined /> 系统信息</span>,
              children: infoTab,
            },
            {
              key: 'backup',
              label: <span><CloudDownloadOutlined /> 系统备份</span>,
              children: backupTab,
            },
            {
              key: 'restore',
              label: <span><CloudUploadOutlined /> 系统恢复</span>,
              children: restoreTab,
            },
          ]}
        />
      </Card>
    </div>
  )
}
