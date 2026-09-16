/** 导入/导出对话框 — 文件上传 + 两阶段预览 + 异步进度轮询 + 多格式导出 + API 抓取追加.
 *
 * V2 扩展：
 * - 高级导入设置（折叠区）：参考列多选 + 未知列策略
 * - 预览面板三区域：统计卡片（可新增/可更新/警告/错误）+ 高级设置折叠 + Tabs（待新增/待更新/错误警告）
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { Modal, Tabs, Button, Progress, message, Space, Select, Alert, Empty, Upload, Switch, Table, Tag, Collapse, Radio, Descriptions } from 'antd'
import { InboxOutlined, UploadOutlined, DownloadOutlined, FileTextOutlined, ApiOutlined, CheckCircleOutlined, ExclamationCircleOutlined, CloseCircleOutlined, SettingOutlined } from '@ant-design/icons'
import { importApi, exportApi } from '@/api'
import type { ImportTaskInfo, Field } from '@/api'
import ApiImportDialog from './ApiImportDialog'

const { Dragger } = Upload

interface Props {
  open: boolean
  wid: string
  tid: string
  /** 当前表的活动字段列表（用于参考列多选） */
  fields?: Field[]
  onClose: () => void
  /** 导入成功后调用（刷新列表等） */
  onImported?: () => void
  /** 当前激活的视图 ID（用于按视图筛选导出） */
  viewId?: number | string | null
  /** 当前激活的视图名称（仅用于提示） */
  viewName?: string
}

/** 允许的导入文件扩展名 */
const ACCEPTED_EXT = ['.csv', '.json', '.xlsx']

type Phase = 'idle' | 'analyzing' | 'preview' | 'importing' | 'done' | 'failed'

export default function ImportExportDialog({ open, wid, tid, fields = [], onClose, onImported, viewId, viewName }: Props) {
  const [task, setTask] = useState<ImportTaskInfo | null>(null)
  const [phase, setPhase] = useState<Phase>('idle')
  const [polling, setPolling] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [selectedFormat, setSelectedFormat] = useState<'json' | 'csv' | 'xlsx'>('csv')
  const [useViewFilter, setUseViewFilter] = useState(true)

  // V2 高级设置
  const [matchKeys, setMatchKeys] = useState<string[]>([])
  const [unknownColsStrategy, setUnknownColsStrategy] = useState<'drop' | 'add_text_field'>('drop')

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
      setMatchKeys([])
      setUnknownColsStrategy('drop')
    }
  }, [open])

  // 轮询任务状态
  useEffect(() => {
    if (!polling || !task) return
    pollTimer.current = window.setInterval(async () => {
      try {
        const info = await importApi.getTask(wid, tid, task.task_id)
        setTask(info)
        if (info.status === 'pending_confirm') {
          setPolling(false)
          setPhase('preview')
        } else if (info.status === 'done') {
          setPolling(false)
          setPhase('done')
          const imported = (info as ImportTaskInfo & { validation_report?: any }).validation_report?.actually_imported ?? info.imported_rows ?? 0
          if (imported > 0) {
            message.success(`导入完成：${imported} 行`)
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

  // 上传文件 + analyze（带 V2 参数）
  const beforeUpload = useCallback((file: any) => {
    const name: string = file?.name?.toLowerCase() || ''
    if (!ACCEPTED_EXT.some(ext => name.endsWith(ext))) {
      message.error(`仅支持 ${ACCEPTED_EXT.join(' / ')} 文件`)
      return false
    }
    importApi.previewAnalyze(wid, tid, file, matchKeys, unknownColsStrategy)
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
  }, [wid, tid, matchKeys, unknownColsStrategy])

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

  // 确认导入（带 V2 参数）
  const handleConfirm = async () => {
    if (!task) return
    try {
      await importApi.confirmImport(wid, tid, task.task_id, matchKeys, unknownColsStrategy)
      setPhase('importing')
      setPolling(true)
    } catch (err) {
      message.error(err instanceof Error ? err.message : '确认失败')
    }
  }

  const handleReset = () => {
    if (pollTimer.current) {
      clearInterval(pollTimer.current)
      pollTimer.current = null
    }
    setTask(null)
    setPhase('idle')
    setPolling(false)
  }

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
          <span style={{ marginLeft: 12, color: '#94a3b8' }}>· {(task.format || '').toUpperCase()}</span>
        </div>
        <Progress percent={task.progress} status={colorMap[task.status] || 'normal'} size="small" />
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

  // ── 渲染：高级导入设置（折叠区）──────────
  const renderAdvancedSettings = () => {
    const fieldOptions = fields
      .filter(f => f.field_type !== 'link')  // link 不适合做 upsert key
      .map(f => ({ value: f.name, label: `${f.name} (${f.field_type})` }))
    return (
      <Collapse
        size="small"
        style={{ marginBottom: 12 }}
        items={[{
          key: 'adv',
          label: <span><SettingOutlined /> 高级导入设置</span>,
          children: (
            <Descriptions column={1} size="small" bordered>
              <Descriptions.Item label="参考列（upsert 匹配键）">
                <Select
                  mode="multiple"
                  allowClear
                  style={{ width: '100%' }}
                  placeholder="不选则全部导入为新行；选了则按此列匹配已有行做更新"
                  value={matchKeys}
                  onChange={setMatchKeys}
                  options={fieldOptions}
                  disabled={fieldOptions.length === 0}
                />
              </Descriptions.Item>
              <Descriptions.Item label="未知列处理策略">
                <Radio.Group value={unknownColsStrategy} onChange={e => setUnknownColsStrategy(e.target.value)}>
                  <Radio value="drop">丢弃（跳过文件里表中不存在的列）</Radio>
                  <Radio value="add_text_field">自动新增字段（推断类型并建列）</Radio>
                </Radio.Group>
              </Descriptions.Item>
            </Descriptions>
          ),
        }]}
      />
    )
  }

  // ── 渲染：预览面板（V2 四卡片 + Tab） ──
  const renderPreview = () => {
    if (!task || phase !== 'preview') return null
    const report = (task as ImportTaskInfo & { validation_report?: any }).validation_report
    if (!report) return null

    const hasErrors = report.error_count > 0
    const newCount = report.new_count ?? report.valid_count
    const updateCount = report.update_count ?? 0
    const warning = report.warning_count
    const error = report.error_count
    const hasUpsert = updateCount > 0
    const multiConflict = report.multi_key_conflicts ?? 0
    const plannedColumns: Array<{name: string; field_type: string; sample_values?: string[]}> = report.planned_columns || []

    return (
      <div style={{ marginTop: 16 }}>
        {/* 统计卡片 */}
        <div style={{ display: 'flex', gap: 12, marginBottom: 16 }}>
          <div style={{ flex: 1, padding: 12, background: '#f0fdf4', borderRadius: 8, textAlign: 'center' }}>
            <div style={{ fontSize: 20, fontWeight: 700, color: '#16a34a' }}>{newCount}</div>
            <div style={{ fontSize: 12, color: '#166534' }}><CheckCircleOutlined /> 待新增</div>
          </div>
          {hasUpsert && (
            <div style={{ flex: 1, padding: 12, background: '#eff6ff', borderRadius: 8, textAlign: 'center' }}>
              <div style={{ fontSize: 20, fontWeight: 700, color: '#2563eb' }}>{updateCount}</div>
              <div style={{ fontSize: 12, color: '#1e40af' }}>🔄 待更新</div>
            </div>
          )}
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

        {multiConflict > 0 && (
          <Alert
            type="warning"
            style={{ marginBottom: 12 }}
            showIcon
            message={`参考列匹配到 ${multiConflict} 组多行冲突（同 key 对应多条已有数据），将取 ID 最小的一行更新`}
          />
        )}

        {renderAdvancedSettings()}

        {/* 未知列提示 / 规划 */}
        {(report.skipped_columns?.length > 0 || report.missing_required?.length > 0) && (
          <Alert
            type="warning"
            style={{ marginBottom: 12 }}
            showIcon
            message={
              <div style={{ fontSize: 12 }}>
                {report.skipped_columns?.length > 0 && (
                  <div>
                    <Tag color="orange">已忽略的文件列</Tag>
                    {report.skipped_columns.join(', ')}
                    {unknownColsStrategy === 'drop' && <span style={{ marginLeft: 8, color: '#d97706' }}>（自动新增字段已关闭，可在上方设置中开启）</span>}
                  </div>
                )}
                {plannedColumns.length > 0 && (
                  <div style={{ marginTop: 6 }}>
                    <Tag color="green">将自动新增字段</Tag>
                    {plannedColumns.map((pc: any) => (
                      <Tag key={pc.name} color="blue">{pc.name} <span style={{ color: '#64748b' }}>({pc.field_type})</span></Tag>
                    ))}
                  </div>
                )}
                {report.missing_required?.length > 0 && (
                  <div>
                    <Tag color="red">必填但文件缺失</Tag>
                    {report.missing_required.join(', ')}
                  </div>
                )}
              </div>
            }
          />
        )}

        {/* 主预览 Tab */}
        <Tabs
          size="small"
          defaultActiveKey={hasUpsert ? 'new' : 'errors'}
          items={[
            {
              key: 'new',
              label: `待新增 (${newCount})`,
              disabled: newCount === 0,
              children: renderPreviewTab(report.new_preview, { match_key_values: 1, field_sample: 1 }),
            },
            ...(hasUpsert ? [{
              key: 'update',
              label: `待更新 (${updateCount})`,
              children: renderPreviewTab(report.update_preview, { match_key_values: 1, field_sample: 1, existing_row_id: 1 }),
            }] : []),
            {
              key: 'errors',
              label: `错误 / 警告 (${report.errors.length + report.warnings.length})`,
              children: (
                <>
                  {report.errors.length > 0 && (
                    <Table
                      size="small" pagination={{ pageSize: 10 }}
                      dataSource={report.errors} rowKey={(_, i) => `e${i}`}
                      columns={[
                        { title: '行号', dataIndex: 'row_number', width: 80 },
                        { title: '字段', dataIndex: 'field', width: 120 },
                        { title: '原因', dataIndex: 'message' },
                      ]}
                    />
                  )}
                  {report.warnings.length > 0 && (
                    <div style={{ marginTop: 12 }}>
                      <div style={{ marginBottom: 4, color: '#92400e', fontSize: 13 }}>⚠️ 警告</div>
                      <Table
                        size="small" pagination={{ pageSize: 10 }}
                        dataSource={report.warnings} rowKey={(_, i) => `w${i}`}
                        columns={[
                          { title: '行号', dataIndex: 'row_number', width: 80 },
                          { title: '字段', dataIndex: 'field', width: 120 },
                          { title: '原因', dataIndex: 'message' },
                        ]}
                      />
                    </div>
                  )}
                  {report.errors.length === 0 && report.warnings.length === 0 && (
                    <Empty description="无错误无警告" />
                  )}
                </>
              ),
            },
          ]}
        />

        {/* 操作按钮 */}
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 12 }}>
          <Button onClick={handleReset}>取消</Button>
          {hasErrors && (
            <Button onClick={handleDownloadFailed} icon={<DownloadOutlined />}>下载失败行</Button>
          )}
          <Button
            type="primary"
            onClick={handleConfirm}
            disabled={newCount + updateCount === 0}
          >
            确认导入（新增 {newCount} / 更新 {updateCount}）
          </Button>
        </div>
      </div>
    )
  }

  // 通用预览表格
  const renderPreviewTab = (
    preview: any[] | undefined,
    colKeys: Record<string, number>,
  ) => {
    if (!preview || preview.length === 0) {
      return <Empty description="无数据" />
    }
    const columns: any[] = [{ title: '行号', dataIndex: 'row_number', width: 80 }]
    if (colKeys.match_key_values) {
      const kvs = Object.keys(preview[0].match_key_values || {})
      kvs.forEach(k => columns.push({ title: `参考列: ${k}`, dataIndex: ['match_key_values', k], width: 120 }))
    }
    if (colKeys.existing_row_id) {
      columns.push({ title: '命中行 ID', dataIndex: 'existing_row_id', width: 100, render: (v: number) => <Tag color="blue">#{v}</Tag> })
    }
    if (colKeys.field_sample) {
      columns.push({
        title: '主要字段样本',
        dataIndex: 'field_sample',
        render: (sample: Record<string, unknown>) => {
          if (!sample) return '-'
          return Object.entries(sample).map(([k, v]) => (
            <Tag key={k} style={{ marginBottom: 2 }}>{k}: <span style={{ color: '#334155' }}>{String(v)}</span></Tag>
          ))
        },
      })
    }
    return (
      <>
        <Table
          size="small"
          pagination={{ pageSize: 20 }}
          scroll={{ y: 320 }}
          dataSource={preview}
          rowKey={(_, i) => `p${i}`}
          columns={columns}
        />
        {preview.length >= 200 && (
          <div style={{ color: '#64748b', fontSize: 12, marginTop: 4 }}>仅预览前 200 行，完整数据将全部导入</div>
        )}
      </>
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
        <Alert type="info" message="处理中..." style={{ marginTop: 12 }} showIcon />
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
      width={860}
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
