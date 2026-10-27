/** 插入数据表引用弹窗（从 DocumentEditorPage 抽出）.
 *
 * 页面侧把 `tablesQuery` 解包为 `tables` / `tablesLoading`，弹窗不依赖 React Query。
 */

import { InputNumber, Modal, Select, Space, Typography } from 'antd'

import type { TableSummary, View } from '@/api'
import { DEFAULT_REF_WIDTH, MAX_REF_WIDTH, MIN_REF_WIDTH } from '@/components/Document/refWidth'

const { Text } = Typography

export default function InsertTableModal({
  open,
  onOk,
  onCancel,
  tableId,
  onTableIdChange,
  viewId,
  onViewIdChange,
  limit,
  onLimitChange,
  width,
  onWidthChange,
  tables,
  tablesLoading,
  views,
  viewsLoading,
}: {
  open: boolean
  onOk: () => void
  onCancel: () => void
  tableId: number | null
  onTableIdChange: (tableId: number) => void
  viewId: number | null
  onViewIdChange: (viewId: number | null) => void
  limit: number | null
  onLimitChange: (limit: number | null) => void
  width: number
  onWidthChange: (width: number) => void
  tables: TableSummary[]
  tablesLoading: boolean
  views: View[]
  viewsLoading: boolean
}) {
  return (
    <Modal
      title="插入数据表引用"
      open={open}
      onOk={onOk}
      okButtonProps={{ disabled: tableId === null }}
      okText="插入"
      cancelText="取消"
      onCancel={onCancel}
      destroyOnHidden
    >
      <Space direction="vertical" style={{ width: '100%' }} size={12}>
        <Select
          data-testid="insert-table-select"
          style={{ width: '100%' }}
          placeholder="选择要引用的数据表"
          value={tableId}
          onChange={v => onTableIdChange(v)}
          options={tables.map(t => ({ value: t.id, label: t.name }))}
          loading={tablesLoading}
          showSearch
          optionFilterProp="label"
        />
        <Select
          data-testid="insert-table-view"
          style={{ width: '100%' }}
          placeholder="全部数据（不按视图过滤）"
          value={viewId ?? undefined}
          onChange={v => onViewIdChange(v ?? null)}
          options={views.map(v => ({ value: v.id, label: v.name }))}
          loading={viewsLoading}
          disabled={tableId === null}
          allowClear
        />
        <InputNumber
          style={{ width: '100%' }}
          min={1}
          max={50}
          placeholder="每页行数（默认 20，上限 50）"
          value={limit}
          onChange={v => onLimitChange(v)}
        />
        <div>
          <Text strong style={{ display: 'block', marginBottom: 4 }}>显示宽度</Text>
          <InputNumber
            data-testid="insert-table-width"
            style={{ width: '100%' }}
            min={MIN_REF_WIDTH}
            max={MAX_REF_WIDTH}
            addonAfter="%"
            value={width}
            onChange={v => {
              if (typeof v === 'number') onWidthChange(v)
            }}
          />
          <Text type="secondary" style={{ fontSize: 12 }}>
            默认 {DEFAULT_REF_WIDTH}%，范围 {MIN_REF_WIDTH}–{MAX_REF_WIDTH}%；插入后也可在预览中调整。
          </Text>
        </div>
        <Text type="secondary" style={{ fontSize: 12 }}>
          以只读表格形式在文档中动态引用所选数据表，数据随表内容实时更新；选择视图后按该视图的过滤 / 排序取数。
        </Text>
      </Space>
    </Modal>
  )
}
