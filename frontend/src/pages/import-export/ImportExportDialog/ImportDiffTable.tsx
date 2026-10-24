/** Diff 表格 —— 新增行绿底 / 更新行蓝底 + 字段级 old→new chip 对比与变更汇总列. */

import type { CSSProperties } from 'react'
import { Alert, Empty, Table, Tag } from 'antd'
import { PlusCircleOutlined, EditOutlined } from '@ant-design/icons'
import { changedCountOf, collectDiffColumnKeys, diffChipStyle, fmtValue } from './importPreview'

interface ImportDiffTableProps {
  preview: any[] | undefined
  mode: 'new' | 'update'
  report?: any
  matchKeys: string[]
}

export default function ImportDiffTable({ preview, mode, report, matchKeys }: ImportDiffTableProps) {
    const isNew = mode === 'new'
    const rowBg = isNew
        ? 'var(--cn-mix-green-8-bg-container)'   // 新增绿
        : 'var(--cn-mix-blue-8-bg-container)'   // 更新蓝
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
                        <span style={{ color: 'var(--cn-text-muted)', fontSize: 13 }}>
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
                        <span style={{ color: 'var(--cn-text-muted)', fontSize: 13 }}>
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
                <span style={{ ...chipBase, background: 'var(--cn-mix-red-12-bg-container)', color: '#ef4444', textDecoration: 'line-through' }}>
                    − {oldText || '(空)'}
                </span>
                <span style={{ ...chipBase, background: 'var(--cn-mix-green-12-bg-container)', color: '#22c55e', fontWeight: 500 }}>
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
                    return <Tag style={{ margin: 0, color: 'var(--cn-text-muted)', background: 'var(--cn-bg-muted)', borderColor: 'var(--cn-border-soft)' }}>无变化</Tag>
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
                <div style={{ color: 'var(--cn-text-muted)', fontSize: 12, marginTop: 4 }}>仅预览前 200 行，完整数据将全部导入</div>
            )}
        </>
    )
}
