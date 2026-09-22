/** 导入面板 — 文件上传 + 两阶段预览 + 异步进度轮询 + Diff 视图 + 数据质量面板.
 *
 * V3 流程：
 *   1. 用户上传文件（不带 matchKeys），系统解析+校验，全量展示为"待新增"
 *   2. 用户在预览面板里选择参考列 + 点击"执行 DIFF"
 *   3. 后端重新 analyze，返回 new/update 分类 + 字段级 diff
 *   4. Diff 视图：新增行绿底 / 更新行蓝底；更新行字段级红/绿 chip old→new 对比 + 变更汇总列，
 *      无更新行时空态区分"未选参考列 / 无匹配行 / 命中但字段无变化"
 *
 * 从 ImportExportDialog 拆出：导入全流程状态与渲染内聚于此，外层 Modal 由容器负责.
 */
import { useCallback, useEffect, useRef, useState, type CSSProperties } from 'react'
import { Button, Progress, App as AntApp, Space, Select, Alert, Empty, Upload, Table, Tabs, Tag, Collapse, Radio, Descriptions, Tooltip, Checkbox } from 'antd'
import { InboxOutlined, DownloadOutlined, FileTextOutlined, SettingOutlined, ReloadOutlined, SwapOutlined, PlusCircleOutlined, EditOutlined } from '@ant-design/icons'
import { importApi } from '@/api'
import type { ImportTaskInfo, Field } from '@/api'
import HelpTip from '@/components/HelpTip'
import { ACCEPTED_EXT, changedCountOf, collectDiffColumnKeys, diffChipStyle, fmtValue, type Phase } from './importPreview'

const { Dragger } = Upload

interface ImportPanelProps {
    /** 外层 Modal 打开时才轮询；关闭时由容器传入 false 触发状态清理 */
    open: boolean
    wid: string
    tid: string
    /** 当前表的活动字段列表（用于参考列多选） */
    fields?: Field[]
    onClose: () => void
    /** 导入成功后调用（刷新列表等） */
    onImported?: () => void
}

export default function ImportPanel({ open, wid, tid, fields = [], onClose, onImported }: ImportPanelProps) {
    const { message } = AntApp.useApp()
    const [task, setTask] = useState<ImportTaskInfo | null>(null)
    const [phase, setPhase] = useState<Phase>('idle')
    const [polling, setPolling] = useState(false)

    // V3: 参考列选择 + 高级设置
    const [matchKeys, setMatchKeys] = useState<string[]>([])
    const [unknownColsStrategy, setUnknownColsStrategy] = useState<'drop' | 'add_text_field'>('add_text_field')
    // V3: 用户勾选丢弃的 planned_columns 字段名列表（默认全创建）
    const [droppedColumns, setDroppedColumns] = useState<string[]>([])
    const [diffing, setDiffing] = useState(false)  // 执行 DIFF 的 loading

    // V3: 数据质量面板 —— 用户勾选的清洗建议列表（完整 suggestion 对象）
    const [selectedCleaningActions, setSelectedCleaningActions] = useState<any[]>([])

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
            setUnknownColsStrategy('add_text_field')
            setDroppedColumns([])
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
    }, [polling, task, wid, tid, onImported, message])

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
    }, [wid, tid, unknownColsStrategy, message])

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
    }, [task, wid, tid, matchKeys, unknownColsStrategy, message])

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
    }, [task, wid, tid, unknownColsStrategy, message])

    // 确认导入（当前 matchKeys + unknownColsStrategy + droppedColumns + 清洗建议）
    const handleConfirm = async () => {
        if (!task) return
        try {
            await importApi.confirmImport(wid, tid, task.task_id, matchKeys, unknownColsStrategy, droppedColumns, selectedCleaningActions)
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
        setUnknownColsStrategy('add_text_field')
        setDroppedColumns([])
        setDiffing(false)
        setSelectedCleaningActions([])
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

    // ── 渲染：进度 + 统计 整合面板（紧凑单行布局） ──
    const renderProgressSummary = () => {
        if (!task) return null
        const report = (task as ImportTaskInfo & { validation_report?: any }).validation_report
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
            pending_validation: diffing ? '重新比对分析中...' : '校验中...',
            running: '导入中...',
            done: '已完成',
            failed: '失败',
            pending: '排队中',
        }

        // 三卡统计数据（仅 preview 阶段有 report 时展示）
        // 后端契约：update_count = 命中已有行总数（含无变化），update_changed_count = 有实际字段变化的行数
        // 三卡口径：待新增 = new_count，待更新 = update_changed_count（真正会更新的），无变化 = 命中但字段值一致的
        let newCount = 0, updateCount = 0, unchangedCount = 0
        if (report) {
            newCount = report.new_count ?? report.valid_count ?? 0
            const hitCount: number = report.update_count ?? 0
            const changedCount: number = report.update_changed_count ?? hitCount
            updateCount = changedCount
            unchangedCount = Math.max(0, hitCount - changedCount)
        }

        return (
            <div style={{ marginTop: 12, padding: '10px 14px', background: '#f6f8fa', borderRadius: 8, border: '1px solid #e2e8f0' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 16, flexWrap: 'wrap' }}>
                    {/* 左：文件 + 进度 */}
                    <div style={{ flex: 1, minWidth: 280 }}>
                        <div style={{ fontSize: 13, color: '#475569', display: 'flex', alignItems: 'center', gap: 8 }}>
                            <FileTextOutlined />
                            <span style={{ fontWeight: 500 }}>{task.filename}</span>
                            <span style={{ color: '#94a3b8' }}>· {(task.format || '').toUpperCase()}</span>
                            <span style={{ color: '#94a3b8' }}>·</span>
                            <span style={{ color: '#64748b', fontSize: 12 }}>
                                {textMap[task.status] || task.status}
                                {task.imported_rows != null && task.status === 'done' && ` · 已导入 ${task.imported_rows} 行`}
                            </span>
                        </div>
                        <Progress
                            percent={task.progress}
                            status={colorMap[task.status] || 'normal'}
                            size="small"
                            style={{ marginTop: 6, marginBottom: 0 }}
                            strokeColor={task.status === 'done' ? '#22c55e' : task.status === 'failed' ? '#ef4444' : '#3b82f6'}
                        />
                    </div>

                    {/* 右：三卡统计（仅 preview 及之后展示） */}
                    {report && (
                        <div style={{ display: 'flex', gap: 8 }}>
                            <MiniStat compact label="待新增" value={newCount} color="#22c55e" />
                            <MiniStat compact label="待更新" value={updateCount} color="#3b82f6" />
                            <MiniStat compact label="无变化" value={unchangedCount} color="#94a3b8" />
                        </div>
                    )}
                </div>
                {task.error_message && (
                    <Alert type="error" message={task.error_message} style={{ marginTop: 8, padding: '4px 10px' }} showIcon />
                )}
            </div>
        )
    }

    // ── 渲染：Diff 控制区（参考列 + 执行 DIFF + 高级设置） ──
    const renderDiffControls = () => {
        // V5: 参考列智能推荐 —— 从 analyze 报告读取推荐/禁用信息，装饰下拉选项
        const report = (task as (ImportTaskInfo & { validation_report?: any }) | null)?.validation_report
        const recs = (report?.match_key_recommendations || []) as Array<{ field: string; field_type: string; recommended: boolean; disabled: boolean; reason: string }>
        const recByField = new Map(recs.map(r => [r.field, r]))
        const fieldOptions = fields
            .filter(f => f.field_type !== 'link')
            .map(f => {
                const rec = recByField.get(f.name)
                if (rec?.disabled) {
                    // 禁用项：原因直接展示在标签里，选项不可选
                    return { value: f.name, label: `${f.name} (${f.field_type}) — ${rec.reason}`, disabled: true }
                }
                return {
                    value: f.name,
                    label: rec?.recommended ? `★ ${f.name} (${f.field_type})` : `${f.name} (${f.field_type})`,
                }
            })
        const recommendedFields = recs.filter(r => r.recommended && !r.disabled).map(r => r.field)
        const hasKeys = matchKeys.length > 0
        return (
            <div style={{ marginBottom: 12 }}>
                {/* 参考列选择 */}
                <div style={{ padding: 12, background: '#f8fafc', borderRadius: 8, border: '1px solid #e2e8f0' }}>
                    <div style={{ fontSize: 13, fontWeight: 600, color: '#334155', marginBottom: 8 }}>
                        <SwapOutlined style={{ marginRight: 6 }} />
                        选择参考列（按此匹配已有行做更新 / 新增）
                        <HelpTip title="参考列即匹配键：导入时用这些列的值在表中查找同值行，找到则更新该行，找不到则新增一行" />
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
                            {hasKeys ? '更新数据比对分析' : '预览全量'}
                        </Button>
                        {hasKeys && (
                            <Button onClick={handleClearMatchKeys} disabled={diffing}>
                                清空参考列
                            </Button>
                        )}
                    </div>
                    {recommendedFields.length > 0 && (
                        <div style={{ fontSize: 12, color: '#16a34a', marginTop: 6 }}>
                            ★ 推荐参考列：{recommendedFields.join('、')}（文件与表内取值唯一，匹配最可靠）
                        </div>
                    )}
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

    // ── 渲染：数据质量面板 ──
    const renderQualityPanel = (report: any) => {
        const profiles = (report.column_profiles || []) as any[]
        const summary = report.data_quality_summary as any
        const suggestions = (report.cleaning_suggestions || []) as any[]
        if (profiles.length === 0) return <Empty description="暂无数据质量信息" />

        return (
            <div>
                {/* 整体 summary 卡片 */}
                {summary && (
                    <div style={{ display: 'flex', gap: 12, marginBottom: 16, flexWrap: 'wrap' }}>
                        <MiniStat label="总行数" value={summary.total_rows} color="#3b82f6" />
                        <MiniStat label="总列数" value={summary.total_columns} color="#8b5cf6" />
                        {summary.duplicate_rows > 0 && <MiniStat label="重复行" value={summary.duplicate_rows} color="#f59e0b" />}
                        {summary.empty_columns?.length > 0 && <MiniStat label="全空列" value={summary.empty_columns.length} color="#ef4444" />}
                        {summary.high_null_columns?.length > 0 && <MiniStat label="高空值列" value={summary.high_null_columns.length} color="#ec4899" />}
                    </div>
                )}

                {/* 清洗建议（如果有） */}
                {suggestions.length > 0 && (
                    <div style={{ marginBottom: 16, padding: 12, background: '#fafafa', borderRadius: 8, border: '1px solid #e5e7eb' }}>
                        <div style={{ fontWeight: 600, marginBottom: 8, fontSize: 13 }}>
                            <SettingOutlined /> 清洗建议（勾选后将在确认导入时执行）
                        </div>
                        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                            {suggestions.map((s: any, i: number) => {
                                const isChecked = selectedCleaningActions.some((a: any) => a.id === s.id)
                                return (
                                    <label key={s.id || i} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12 }}>
                                        <Checkbox
                                            checked={isChecked}
                                            onChange={(e) => {
                                                if (e.target.checked) {
                                                    setSelectedCleaningActions((prev) => [...prev, s])
                                                } else {
                                                    setSelectedCleaningActions((prev) => prev.filter((a: any) => a.id !== s.id))
                                                }
                                            }}
                                        >
                                            {s.action}{s.column ? ` (${s.column})` : ''} — {s.reason}（影响 {s.affected_count} 行）
                                        </Checkbox>
                                    </label>
                                )
                            })}
                        </div>
                    </div>
                )}

                {/* 每列可展开卡片 */}
                <Collapse
                    size="small"
                    defaultActiveKey={profiles.slice(0, 1).map(p => p.name)}
                    items={profiles.map(p => ({
                        key: p.name,
                        label: (
                            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                                <span style={{ fontWeight: 500 }}>{p.name}</span>
                                <Tag color="blue">{p.inferred_type}</Tag>
                                <Tag color={p.confidence >= 0.9 ? 'green' : p.confidence >= 0.7 ? 'orange' : 'red'} style={{ margin: 0 }}>
                                    置信 {Math.round(p.confidence * 100)}%
                                </Tag>
                            </div>
                        ),
                        children: (
                            <div style={{ fontSize: 13 }}>
                                <div style={{ display: 'flex', gap: 24, marginBottom: 10 }}>
                                    <span>唯一值 <b>{p.unique_count}</b></span>
                                    <span>空值 <b>{p.null_count}</b></span>
                                    {p.fallback_type && <span style={{ color: '#dc2626' }}>建议降级: {p.fallback_type}</span>}
                                </div>
                                {/* 空值率进度条 */}
                                <div style={{ marginBottom: 10 }}>
                                    <span style={{ color: '#64748b', marginRight: 8 }}>空值率</span>
                                    <Progress
                                        size="small"
                                        percent={Math.round(p.null_ratio * 100)}
                                        strokeColor={p.null_ratio > 0.5 ? '#ef4444' : p.null_ratio > 0.2 ? '#f59e0b' : '#22c55e'}
                                    />
                                </div>
                                {/* 数值列 min/max/mean */}
                                {p.min !== undefined && (
                                    <div style={{ marginBottom: 10, color: '#475569' }}>
                                        最小 <b>{p.min}</b> / 最大 <b>{p.max}</b> / 均值 <b>{p.mean?.toFixed(2)}</b>
                                    </div>
                                )}
                                {/* 类型冲突 */}
                                {p.type_conflicts?.length > 0 && (
                                    <div style={{ marginBottom: 10 }}>
                                        <div style={{ color: '#dc2626', marginBottom: 4 }}>⚠ 类型冲突（{p.type_conflicts.length} 条）</div>
                                        {p.type_conflicts.slice(0, 5).map((c: any, i: number) => (
                                            <div key={i} style={{ color: '#64748b' }}>
                                                行 {c.row_number}: <code style={{ background: '#f1f5f9', padding: '1px 4px', borderRadius: 3 }}>{String(c.value).slice(0, 40)}</code>
                                                被识别为 <Tag>{c.conflicting_type}</Tag>
                                            </div>
                                        ))}
                                    </div>
                                )}
                                {/* 异常值 */}
                                {p.outliers?.length > 0 && (
                                    <div style={{ marginBottom: 10 }}>
                                        <div style={{ color: '#d97706', marginBottom: 4 }}>⚠ 异常值（{p.outliers.length} 个）</div>
                                        <div style={{ color: '#64748b' }}>
                                            {p.outliers.slice(0, 5).map((o: any, i: number) => (
                                                <Tag key={i} color="orange" style={{ marginBottom: 2 }}>{String(o.value)}</Tag>
                                            ))}
                                        </div>
                                    </div>
                                )}
                                {/* 分布直方图（数值列） */}
                                {p.distribution_bins?.length > 0 && (
                                    <div style={{ marginBottom: 10 }}>
                                        <div style={{ color: '#475569', marginBottom: 4 }}>数值分布</div>
                                        <div style={{ display: 'flex', alignItems: 'flex-end', gap: 2, height: 50 }}>
                                            {p.distribution_bins.map((b: any, i: number) => {
                                                const maxC = Math.max(...p.distribution_bins.map((x: any) => x.count))
                                                const h = Math.max(4, (b.count / maxC) * 46)
                                                return (
                                                    <Tooltip key={i} title={`${b.bin_label}: ${b.count}`}>
                                                        <div style={{
                                                            width: `${100 / p.distribution_bins.length}%`,
                                                            background: '#3b82f6',
                                                            height: h,
                                                            borderRadius: 2,
                                                            minWidth: 3,
                                                        }} />
                                                    </Tooltip>
                                                )
                                            })}
                                        </div>
                                    </div>
                                )}
                                {/* 离散列 Top N */}
                                {p.value_counts?.length > 0 && (
                                    <div style={{ marginBottom: 10 }}>
                                        <div style={{ color: '#475569', marginBottom: 4 }}>Top {Math.min(5, p.value_counts.length)} 取值</div>
                                        {p.value_counts.slice(0, 5).map((v: any, i: number) => (
                                            <div key={i} style={{ display: 'flex', justifyContent: 'space-between', color: '#64748b' }}>
                                                <span style={{ maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis' }}>{String(v.value)}</span>
                                                <span>{v.count}</span>
                                            </div>
                                        ))}
                                    </div>
                                )}
                                {/* 样本值 */}
                                {p.sample_values?.length > 0 && (
                                    <div style={{ color: '#64748b' }}>
                                        样本: {p.sample_values.map((v: string, i: number) => (
                                            <Tag key={i} style={{ marginBottom: 2 }}>{String(v).slice(0, 30)}</Tag>
                                        ))}
                                    </div>
                                )}
                            </div>
                        ),
                    }))}
                />
            </div>
        )
    }

    // ── 渲染：Diff 表格（更新行红/绿 chip 字段对比 + 变更汇总列；空态区分提示） ──
    const renderDiffTable = (
        preview: any[] | undefined,
        mode: 'new' | 'update',
        report?: any,
    ) => {
        const isNew = mode === 'new'
        const rowBg = isNew ? '#f0fdf4' : '#eff6ff'          // 新增绿 / 更新蓝
        const rowBorder = isNew ? '#22c55e' : '#3b82f6'       // 左侧竖条颜色
        const badgeColor = isNew ? 'green' : 'blue'
        const BadgeIcon = isNew ? PlusCircleOutlined : EditOutlined

        // ── 空态区分：update 模式按"未选参考列 / 无匹配行"分别提示 ──
        if (!preview || preview.length === 0) {
            if (!isNew) {
                return matchKeys.length === 0 ? (
                    <Empty
                        image={Empty.PRESENTED_IMAGE_SIMPLE}
                        description={
                            <span style={{ color: '#64748b', fontSize: 13 }}>
                                未选择参考列，所有行将作为<b>新增</b>导入
                                <br />
                                <span style={{ fontSize: 12 }}>选择参考列并执行更新数据比对分析后，此处将显示新旧字段对比</span>
                            </span>
                        }
                    />
                ) : (
                    <Empty
                        image={Empty.PRESENTED_IMAGE_SIMPLE}
                        description={
                            <span style={{ color: '#64748b', fontSize: 13 }}>
                                没有需要更新的行
                                <br />
                                <span style={{ fontSize: 12 }}>按参考列「{matchKeys.join('、')}」未匹配到已有数据</span>
                            </span>
                        }
                    />
                )
            }
            return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="无新增行" />
        }

        const { kvKeys, diffKeys, allFieldNames } = collectDiffColumnKeys(preview, mode)

        /** 字段级 diff 单元格：GitHub diff 风格 —— 旧值红底删除线（−）、新值绿底（+） */
        const renderDiffCell = (diff: any) => {
            const oldText = fmtValue(diff.old)
            const newText = fmtValue(diff.new)
            const chipBase: CSSProperties = diffChipStyle()
            return (
                <div style={{ display: 'inline-flex', flexDirection: 'column', gap: 2 }}>
                    <span style={{ ...chipBase, background: '#fef2f2', color: '#b91c1c', textDecoration: 'line-through' }}>
                        − {oldText || '(空)'}
                    </span>
                    <span style={{ ...chipBase, background: '#f0fdf4', color: '#15803d', fontWeight: 500 }}>
                        + {newText || '(清空)'}
                    </span>
                </div>
            )
        }

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
                width: 90,
                fixed: 'left',
                render: (v: number) => <Tag color="blue">#{v}</Tag>,
            })
            // 变更汇总列：变更字段数 + 字段名（最多 2 个，多余折叠为 +N）
            columns.push({
                title: '变更',
                dataIndex: '_changes',
                width: 170,
                fixed: 'left',
                render: (_: unknown, row: any) => {
                    const n = changedCountOf(row)
                    if (n === 0) {
                        return <Tag style={{ margin: 0, color: '#6b7280', background: '#f3f4f6', borderColor: '#e5e7eb' }}>无变化</Tag>
                    }
                    const names: string[] = Object.keys(row.field_diffs)
                    return (
                        <span>
                            <Tag color="blue" style={{ margin: '0 4px 2px 0' }}>{n} 处</Tag>
                            {names.slice(0, 2).map(nm => (
                                <Tag key={nm} color="default" style={{ margin: '0 4px 2px 0' }}>{nm}</Tag>
                            ))}
                            {names.length > 2 && <Tag style={{ margin: 0 }}>+{names.length - 2}</Tag>}
                        </span>
                    )
                },
            })
        }

        // 每个字段列：update 模式仅展示参考列与变化字段（聚焦变更）；变化字段渲染 diff chip
        allFieldNames.forEach(fname => {
            const isKeyCol = kvKeys.includes(fname)
            const isDiffCol = diffKeys.includes(fname)
            columns.push({
                title: isKeyCol ? <span style={{ color: '#7c3aed' }}>🔑 {fname}</span> : fname,
                dataIndex: ['field_sample', fname],
                ellipsis: !isDiffCol,
                render: (_: unknown, row: any) => {
                    const previewVal = row.field_sample?.[fname]
                    const diff = row.field_diffs?.[fname]
                    // 变化字段：红/绿 chip 对比
                    if (diff) {
                        return renderDiffCell(diff)
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
                {/* 命中但全部无字段变化 → 区分提示 */}
                {!isNew && report && report.update_changed_count === 0 && (
                    <Alert
                        type="info"
                        showIcon
                        style={{ marginBottom: 8 }}
                        message={`已匹配 ${report.update_count} 行已有数据，但字段值均与现有数据一致，无需更新`}
                    />
                )}
                <Table
                    size="small"
                    pagination={{ pageSize: 20 }}
                    scroll={{ x: 700, y: 360 }}
                    dataSource={preview.map((r, i) => ({ ...r, __key: `${mode}-${i}` }))}
                    rowKey="__key"
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
        // 有实际字段变化的更新行数（旧任务报告缺省时按"全部有变化"处理，避免误报无变化）
        const updateChangedCount: number = report.update_changed_count ?? updateCount
        const hasUpsert = updateCount > 0
        const multiConflict = report.multi_key_conflicts ?? 0
        const plannedColumns: Array<{ name: string; field_type: string; sample_values?: string[] }> = report.planned_columns || []

        return (
            <div style={{ marginTop: 16 }}>
                {/* 进度 + 统计已整合至上方进度面板 */}

                {multiConflict > 0 && (
                    <Alert
                        type="warning"
                        style={{ marginBottom: 12 }}
                        showIcon
                        message={`参考列匹配到 ${multiConflict} 组多行冲突（同 key 对应多条已有数据），将取 ID 最小的一行更新`}
                    />
                )}

                {/* 无更新行区分提示：已选参考列但无命中 / 命中但字段均无变化 */}
                {matchKeys.length > 0 && updateCount === 0 && (
                    <Alert
                        type="info"
                        showIcon
                        style={{ marginBottom: 12 }}
                        message={`按参考列 ${matchKeys.join('、')} 比对分析完成：没有匹配到已有数据，全部 ${newCount} 行将作为新增导入`}
                    />
                )}
                {hasUpsert && updateChangedCount === 0 && (
                    <Alert
                        type="info"
                        showIcon
                        style={{ marginBottom: 12 }}
                        message={`命中 ${updateCount} 行已有数据，但字段值均与现有数据一致，本次不会产生实际更新`}
                    />
                )}

                {/* Diff 控制区 */}
                {renderDiffControls()}

                {/* 未知列提示 / 规划 —— 可勾选逐个决定是否创建 */}
                {(report.skipped_columns?.length > 0 || report.missing_required?.length > 0 || plannedColumns.length > 0) && (
                    <Alert
                        type={plannedColumns.length > 0 ? 'info' : 'warning'}
                        style={{ marginBottom: 12 }}
                        showIcon
                        message={
                            <div style={{ fontSize: 12 }}>
                                {plannedColumns.length > 0 && (
                                    <div>
                                        <div style={{ fontWeight: 600, marginBottom: 6 }}>
                                            <Tag color="blue" style={{ marginRight: 6 }}>新字段</Tag>
                                            检测到 {plannedColumns.length} 个文件里有、但表中尚未建立的字段
                                            {unknownColsStrategy === 'add_text_field'
                                                ? <span style={{ color: '#0284c7', marginLeft: 4 }}>— 勾选要自动创建的字段，未勾选的将被丢弃</span>
                                                : <span style={{ color: '#d97706', marginLeft: 4 }}>— 当前为「丢弃」策略，切换到上方高级设置开启自动新增</span>}
                                        </div>
                                        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                                            {plannedColumns.map((pc: any) => {
                                                const isDropped = droppedColumns.includes(pc.name)
                                                return (
                                                    <label
                                                        key={pc.name}
                                                        style={{
                                                            display: 'flex', alignItems: 'center', gap: 8,
                                                            padding: '4px 8px',
                                                            background: isDropped ? '#fef2f2' : '#f0fdf4',
                                                            border: `1px solid ${isDropped ? '#fecaca' : '#bbf7d0'}`,
                                                            borderRadius: 4,
                                                            cursor: unknownColsStrategy === 'add_text_field' ? 'pointer' : 'not-allowed',
                                                            opacity: unknownColsStrategy === 'add_text_field' ? 1 : 0.55,
                                                        }}
                                                    >
                                                        <Checkbox
                                                            checked={!isDropped}
                                                            disabled={unknownColsStrategy !== 'add_text_field'}
                                                            onChange={(e) => {
                                                                if (e.target.checked) {
                                                                    setDroppedColumns(prev => prev.filter(n => n !== pc.name))
                                                                } else {
                                                                    setDroppedColumns(prev => [...prev, pc.name])
                                                                }
                                                            }}
                                                        />
                                                        <span style={{ fontWeight: 500 }}>{pc.name}</span>
                                                        <Tag color={isDropped ? 'default' : 'blue'} style={{ margin: 0 }}>{pc.field_type}</Tag>
                                                        {pc.sample_values?.length > 0 && (
                                                            <span style={{ color: '#64748b', fontSize: 11 }}>
                                                                样本: {pc.sample_values.join(' / ')}
                                                            </span>
                                                        )}
                                                        {isDropped && (
                                                            <Tag color="red" style={{ marginLeft: 'auto', marginRight: 0 }}>将丢弃</Tag>
                                                        )}
                                                    </label>
                                                )
                                            })}
                                        </div>
                                        {unknownColsStrategy === 'add_text_field' && droppedColumns.length > 0 && (
                                            <div style={{ marginTop: 6, color: '#dc2626', fontSize: 11 }}>
                                                其中 {droppedColumns.length} 个字段被勾选丢弃，不会自动创建
                                            </div>
                                        )}
                                    </div>
                                )}
                                {report.skipped_columns?.length > 0 && plannedColumns.length === 0 && (
                                    <div>
                                        <Tag color="orange">已忽略的文件列</Tag>
                                        {report.skipped_columns.join(', ')}
                                        <span style={{ marginLeft: 8, color: '#d97706' }}>（自动新增字段已关闭，可在上方设置中开启）</span>
                                    </div>
                                )}
                                {report.missing_required?.length > 0 && (
                                    <div style={{ marginTop: 6 }}>
                                        <Tag color="red">必填但文件缺失</Tag>
                                        {report.missing_required.join(', ')}
                                    </div>
                                )}
                            </div>
                        }
                    />
                )}

                {/* 主预览 Tab：new/update 分 Tab；update Tab 常驻，空态区分"未选参考列 / 无匹配行" */}
                <Tabs
                    size="small"
                    defaultActiveKey={hasUpsert ? 'new' : 'errors'}
                    items={[
                        {
                            key: 'new',
                            label: `待新增 (${newCount})`,
                            disabled: newCount === 0,
                            children: renderDiffTable(report.new_preview, 'new', report),
                        },
                        {
                            key: 'update',
                            label: updateChangedCount < updateCount
                                ? `更新 (${updateChangedCount}/${updateCount})`
                                : `更新 (${updateCount})`,
                            children: renderDiffTable(report.update_preview, 'update', report),
                        },
                        {
                            key: 'errors',
                            label: `错误 / 警告 (${report.errors.length + report.warnings.length})`,
                            children: (
                                <>
                                    {report.errors.length > 0 && (
                                        <Table
                                            size="small" pagination={{ pageSize: 10 }}
                                            dataSource={report.errors.map((e: any, i: number) => ({ ...e, __key: `e${i}` }))} rowKey="__key"
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
                                                dataSource={report.warnings.map((w: any, i: number) => ({ ...w, __key: `w${i}` }))} rowKey="__key"
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
                        // ── 数据质量 Tab ──
                        ...((report as any).column_profiles?.length > 0 ? [{
                            key: 'quality',
                            label: `数据质量 (${(report as any).column_profiles.length})`,
                            children: renderQualityPanel(report),
                        }] : []),
                    ]}
                />

                {/* 操作按钮 */}
                <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 12 }}>
                    <Button onClick={handleReset}>取消</Button>
                    {hasErrors && (
                        <Button onClick={handleDownloadFailed} icon={<DownloadOutlined />}>下载失败行</Button>
                    )}
                    <Tooltip title={matchKeys.length > 0
                        ? `将按参考列 ${matchKeys.join(', ')} 执行 upsert（新增 ${newCount} / 更新 ${updateChangedCount} / 无变化 ${Math.max(0, updateCount - updateChangedCount)}）`
                        : '当前全部作为新增导入'}>
                        <Button
                            type="primary"
                            onClick={handleConfirm}
                            disabled={newCount + updateChangedCount === 0}
                        >
                            确认导入（新增 {newCount} / 更新 {updateChangedCount}）
                        </Button>
                    </Tooltip>
                </div>
            </div>
        )
    }

    return (
        <div>
            {phase === 'idle' && (
                <Dragger
                    multiple={false}
                    accept={ACCEPTED_EXT.join(',')}
                    beforeUpload={beforeUpload}
                >
                    <p className="ant-upload-drag-icon"><InboxOutlined /></p>
                    <p className="ant-upload-text">点击或拖拽文件到此处</p>
                    <p className="ant-upload-hint">支持 CSV / JSON / XLSX — 先看全量数据，再选参考列执行更新数据比对分析</p>
                </Dragger>
            )}

            {(phase === 'analyzing' || phase === 'importing') && (
                <Alert type="info" message="处理中..." style={{ marginTop: 12 }} showIcon />
            )}

            {renderProgressSummary()}
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
}

// ─────────────── 迷你统计卡片 ───────────────

/** 迷你统计卡片 —— 进度面板与数据质量面板共用 */
function MiniStat({ label, value, color, compact }: { label: string; value: number | string; color: string; compact?: boolean }) {
    return compact ? (
        <div style={{
            padding: '6px 12px', background: color + '12', borderRadius: 6,
            borderLeft: `3px solid ${color}`, minWidth: 72, textAlign: 'center',
        }}>
            <div style={{ fontSize: 16, fontWeight: 700, color, lineHeight: 1.2 }}>{value}</div>
            <div style={{ fontSize: 11, color: '#64748b' }}>{label}</div>
        </div>
    ) : (
        <div style={{
            padding: '8px 14px', background: color + '10', borderRadius: 6,
            borderLeft: `3px solid ${color}`, minWidth: 90,
        }}>
            <div style={{ fontSize: 18, fontWeight: 700, color }}>{value}</div>
            <div style={{ fontSize: 11, color: '#64748b' }}>{label}</div>
        </div>
    )
}
