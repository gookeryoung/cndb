/** 数据质量面板 —— 列画像 / 清洗建议勾选 / 类型冲突与分布. */

import { Progress, Empty, Tag, Collapse, Tooltip, Checkbox } from 'antd'
import { SettingOutlined } from '@ant-design/icons'
import { getFieldTypeLabel } from '@/utils/fieldTypeMeta'
import MiniStat from './MiniStat'

import type { Dispatch, SetStateAction } from 'react'

interface ImportQualityPanelProps {
  report: any
  selectedCleaningActions: any[]
  setSelectedCleaningActions: Dispatch<SetStateAction<any[]>>
}

export default function ImportQualityPanel({
  report,
  selectedCleaningActions,
  setSelectedCleaningActions,
}: ImportQualityPanelProps) {
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
                <div style={{ marginBottom: 16, padding: 12, background: 'var(--cn-bg-subtle)', borderRadius: 8, border: '1px solid var(--cn-border-soft)' }}>
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
                            <Tag color="blue">{getFieldTypeLabel(p.inferred_type)}</Tag>
                            <Tag color={p.confidence >= 0.9 ? 'green' : p.confidence >= 0.7 ? 'orange' : 'red'} style={{ margin: 0 }}>
                                自动识别 {Math.round(p.confidence * 100)}%
                            </Tag>
                        </div>
                    ),
                    children: (
                        <div style={{ fontSize: 13 }}>
                            <div style={{ display: 'flex', gap: 24, marginBottom: 10 }}>
                                <span>唯一值 <b>{p.unique_count}</b></span>
                                <span>空值 <b>{p.null_count}</b></span>
                                {p.fallback_type && <span style={{ color: '#ef4444' }}>部分值无法识别，建议改用：{getFieldTypeLabel(p.fallback_type)}</span>}
                            </div>
                            {/* 空值率进度条 */}
                            <div style={{ marginBottom: 10 }}>
                                <span style={{ color: 'var(--cn-text-muted)', marginRight: 8 }}>空值率</span>
                                <Progress
                                    size="small"
                                    percent={Math.round(p.null_ratio * 100)}
                                    strokeColor={p.null_ratio > 0.5 ? '#ef4444' : p.null_ratio > 0.2 ? '#f59e0b' : '#22c55e'}
                                />
                            </div>
                            {/* 数值列 min/max/mean */}
                            {p.min !== undefined && (
                                <div style={{ marginBottom: 10, color: 'var(--cn-text-secondary)' }}>
                                    最小 <b>{p.min}</b> / 最大 <b>{p.max}</b> / 均值 <b>{p.mean?.toFixed(2)}</b>
                                </div>
                            )}
                            {/* 类型冲突 */}
                            {p.type_conflicts?.length > 0 && (
                                <div style={{ marginBottom: 10 }}>
                                    <div style={{ color: '#ef4444', marginBottom: 4 }}>⚠ 类型冲突（{p.type_conflicts.length} 条）</div>
                                    {p.type_conflicts.slice(0, 5).map((c: any, i: number) => (
                                        <div key={i} style={{ color: 'var(--cn-text-muted)' }}>
                                            行 {c.row_number}: <code style={{ background: 'var(--cn-bg-muted)', padding: '1px 4px', borderRadius: 3 }}>{String(c.value).slice(0, 40)}</code>
                                            被识别为 <Tag>{c.conflicting_type}</Tag>
                                        </div>
                                    ))}
                                </div>
                            )}
                            {/* 异常值 */}
                            {p.outliers?.length > 0 && (
                                <div style={{ marginBottom: 10 }}>
                                    <div style={{ color: '#f59e0b', marginBottom: 4 }}>⚠ 异常值（{p.outliers.length} 个）</div>
                                    <div style={{ color: 'var(--cn-text-muted)' }}>
                                        {p.outliers.slice(0, 5).map((o: any, i: number) => (
                                            <Tag key={i} color="orange" style={{ marginBottom: 2 }}>{String(o.value)}</Tag>
                                        ))}
                                    </div>
                                </div>
                            )}
                            {/* 分布直方图（数值列） */}
                            {p.distribution_bins?.length > 0 && (
                                <div style={{ marginBottom: 10 }}>
                                    <div style={{ color: 'var(--cn-text-secondary)', marginBottom: 4 }}>数值分布</div>
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
                                    <div style={{ color: 'var(--cn-text-secondary)', marginBottom: 4 }}>Top {Math.min(5, p.value_counts.length)} 取值</div>
                                    {p.value_counts.slice(0, 5).map((v: any, i: number) => (
                                        <div key={i} style={{ display: 'flex', justifyContent: 'space-between', color: 'var(--cn-text-muted)' }}>
                                            <span style={{ maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis' }}>{String(v.value)}</span>
                                            <span>{v.count}</span>
                                        </div>
                                    ))}
                                </div>
                            )}
                            {/* 样本值 */}
                            {p.sample_values?.length > 0 && (
                                <div style={{ color: 'var(--cn-text-muted)' }}>
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
