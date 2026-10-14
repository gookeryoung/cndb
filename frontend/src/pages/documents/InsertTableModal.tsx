/** 插入数据表引用弹窗（从 DocumentEditorPage 抽出）.
 *
 * 页面侧把 `tablesQuery` 解包为 `tables` / `tablesLoading`，弹窗不依赖 React Query。
 */

import { InputNumber, Modal, Select, Space, Typography } from 'antd'

import type { TableSummary } from '@/api'

const { Text } = Typography

export default function InsertTableModal({
  open,
  onOk,
  onCancel,
  tableId,
  onTableIdChange,
  limit,
  onLimitChange,
  tables,
  tablesLoading,
}: {
  open: boolean
  onOk: () => void
  onCancel: () => void
  tableId: number | null
  onTableIdChange: (tableId: number) => void
  limit: number | null
  onLimitChange: (limit: number | null) => void
  tables: TableSummary[]
  tablesLoading: boolean
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
          style={{ width: '100%' }}
          placeholder="选择要引用的数据表"
          value={tableId}
          onChange={v => onTableIdChange(v)}
          options={tables.map(t => ({ value: t.id, label: t.name }))}
          loading={tablesLoading}
          showSearch
          optionFilterProp="label"
        />
        <InputNumber
          style={{ width: '100%' }}
          min={1}
          max={50}
          placeholder="每页行数（默认 20，上限 50）"
          value={limit}
          onChange={v => onLimitChange(v)}
        />
        <Text type="secondary" style={{ fontSize: 12 }}>
          以只读表格形式在文档中动态引用所选数据表，数据随表内容实时更新。
        </Text>
      </Space>
    </Modal>
  )
}
