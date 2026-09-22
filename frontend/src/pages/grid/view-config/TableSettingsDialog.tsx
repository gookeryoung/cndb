/** 表格显示设置 Dialog — 全局用户偏好（间距 / 每页行数 / 边框 / 表头 / 斑马纹） */

import { useMemo, useEffect, useState } from 'react'
import { Button, Modal, Select, Switch, App as AntApp } from 'antd'
import { useTableSettingsStore } from '@/store'
import { DEFAULT_TABLE_SETTINGS } from '@/theme/tableSettings'

interface TableSettingsDialogProps {
  open: boolean
  onClose: () => void
  onAfterSave?: () => void
}

/** 表格显示设置对话框（持久化到浏览器 localStorage，对所有表生效） */
export default function TableSettingsDialog({ open, onClose, onAfterSave }: TableSettingsDialogProps) {
  const { message } = AntApp.useApp()
  const density = useTableSettingsStore(s => s.density)
  const defaultPageSize = useTableSettingsStore(s => s.defaultPageSize)
  const bordered = useTableSettingsStore(s => s.bordered)
  const showHeader = useTableSettingsStore(s => s.showHeader)
  const striped = useTableSettingsStore(s => s.striped)
  const updateSettings = useTableSettingsStore(s => s.updateSettings)
  const resetSettings = useTableSettingsStore(s => s.resetSettings)
  const settings = useMemo(
    () => ({ density, defaultPageSize, bordered, showHeader, striped }),
    [density, defaultPageSize, bordered, showHeader, striped],
  )
  const [draft, setDraft] = useState(settings)

  useEffect(() => {
    if (open) setDraft(settings)
  }, [open, settings])

  const updateDraft = <K extends keyof typeof draft>(key: K, value: typeof draft[K]) => {
    setDraft(prev => ({ ...prev, [key]: value }))
  }

  const handleOk = () => {
    updateSettings(draft)
    onAfterSave?.()
    message.success('设置已保存（适用于所有数据表）')
    onClose()
  }

  const handleReset = () => {
    resetSettings()
    setDraft({ ...DEFAULT_TABLE_SETTINGS })
    message.info('已重置为默认值')
  }

  return (
    <Modal
      title="显示模式"
      open={open}
      onCancel={onClose}
      width={400}
      okText="保存"
      cancelText="取消"
      onOk={handleOk}
      destroyOnHidden
      className="table-settings-dialog"
      footer={[
        <Button key="reset" size="small" onClick={handleReset}>重置默认</Button>,
        <Button key="cancel" size="small" onClick={onClose}>取消</Button>,
        <Button key="ok" size="small" type="primary" onClick={handleOk}>保存</Button>,
      ]}
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        {/* 内容间距 — 横向 radiogroup 样式 */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 13, color: '#374151', whiteSpace: 'nowrap', minWidth: 56 }}>间距</span>
          <Select
            size="small"
            value={draft.density}
            onChange={(v: typeof draft.density) => updateDraft('density', v)}
            style={{ flex: 1 }}
            options={[
              { value: 'compact', label: '紧凑' },
              { value: 'comfortable', label: '适中' },
              { value: 'spacious', label: '宽松' },
            ]}
          />
        </div>

        {/* 每页行数 */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 13, color: '#374151', whiteSpace: 'nowrap', minWidth: 56 }}>每页</span>
          <Select
            size="small"
            value={draft.defaultPageSize}
            onChange={(v: number) => updateDraft('defaultPageSize', v)}
            style={{ flex: 1 }}
            options={[
              { value: 25, label: '25 条' },
              { value: 50, label: '50 条' },
              { value: 100, label: '100 条' },
              { value: 200, label: '200 条' },
            ]}
          />
        </div>

        {/* 显示选项 — 三开关横排 */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 16, paddingTop: 4, borderTop: '1px solid #f0f0f0' }}>
          <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6, cursor: 'pointer', fontSize: 13 }}>
            <Switch size="small" checked={draft.bordered} onChange={(v) => updateDraft('bordered', v)} />
            <span>边框</span>
          </label>
          <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6, cursor: 'pointer', fontSize: 13 }}>
            <Switch size="small" checked={draft.showHeader} onChange={(v) => updateDraft('showHeader', v)} />
            <span>表头</span>
          </label>
          <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6, cursor: 'pointer', fontSize: 13 }}>
            <Switch size="small" checked={draft.striped} onChange={(v) => updateDraft('striped', v)} />
            <span>斑马纹</span>
          </label>
        </div>
      </div>

      <div style={{ marginTop: 10, fontSize: 11, color: '#9ca3af', textAlign: 'center' }}>
        保存到浏览器，对所有视图生效
      </div>
    </Modal>
  )
}
