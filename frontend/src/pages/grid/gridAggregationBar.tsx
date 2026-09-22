/** 底部选中行聚合条 — 数值列 count/sum/avg 统计与批量操作（从 GridPage 抽出）. */

import { Button, Modal, Space, Tag } from 'antd'
import { CopyOutlined, DeleteOutlined } from '@ant-design/icons'

interface GridAggregationBarProps {
  selectedCount: number
  aggregates: Record<string, { count: number; sum: number; avg: number }>
  copyLoading: boolean
  deleteLoading: boolean
  onCopy: () => void
  onDelete: () => void
  onClear: () => void
}

export default function GridAggregationBar({
  selectedCount, aggregates, copyLoading, deleteLoading, onCopy, onDelete, onClear,
}: GridAggregationBarProps) {
  if (selectedCount <= 0) return null
  return (
    <div style={{ padding: '8px 16px', borderTop: '1px solid var(--cn-border)', background: 'var(--cn-bg-container)', display: 'flex', alignItems: 'center', gap: 16, flexWrap: 'wrap' }}>
      <Tag color="blue" style={{ margin: 0 }}>已选 {selectedCount} 行</Tag>
      <Space size="middle">
        {Object.entries(aggregates).map(([name, a]) => (
          <Tag key={name} style={{ margin: 0 }}>{name}: {a.count}条 · 和 {a.sum.toFixed(2)} · 均值 {a.avg.toFixed(2)}</Tag>
        ))}
      </Space>
      <div style={{ marginLeft: 'auto' }}>
        <Space>
          <Button size="small" icon={<CopyOutlined />} loading={copyLoading} onClick={onCopy}>复制选中</Button>
          <Button size="small" danger icon={<DeleteOutlined />}
            onClick={() => Modal.confirm({
              title: `确定删除 ${selectedCount} 行？`,
              onOk: onDelete,
            })}
            loading={deleteLoading}>删除选中</Button>
          <Button size="small" onClick={onClear}>取消选择</Button>
        </Space>
      </div>
    </div>
  )
}
