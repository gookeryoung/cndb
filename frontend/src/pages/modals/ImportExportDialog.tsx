/** 导入/导出对话框 — 文件上传 + 两阶段预览 + 异步进度轮询 + 多格式导出 + API 抓取追加.
 *
 * V3 流程：
 *   1. 用户上传文件（不带 matchKeys），系统解析+校验，全量展示为"待新增"
 *   2. 用户在预览面板里选择参考列 + 点击"执行 DIFF"
 *   3. 后端重新 analyze，返回 new/update 分类 + 字段级 diff
 *   4. Diff 视图：新增行绿底 / 更新行蓝底 + 字段级 old→new 对比
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { Modal, Tabs, Button, Progress, message, Space, Select, Alert, Empty, Upload, Switch, Table, Tag, Collapse, Radio, Descriptions, Tooltip } from 'antd'
import { InboxOutlined, UploadOutlined, DownloadOutlined, FileTextOutlined, ApiOutlined, ExclamationCircleOutlined, CloseCircleOutlined, SettingOutlined, ReloadOutlined, SwapOutlined, PlusCircleOutlined, EditOutlined } from '@ant-design/icons'
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

/** 把值格式化为可显示的短文本（超长截断） */
function fmtValue(v: unknown, limit = 80): string {
  if (v == null) return ''
  const s = String(v)
  return s.length > limit ? s.slice(0, limit - 3) + '...' : s
}

export default function ImportExportDialog({ open, wid, tid, fields = [], onClose, onImported, viewId, viewName }: Props) {
  const [task, setTask] = useState<ImportTaskInfo | null>(null)
  const [phase, setPhase] = useState<Phase>('idle')
  const [polling, setPolling] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [selectedFormat, setSelectedFormat] = useState<'json' | 'csv' | 'xlsx'>('csv')
  const [useViewFilter, setUseViewFilter] = useState(true)

  // V3: 参考列选择 + 高级设置
  const [matchKeys, setMatchKeys] = useState<string[]>([])
  const [unknownColsStrategy, setUnknownColsStrategy] = useState<'drop' | 'add_text_field'>('drop')
  const [diffing, setDiffing] = useState(false)  // 执行 DIFF 的 loading

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
      setDiffing(false)
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
          setDiffing(false)
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
          setDiffing(false)
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

  // 上传文件（不带 matchKeys，让后端全部归为 new）
  const beforeUpload = useCallback((file: any) => {
    const name: string = file?.name?.toLowerCase() || ''
    if (!ACCEPTED_EXT.some(ext => name.endsWith(ext))) {
      message.error(`仅支持 ${ACCEPTED_EXT.join(' / ')} 文件`)
      return false
    }
    importApi.previewAnalyze(wid, tid, file, [], unknownColsStrategy)
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
  }, [wid, tid, unknownColsStrategy])

  // 执行 DIFF — 用户改了 matchKeys 后重新 analyze
  const handleRunDiff = useCallback(async () => {
    if (!task) return
    try {
      setDiffing(true)
      await importApi.reanalyzeImport(wid, tid, task.task_id, matchKeys, unknownColsStrategy)
      setPolling(true)
    } catch (err) {
      setDiffing(false)
      message.error(err instanceof Error ? err.message : '执行 DIFF 失败')
    }
  }, [task, wid, tid, matchKeys, unknownColsStrategy])

  // 清空参考列（回到全量预览）
  const handleClearMatchKeys = useCallback(async () => {
    if (!task) { setMatchKeys([]); return }
    try {
      setDiffing(true)
      setMatchKeys([])
      await importApi.reanalyzeImport(wid, tid, task.task_id, [], unknownColsStrategy)
      setPolling(true)
    } catch (err) {
      setDiffing(false)
      message.error(err instanceof Error ? err.message : '清空参考列失败')
    }
  }, [task, wid, tid, unknownColsStrategy])

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

  // 确认导入（当前 matchKeys + unknownColsStrategy）
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
    setMatchKeys([])
    setUnknownColsStrategy('drop')
    setDiffing(false)
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
      pending_validation: diffing ? '重新 DIFF 中...' : '校验中...',
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

  // ── 渲染：Diff 控制区（参考列 + 执行 DIFF + 高级设置） ──
  const renderDiffControls = () => {
    const fieldOptions = fields
      .filter(f => f.field_type !== 'link')
      .map(f => ({ value: f.name, label: `${f.name} (${f.field_type})` }))
    const hasKeys = matchKeys.length > 0
    return (
      <div style={{ marginBottom: 12 }}>
        {/* 参考列选择 */}
        <div style={{ padding: 12, background: '#f8fafc', borderRadius: 8, border: '1px solid #e2e8f0' }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: '#334155', marginBottom: 8 }}>
            <SwapOutlined style={{ marginRight: 6 }} />
            选择参考列（按此匹配已有行做更新 / 新增）
          </div>
          <div style={{ display: 'flex', gap: 8, alignItems: 'flex-start' }}>
            <Select
              mode="multiple"
              allowClear
              style={{ flex: 1 }}
              placeholder="不选 = 全部作为新增；选了 = 按此列匹配已有行"
              value={matchKeys}
              onChange={setMatchKeys}
              options={fieldOptions}
              disabled={fieldOptions.length === 0 || diffing}
            />
            <Button
              type="primary"
              icon={<ReloadOutlined />}
              onClick={handleRunDiff}
              loading={diffing}
              disabled={!task}
            >
              {hasKeys ? '执行 DIFF' : '预览全量'}
            </Button>
            {hasKeys && (
              <Button onClick={handleClearMatchKeys} disabled={diffing}>
                清空
              </Button>
            )}
          </div>
          <div style={{ fontSize: 12, color: '#64748b', marginTop: 6 }}>
            提示：选择一个或多个字段（如『ID』、『名称』），系统将用它们匹配表中已有行，相同值视为更新，无匹配视为新增。
          </div>
        </div>

        {/* 高级设置折叠区（未知列策略） */}
        <Collapse
          size="small"
          style={{ marginTop: 8 }}
          items={[{
            key: 'adv',
            label: <span><SettingOutlined /> 高级设置</span>,
            children: (
              <Descriptions column={1} size="small" bordered>
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
      </div>
    )
  }

  // ── 渲染：Diff 表格（支持行着色 + 字段级 old→new 对比） ──
  const renderDiffTable = (
    preview: any[] | undefined,
    mode: 'new' | 'update',
  ) => {
    if (!preview || preview.length === 0) {
      return <Empty description={mode === 'new' ? '无新增行' : '无更新行'} />
    }
    const isNew = mode === 'new'
    const rowBg = isNew ? '#f0fdf4' : '#eff6ff'          // 新增绿 / 更新蓝
    const rowBorder = isNew ? '#22c55e' : '#3b82f6'       // 左侧竖条颜色
    const badgeColor = isNew ? 'green' : 'blue'
    const BadgeIcon = isNew ? PlusCircleOutlined : EditOutlined

    // 动态收集所有列（以第一行为准 + 常见列）
    const firstRow = preview[0]
    // new_preview / update_preview 都有 match_key_values / field_sample
    const kvKeys = firstRow?.match_key_values ? Object.keys(firstRow.match_key_values) : []
    const sampleKeys = firstRow?.field_sample ? Object.keys(firstRow.field_sample) : []
    const diffKeys = firstRow?.field_diffs ? Object.keys(firstRow.field_diffs) : []
    // 列集合：参考列 + 样本列 + 变化列（去重）
    const allFieldNames: string[] = []
    kvKeys.forEach(k => { if (!allFieldNames.includes(k)) allFieldNames.push(k) })
    sampleKeys.forEach(k => { if (!allFieldNames.includes(k)) allFieldNames.push(k) })
    diffKeys.forEach(k => { if (!allFieldNames.includes(k)) allFieldNames.push(k) })

    const columns: any[] = [
      {
        title: <BadgeIcon style={{ color: isNew ? '#16a34a' : '#2563eb', marginRight: 4 }} />,
        dataIndex: '_tag',
        width: 70,
        fixed: 'left',
        render: () => (
          <Tag color={badgeColor} style={{ margin: 0 }}>
            {isNew ? '新增' : '更新'}
          </Tag>
        ),
      },
      { title: '文件行号', dataIndex: 'row_number', width: 90, fixed: 'left' },
    ]

    if (!isNew) {
      columns.push({
        title: '命中行',
        dataIndex: 'existing_row_id',
        width: 100,
        fixed: 'left',
        render: (v: number) => <Tag color="blue">#{v}</Tag>,
      })
    }

    // 每个字段列：显示值 + 如果是变化字段则渲染 diff
    allFieldNames.forEach(fname => {
      const isKeyCol = kvKeys.includes(fname)
      columns.push({
        title: isKeyCol ? <span style={{ color: '#7c3aed' }}>🔑 {fname}</span> : fname,
        dataIndex: ['field_sample', fname],
        ellipsis: true,
        render: (_: unknown, row: any) => {
          const previewVal = row.field_sample?.[fname]
          const diff = row.field_diffs?.[fname]
          // 优先展示 diff（如果是变化字段）
          if (diff) {
            const oldText = fmtValue(diff.old)
            const newText = fmtValue(diff.new)
            return (
              <div style={{ fontSize: 12, lineHeight: 1.6 }}>
                <div style={{ color: '#9ca3af', textDecoration: 'line-through' }}>
                  {oldText || <span style={{ color: '#d1d5db' }}>(空)</span>}
                </div>
                <div style={{ color: '#16a34a', fontWeight: 500 }}>
                  → {newText || <span style={{ color: '#16a34a' }}>(清空)</span>}
                </div>
              </div>
            )
          }
          // 参考列：高亮标记
          if (isKeyCol) {
            const kv = row.match_key_values?.[fname]
            return <Tag color="purple">{fmtValue(kv ?? previewVal)}</Tag>
          }
          return previewVal != null ? fmtValue(previewVal) : '-'
        },
      })
    })

    return (
      <>
        <Table
          size="small"
          pagination={{ pageSize: 20 }}
          scroll={{ x: 700, y: 360 }}
          dataSource={preview}
          rowKey={(_, i) => `${mode}-${i}`}
          columns={columns}
          rowClassName={() => 'diff-row'}
          style={{ '--diff-row-bg': rowBg, '--diff-row-border': rowBorder } as any}
        />
        {preview.length >= 200 && (
          <div style={{ color: '#64748b', fontSize: 12, marginTop: 4 }}>仅预览前 200 行，完整数据将全部导入</div>
        )}
      </>
    )
  }

  // ── 渲染：预览面板（V3 四卡片 + Diff 控制 + Diff 表格） ──
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
    const plannedColumns: Array<{ name: string; field_type: string; sample_values?: string[] }> = report.planned_columns || []

    return (
      <div style={{ marginTop: 16 }}>
        {/* 统计卡片 */}
        <div style={{ display: 'flex', gap: 12, marginBottom: 16 }}>
          <div style={{ flex: 1, padding: 12, background: '#f0fdf4', borderRadius: 8, textAlign: 'center', borderLeft: '3px solid #22c55e' }}>
            <div style={{ fontSize: 20, fontWeight: 700, color: '#16a34a' }}>{newCount}</div>
            <div style={{ fontSize: 12, color: '#166534' }}><PlusCircleOutlined /> 待新增</div>
          </div>
          <div style={{ flex: 1, padding: 12, background: '#eff6ff', borderRadius: 8, textAlign: 'center', borderLeft: '3px solid #3b82f6', opacity: hasUpsert ? 1 : 0.4 }}>
            <div style={{ fontSize: 20, fontWeight: 700, color: '#2563eb' }}>{updateCount}</div>
            <div style={{ fontSize: 12, color: '#1e40af' }}><EditOutlined /> 待更新{!hasUpsert && '（选参考列后显示）'}</div>
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

        {multiConflict > 0 && (
          <Alert
            type="warning"
            style={{ marginBottom: 12 }}
            showIcon
            message={`参考列匹配到 ${multiConflict} 组多行冲突（同 key 对应多条已有数据），将取 ID 最小的一行更新`}
          />
        )}

        {/* Diff 控制区 */}
        {renderDiffControls()}

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

        {/* 主预览 Tab：有 upsert 时按 new/update 分 Tab 并带 diff；否则全量 new */}
        <Tabs
          size="small"
          defaultActiveKey={hasUpsert ? 'new' : 'errors'}
          items={[
            {
              key: 'new',
              label: `待新增 (${newCount})`,
              disabled: newCount === 0,
              children: renderDiffTable(report.new_preview, 'new'),
            },
            ...(hasUpsert ? [{
              key: 'update',
              label: `待更新 (${updateCount})`,
              children: renderDiffTable(report.update_preview, 'update'),
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
                      <div style={{ marginBottom: 4, color: '#92400e', fontSize: 13 }}>警告</div>
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
          <Tooltip title={matchKeys.length > 0 ? `将按参考列 ${matchKeys.join(', ')} 执行 upsert` : '当前全部作为新增导入'}>
            <Button
              type="primary"
              onClick={handleConfirm}
              disabled={newCount + updateCount === 0}
            >
              确认导入（新增 {newCount} / 更新 {updateCount}）
            </Button>
          </Tooltip>
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
            <p className="ant-upload-hint">支持 CSV / JSON / XLSX — 先看全量数据，再选参考列执行 DIFF</p>
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
      width={1000}
      destroyOnHidden
    >
      {/* 行着色样式（:where 避免 specificity 冲突） */}
      <style>{`
        tr.diff-row td {
          background: var(--diff-row-bg, transparent) !important;
          border-left: 3px solid var(--diff-row-border, transparent) !important;
        }
      `}</style>
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
