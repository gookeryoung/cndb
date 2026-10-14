/** 转让工作区所有权弹窗.
 *
 * 从 WorkspaceSettingsContent 抽出；接收方选项由页面侧预先算好，本组件不认识成员模型。
 */

import { Modal, Select } from 'antd'

export default function TransferOwnerModal({
  open,
  onCancel,
  onOk,
  options,
  value,
  onChange,
  confirming,
}: {
  open: boolean
  onCancel: () => void
  onOk: () => void
  options: Array<{ value: string; label: string }>
  value: string | null
  onChange: (value: string) => void
  confirming: boolean
}) {
  return (
    <Modal
      title="转让工作区所有权"
      open={open}
      onCancel={onCancel}
      onOk={onOk}
      okText="确认转让"
      okType="danger"
      confirmLoading={confirming}
      okButtonProps={{ disabled: !value }}
      destroyOnHidden
    >
      <div style={{ marginBottom: 8, color: 'var(--cn-text-secondary)', fontSize: 13 }}>
        将工作区所有权转让给下列成员。转让后您将失去所有者特权，回落到编辑者角色。
      </div>
      <Select
        showSearch
        placeholder="选择接收者"
        style={{ width: '100%' }}
        value={value}
        onChange={onChange}
        options={options}
        filterOption={(input, option) =>
          (option?.label ?? '').toLowerCase().includes(input.toLowerCase())
        }
      />
    </Modal>
  )
}
