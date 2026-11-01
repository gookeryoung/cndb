/** 工作区功能模块卡片式选型（ADR 0080 D8）—— 创建弹窗与工作区设置共用.
 *
 * 三张整卡可点击切换：图标 + 名称 + 说明；选中态品牌色描边。
 * 至少保留一个模块：最后一个选中项不可取消（点击无效并给 Tooltip 提示）。
 * 作为 antd Form 受控组件使用（Form.Item name 提供 value/onChange）。
 */

import { Space, Tooltip, Typography } from 'antd'
import { DatabaseOutlined, FileTextOutlined, ToolOutlined, CheckCircleFilled } from '@ant-design/icons'
import {
  WORKSPACE_MODULES, WORKSPACE_MODULE_LABEL, WORKSPACE_MODULE_HINT,
} from '@/utils/workspaceModules'
import type { WorkspaceModule } from '@/utils/workspaceModules'

const { Text } = Typography

/** 模块图标（与 MainLayout 页签同源语义） */
const MODULE_ICON: Record<WorkspaceModule, React.ReactNode> = {
  tables: <DatabaseOutlined />,
  documents: <FileTextOutlined />,
  design: <ToolOutlined />,
}

/** 模块选中态描边色（与页签语义色一致） */
const MODULE_COLOR: Record<WorkspaceModule, string> = {
  tables: '#1677ff',
  documents: '#d48806',
  design: '#722ed1',
}

interface Props {
  value?: WorkspaceModule[]
  onChange?: (value: WorkspaceModule[]) => void
  disabled?: boolean
}

export default function ModuleCheckCards({ value, onChange, disabled }: Props) {
  const selected = value ?? []
  const toggle = (m: WorkspaceModule) => {
    if (disabled || !onChange) return
    if (selected.includes(m)) {
      // 至少一项：最后一个选中项不可取消
      if (selected.length <= 1) return
      onChange(selected.filter(x => x !== m))
    } else {
      // 按固定顺序归位，保证勾选 UI 与校验顺序一致
      const order: readonly WorkspaceModule[] = WORKSPACE_MODULES
      onChange(order.filter(x => x === m || selected.includes(x)))
    }
  }

  return (
    <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }} role="group" aria-label="功能模块选型">
      {WORKSPACE_MODULES.map((m) => {
        const active = selected.includes(m)
        const lastOne = active && selected.length <= 1
        const card = (
          <div
            key={m}
            role="checkbox"
            aria-checked={active}
            aria-disabled={disabled || lastOne}
            data-testid={`module-card-${m}`}
            data-checked={active}
            title={
              lastOne
                ? '至少保留一个功能模块'
                : WORKSPACE_MODULE_HINT[m]
            }
            onClick={() => toggle(m)}
            style={{
              flex: '1 1 140px',
              minWidth: 140,
              padding: '10px 12px',
              borderRadius: 8,
              border: `1px solid ${active ? MODULE_COLOR[m] : 'var(--cn-border, #d9d9d9)'}`,
              background: active ? 'var(--cn-primary-bg, #e6f4ff)' : 'var(--cn-bg-container, #fff)',
              cursor: disabled ? 'not-allowed' : 'pointer',
              opacity: disabled ? 0.6 : 1,
              display: 'flex',
              flexDirection: 'column',
              gap: 4,
              transition: 'border-color 0.2s, background 0.2s',
              userSelect: 'none',
            }}
          >
            <Space size={6} style={{ justifyContent: 'space-between', width: '100%' }}>
              <Space size={6}>
                <span style={{ color: MODULE_COLOR[m], fontSize: 16 }}>
                  {MODULE_ICON[m]}
                </span>
                <Text strong>{WORKSPACE_MODULE_LABEL[m]}</Text>
              </Space>
              {active && (
                <CheckCircleFilled style={{ color: MODULE_COLOR[m] }} />
              )}
            </Space>
            <Text type="secondary" style={{ fontSize: 12, lineHeight: 1.4 }}>
              {WORKSPACE_MODULE_HINT[m]}
            </Text>
          </div>
        )
        return lastOne && !disabled ? <Tooltip key={m} title="至少保留一个功能模块">{card}</Tooltip> : card
      })}
    </div>
  )
}
