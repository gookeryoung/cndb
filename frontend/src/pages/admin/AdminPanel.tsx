/** 系统管理台 — 用户管理 / 事件流 / 系统信息 / 完整备份 / 完整恢复.
 *
 * 布局口径（与全站一致）：
 *   - 页面根 `·cn-admin`：撑满内容区高度的两栏布局；
 *   - 桌面端左侧是管理台自己的 SIDEBAR（240px，贴边占满高度，风格与工作区
 *     数据表 Sider 一致：bg-container 背景 + 右侧分隔线，选中态沿用
 *     `.cn-table-nav` 的品牌色指示条语言，可折叠为 60px 图标栏），窄屏折叠成
 *     可横滑的胶囊导航；
 *   - 内容列 = 页头（分区标题 + 说明 + 版本徽标）+ 分区内容，纵向 12px 节奏，
 *     滚动只发生在内容列（16px 留白，窄屏 12px）；
 *   - 分区状态写入 `?section=`：可深链、刷新保持，且不影响「事件流」自身的
 *     `?action=` / `?keyword=` 筛选参数。
 */

import { useState, type ReactNode } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  Card, Descriptions, Button, Switch, Upload, Alert, App as AntApp, Progress,
  Typography, Space, Popconfirm, Tag, Result, Select,
} from 'antd'
import {
  DatabaseOutlined, CloudUploadOutlined, CloudDownloadOutlined,
  InfoCircleOutlined, InboxOutlined, ExclamationCircleOutlined,
  ReloadOutlined, FileZipOutlined, WarningOutlined, SafetyOutlined,
  TeamOutlined, HistoryOutlined, HddOutlined, MenuFoldOutlined, MenuUnfoldOutlined,
} from '@ant-design/icons'
import { useQuery, useMutation } from '@tanstack/react-query'
import { adminApi } from '@/api'
import { useAuthStore } from '@/store'
import type { BackupManifest } from '@/api'
import UsersPage from './UsersPage'
import EventsPage from './EventsPage'
import StoragePage from './StoragePage'
import { useResponsive } from '@/hooks/useResponsive'
import { formatSize } from '@/utils/formatSize'

const { Text } = Typography

/** 管理台分区 —— 导航栏、页头文案与内容切换共用同一份定义. */
type AdminSectionKey = 'users' | 'events' | 'storage' | 'info' | 'backup' | 'restore'

interface AdminSection {
  key: AdminSectionKey
  label: string
  desc: string
  icon: ReactNode
}

const SECTIONS: readonly AdminSection[] = [
  { key: 'users', label: '用户管理', desc: '账号资料、角色与启停状态，变更全部写入操作日志。', icon: <TeamOutlined /> },
  { key: 'events', label: '事件流', desc: '跨插件统一事件视图，可按动作与关键词追溯一次请求。', icon: <HistoryOutlined /> },
  { key: 'storage', label: '空间分配', desc: '按工作区分配存储上限（默认 100MB），查看已用空间与使用率。', icon: <HddOutlined /> },
  { key: 'info', label: '系统信息', desc: '版本、数据库与存储路径等运行期信息。', icon: <InfoCircleOutlined /> },
  { key: 'backup', label: '系统备份', desc: '整库打包为 .tar.gz（含 manifest 元信息与附件目录）。', icon: <CloudDownloadOutlined /> },
  { key: 'restore', label: '系统恢复', desc: '校验备份包后覆盖式还原，操作不可撤销。', icon: <CloudUploadOutlined /> },
] as const

export default function AdminPanel() {
  const { message, modal } = AntApp.useApp()
  const user = useAuthStore(s => s.user)
  const isAdmin = !!user && (user.is_superuser || user.role === 'system_admin')
  // 窄屏：Descriptions 两列会把标签挤成竖排文字（「应用名称」一字一行），改单列 + 标签在上
  const { isMobile } = useResponsive()

  // 分区切换写进 URL —— 刷新/分享后停在同一个分区；缺省回落到用户管理
  const [searchParams, setSearchParams] = useSearchParams()
  const rawSection = searchParams.get('section')
  const section: AdminSectionKey = SECTIONS.some(s => s.key === rawSection)
    ? (rawSection as AdminSectionKey)
    : 'users'
  const activeSection = SECTIONS.find(s => s.key === section) ?? SECTIONS[0]

  const goSection = (key: AdminSectionKey) => {
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev)
      next.set('section', key)
      return next
    }, { replace: true })
  }

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

  // 侧栏折叠态 —— 与工作区数据表 Sider 的 collapsible 行为一致（60px 图标栏）
  const [railCollapsed, setRailCollapsed] = useState(false)

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
          title: '恢复完成 — 部分数据未导入',
          width: 560,
          content: (
            <div style={{ whiteSpace: 'pre-wrap', fontSize: 'var(--cn-text-sm)' }}>
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
      <div className="cn-page" data-testid="admin-panel">
        <Result
          status="403"
          icon={<SafetyOutlined />}
          title="无权访问系统管理台"
          subTitle="系统备份与恢复仅系统管理员可以操作，请联系系统管理员。"
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

  // 表清单分组：优先用后端分类结果；缺失时回退为全部归入系统表（兼容旧响应）
  const tableGroups = manifest?.table_groups ?? {
    system: manifest?.database.tables ?? [],
    user: [],
  }

  const backupTab = (
    <div className="cn-admin-section">
      <Alert
        type="info"
        showIcon
        icon={<InfoCircleOutlined />}
        message="系统级完整备份"
        description="将打包整个数据库（全部工作区、表、数据行、配置）以及附件目录 uploads/。导出为 .tar.gz 文件，包含 manifest.json 元信息。"
      />

      <Card size="small" title={<span><FileZipOutlined /> 备份选项</span>}>
        <div className="cn-field">
          <span className="cn-field-label">备份模式</span>
          <Select
            value={backupMode}
            onChange={setBackupMode}
            style={{ width: isMobile ? '100%' : 280 }}
            options={[
              { value: 'auto', label: '自动选择（推荐）' },
              { value: 'native', label: '完整备份（打包整个数据库文件，最快）' },
              { value: 'sqlalchemy', label: '兼容备份（逐表导出，适用面更广）' },
            ]}
          />
        </div>
        <div className="cn-field">
          <span className="cn-field-label">附件目录</span>
          <Space size={8} wrap>
            <Switch checked={includeUploads} onChange={setIncludeUploads} />
            <Text type="secondary">
              包含 uploads 附件目录（{info?.upload_dir ? `位于 ${info.upload_dir}` : '…'}）
            </Text>
          </Space>
        </div>
      </Card>

      <div className="cn-actionbar">
        <Button
          type="primary"
          icon={<CloudDownloadOutlined />}
          loading={backupProgress}
          onClick={() => backupMutation.mutate()}
        >
          立即备份并下载
        </Button>
        <Text type="secondary">备份文件为 .tar.gz 格式，恢复时可直接上传</Text>
      </div>

      {backupProgress && (
        <div className="cn-admin-progress">
          <Progress percent={100} status="active" showInfo={false} />
          <Text type="secondary">服务器正在生成备份，请稍候…</Text>
        </div>
      )}

      <div className="cn-hint">
        <WarningOutlined />
        <div>
          备份也可以通过 CLI 完成：Web 管理台输出 .tar.gz 方便下载；若需要直接备份到服务器文件夹（不压缩），请在服务器终端执行
          <Text code>cndb backup --dir -o /path/to/backup_dir</Text>
        </div>
      </div>
    </div>
  )

  const restoreTab = (
    <div className="cn-admin-section">
      <Alert
        type="error"
        showIcon
        icon={<ExclamationCircleOutlined />}
        message="破坏性操作 — 恢复将覆盖当前数据库"
        description="请确保已备份当前数据。恢复后原有工作区、表结构、数据行将全部被替换为备份中的内容。"
      />

      {!restoreFile ? (
        <Upload.Dragger
          multiple={false}
          accept=".tar.gz,.tgz"
          beforeUpload={handleRestoreFile}
          disabled={restoring}
          showUploadList={false}
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
                  message="备份由更新版本的程序生成"
                  description="该备份由更高版本的程序生成，无法使用快速恢复。已自动选择「兼容恢复」：按当前程序支持的表结构逐表导入，备份中多出的表或字段的数据会被跳过。"
                  style={{ marginBottom: 'var(--cn-space-lg)' }}
                />
              )}
              <Descriptions
                column={isMobile ? 1 : 2}
                layout={isMobile ? 'vertical' : 'horizontal'}
                size="small"
                bordered
              >
                <Descriptions.Item label="备份版本">{manifest.version}</Descriptions.Item>
                <Descriptions.Item label="应用版本">{manifest.app_version}</Descriptions.Item>
                <Descriptions.Item label="创建时间">
                  {new Date(manifest.created_at).toLocaleString()}
                </Descriptions.Item>
                <Descriptions.Item label="数据库类型">
                  {manifest.database.db_type}（{manifest.database.backup_mode}）
                </Descriptions.Item>
                <Descriptions.Item label="数据结构版本">
                  {manifest.database.schema_version || <Tag>未知（旧版备份）</Tag>}
                </Descriptions.Item>
                <Descriptions.Item label="兼容备份包">
                  {manifest.database.fallback_mode
                    ? <Tag color="blue">有</Tag>
                    : <Tag>无</Tag>}
                </Descriptions.Item>
                <Descriptions.Item label="数据表数">{manifest.database.tables.length}</Descriptions.Item>
                <Descriptions.Item label="总行数">
                  {Object.values(manifest.database.row_counts).reduce((a, b) => a + b, 0).toLocaleString()}
                </Descriptions.Item>
                <Descriptions.Item label="附件" span={isMobile ? 1 : 2}>
                  {manifest.uploads.included
                    ? `${manifest.uploads.file_count} 个文件，共 ${formatSize(manifest.uploads.total_size, 2)}`
                    : <Tag>未包含</Tag>}
                </Descriptions.Item>
              </Descriptions>

              <div className="cn-field cn-field-spaced">
                <span className="cn-field-label">恢复模式</span>
                <Select
                  value={restoreMode}
                  onChange={setRestoreMode}
                  disabled={restoring}
                  style={{ width: isMobile ? '100%' : 320 }}
                  options={[
                    { value: 'auto', label: '自动选择（推荐）' },
                    { value: 'native', label: '快速恢复（直接覆盖数据库文件）' },
                    { value: 'sqlalchemy', label: '兼容恢复（逐表导入，适用范围更广）' },
                  ]}
                />
              </div>

              {manifest.database.tables.length > 0 && (
                <div className="cn-manifest-tables">
                  <Text type="secondary">表清单：</Text>
                  <div className="cn-manifest-groups">
                    {([
                      ['系统表', tableGroups.system, undefined],
                      ['用户表', tableGroups.user, 'blue'],
                    ] as const).map(([label, names, color]) =>
                      names.length > 0 ? (
                        <div key={label}>
                          <Text type="secondary">
                            {label}（{names.length}）
                          </Text>
                          <div className="cn-manifest-tags">
                            {names.map(t => (
                              <Tag key={t} color={color}>
                                {t} ({manifest.database.row_counts[t] ?? 0})
                              </Tag>
                            ))}
                          </div>
                        </div>
                      ) : null,
                    )}
                  </div>
                </div>
              )}

              <div className="cn-danger-zone">
                <div className="cn-danger-zone-text">
                  <Text strong>覆盖当前数据库</Text>
                  <Text type="secondary">此操作不可撤销，所有现有数据将被替换为备份内容。建议先做一次备份。</Text>
                </div>
                <Popconfirm
                  title={<Text type="danger" strong>确认覆盖当前数据库？</Text>}
                  description="此操作不可撤销，所有现有数据将被替换为备份内容。建议先做一次备份。"
                  okText="确认恢复"
                  okType="danger"
                  cancelText="取消"
                  icon={<ExclamationCircleOutlined />}
                  onConfirm={() => restoreMutation.mutate(restoreFile)}
                  disabled={restoring}
                >
                  <Button danger type="primary" icon={<ReloadOutlined />} loading={restoring}>
                    {restoring ? '正在恢复…' : '执行系统恢复（覆盖）'}
                  </Button>
                </Popconfirm>
              </div>
            </>
          ) : (
            <div className="cn-state">正在校验备份文件…</div>
          )}
        </Card>
      )}

      {inspectMutation.isPending && (
        <Progress percent={100} status="active" showInfo={false} />
      )}
      {restoring && <Alert type="info" showIcon message="正在恢复系统数据，请勿关闭页面…" />}

      <div className="cn-hint">
        <InfoCircleOutlined />
        <div>
          从文件夹恢复（CLI）：若用 <Text code>cndb backup --dir -o &lt;路径&gt;</Text> 备份到服务器文件夹，
          可直接执行 <Text code>cndb restore /path/to/backup_dir --force</Text>
        </div>
      </div>
    </div>
  )

  const infoTab = (
    <div className="cn-admin-section">
      <Card size="small" title={<span><InfoCircleOutlined /> 系统运行信息</span>} loading={infoLoading}>
        {info && (
          <Descriptions
            column={isMobile ? 1 : 2}
            layout={isMobile ? 'vertical' : 'horizontal'}
            size="small"
            bordered
          >
            <Descriptions.Item label="应用名称">{info.app_name}</Descriptions.Item>
            <Descriptions.Item label="版本">{info.app_version}</Descriptions.Item>
            <Descriptions.Item label="数据库" span={isMobile ? 1 : 2}>
              <Text code copyable>{info.database_url}</Text>
            </Descriptions.Item>
            <Descriptions.Item label="数据目录" span={isMobile ? 1 : 2}>
              <Text code copyable>{info.data_dir}</Text>
            </Descriptions.Item>
            <Descriptions.Item label="附件目录" span={isMobile ? 1 : 2}>
              <Text code copyable>{info.upload_dir}</Text>
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

  const content: Record<AdminSectionKey, ReactNode> = {
    users: <UsersPage />,
    events: <EventsPage />,
    storage: <StoragePage />,
    info: infoTab,
    backup: backupTab,
    restore: restoreTab,
  }

  /** 分区导航项 —— 桌面导航栏与窄屏胶囊行共用（role=tab 便于键盘与测试定位） */
  const navItems = SECTIONS.map((s) => {
    const active = s.key === section
    return { ...s, active, onClick: () => goSection(s.key) }
  })

  // 侧栏折叠态见上方 railCollapsed（Hook 须在条件 return 之前声明）

  return (
    <div className="cn-admin" data-testid="admin-panel">
      {/* 桌面端分区导航 SIDEBAR：贴边占满高度，可折叠（同工作区 Sider），窄屏由下方胶囊行替代 */}
      {!isMobile && (
        <aside className={railCollapsed ? 'cn-admin-rail cn-admin-rail-collapsed' : 'cn-admin-rail'}>
          {!railCollapsed && <div className="cn-admin-rail-title">系统管理台</div>}
          <nav className="cn-admin-nav" role="tablist" aria-label="管理台分区" aria-orientation="vertical">
            {navItems.map(item => (
              <button
                key={item.key}
                type="button"
                role="tab"
                aria-selected={item.active}
                title={railCollapsed ? item.label : undefined}
                data-testid={`admin-nav-${item.key}`}
                className={item.active ? 'cn-admin-nav-item cn-admin-nav-item-active' : 'cn-admin-nav-item'}
                onClick={item.onClick}
              >
                <span className="cn-admin-nav-icon" aria-hidden>{item.icon}</span>
                {!railCollapsed && <span className="cn-admin-nav-label">{item.label}</span>}
              </button>
            ))}
          </nav>
          <div className="cn-admin-rail-foot">
            <button
              type="button"
              className="cn-admin-rail-collapse"
              aria-label={railCollapsed ? '展开侧栏' : '收起侧栏'}
              aria-expanded={!railCollapsed}
              data-testid="admin-rail-collapse"
              onClick={() => setRailCollapsed(c => !c)}
            >
              {railCollapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
            </button>
          </div>
        </aside>
      )}

      <div className="cn-admin-main">
        <header className="cn-admin-header">
          <span className="cn-admin-mark" aria-hidden><SafetyOutlined /></span>
          <div className="cn-admin-heading">
            <div className="cn-admin-eyebrow">系统管理台</div>
            <h1 className="cn-admin-title">{activeSection.label}</h1>
            <p className="cn-admin-desc">{activeSection.desc}</p>
          </div>
          <div className="cn-admin-header-extra">
            <Tag bordered={false} color="blue">系统管理员</Tag>
          </div>
        </header>

        {isMobile && (
          <nav className="cn-admin-pills" role="tablist" aria-label="管理台分区">
            {navItems.map(item => (
              <button
                key={item.key}
                type="button"
                role="tab"
                aria-selected={item.active}
                data-testid={`admin-nav-${item.key}`}
                className={item.active ? 'cn-admin-pill cn-admin-pill-active' : 'cn-admin-pill'}
                onClick={item.onClick}
              >
                <span aria-hidden>{item.icon}</span>
                {item.label}
              </button>
            ))}
          </nav>
        )}

        {content[section]}
      </div>
    </div>
  )
}
