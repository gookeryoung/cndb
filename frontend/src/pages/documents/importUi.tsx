/** 文档导入三入口（单文件 / 文件夹 / Obsidian 库）共用的 UI 片段.
 *
 * 口径统一在这里，三种模式只传内容不各自拼样式：
 * - ``ImportDropzone``：虚线拖放区（图标徽标 + 强标题 + 次要副标题 + 主按钮 + 说明气泡 + 已选状态）；
 * - ``ImportSummary``：解析结果的单行紧凑统计（零值走次要色）；
 * - ``ImportConflictOptions`` / ``ImportSwitch`` / ``ImportStatusRadio`` / ``ImportOptionsPanel``：选项区同一套排布；
 * - ``ImportTruncatedHint``：预览截断提示。
 *
 * 图标语言也统一：模式选择器、拖放区、主按钮都用同一枚图标（单文件 / 文件夹 / zip 库）。
 */
import type { ReactNode } from 'react'
import { Button, Popover, Radio, Space, Switch, Tooltip, Typography } from 'antd'
import { QuestionCircleOutlined } from '@ant-design/icons'
import type { VaultConflictPolicy } from '@/api/documents'

/** 同名冲突策略：通用导入与 Obsidian 库导入共用一份（文案与提示一致） */
export const IMPORT_CONFLICT_OPTIONS: { value: VaultConflictPolicy; label: string; hint: string }[] = [
  { value: 'rename', label: '保留两份（自动改名）', hint: '同名文档追加「 (2)」' },
  { value: 'overwrite', label: '覆盖已有文档', hint: '生成新版本，历史可回溯' },
  { value: 'skip', label: '跳过同名文档', hint: '只导入新增的文件' },
]

export interface ImportDropzoneProps {
  /** 模式图标：与模式选择器、主按钮同源 */
  icon: ReactNode
  title: string
  subtitle: string
  actionLabel: string
  onPick: () => void
  /** 拖放区整体的 testid */
  testId: string
  pickTestId: string
  helpTestId?: string
  disabled?: boolean
  /** 说明气泡：标题 + 内容；两者都给才渲染入口 */
  helpTitle?: string
  help?: ReactNode
  /** 已选状态（一行文本 / 标签），未选时不传 */
  selected?: ReactNode
}

/** 统一的导入拖放区：整块可点，键盘 / 读屏走里面的真实按钮 */
export function ImportDropzone({
  icon,
  title,
  subtitle,
  actionLabel,
  onPick,
  testId,
  pickTestId,
  helpTestId,
  disabled = false,
  helpTitle,
  help,
  selected,
}: ImportDropzoneProps) {
  const pick = () => {
    if (!disabled) onPick()
  }

  return (
    <div
      data-testid={testId}
      onClick={pick}
      style={{
        border: '1px dashed var(--cn-border-soft)',
        borderRadius: 10,
        padding: '16px 16px 12px',
        textAlign: 'center',
        background: 'var(--cn-bg-subtle)',
        cursor: disabled ? 'default' : 'pointer',
      }}
    >
      <Space size={12} align="center" style={{ justifyContent: 'center', width: '100%' }}>
        <span
          aria-hidden
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            justifyContent: 'center',
            width: 40,
            height: 40,
            borderRadius: 10,
            border: '1px solid var(--cn-border-soft)',
            background: 'var(--cn-bg-container)',
            color: 'var(--cn-brand-color)',
            fontSize: 20,
          }}
        >
          {icon}
        </span>
        <span style={{ textAlign: 'left' }}>
          <Typography.Text strong>{title}</Typography.Text>
          <br />
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {subtitle}
          </Typography.Text>
        </span>
      </Space>
      <Space size={8} align="center" style={{ marginTop: 12 }} onClick={event => event.stopPropagation()}>
        <Button type="primary" disabled={disabled} data-testid={pickTestId} onClick={pick}>
          {actionLabel}
        </Button>
        {help && helpTitle ? (
          <Popover trigger="click" placement="bottom" title={helpTitle} content={help}>
            <Button
              type="link"
              size="small"
              icon={<QuestionCircleOutlined />}
              data-testid={helpTestId}
            >
              格式说明
            </Button>
          </Popover>
        ) : null}
      </Space>
      {selected ? <div style={{ marginTop: 8 }}>{selected}</div> : null}
    </div>
  )
}

export interface ImportSummaryItem {
  key: string
  label: string
  value: ReactNode
  /** 值为零：走次要色，避免一排 0 抢注意力 */
  zero?: boolean
}

/** 解析结果的单行紧凑统计（不占一整块表格） */
export function ImportSummary({ items, testId }: { items: ImportSummaryItem[]; testId: string }) {
  return (
    <div
      data-testid={testId}
      style={{ display: 'flex', flexWrap: 'wrap', gap: '4px 20px', fontSize: 12 }}
    >
      {items.map(item => (
        <span key={item.key} style={{ whiteSpace: 'nowrap' }}>
          <Typography.Text type={item.zero ? 'secondary' : undefined} style={{ fontSize: 12 }}>
            {item.label}
          </Typography.Text>{' '}
          <span style={{ fontWeight: 600 }}>{item.value}</span>
        </span>
      ))}
    </div>
  )
}

/** 选项区面板：浅底 + 细边框，三种模式共用 */
export function ImportOptionsPanel({ children, testId }: { children: ReactNode; testId: string }) {
  return (
    <div
      data-testid={testId}
      style={{
        display: 'flex',
        flexWrap: 'wrap',
        alignItems: 'center',
        gap: '10px 24px',
        padding: '10px 12px',
        border: '1px solid var(--cn-border-soft)',
        borderRadius: 8,
        background: 'var(--cn-bg-subtle)',
      }}
    >
      {children}
    </div>
  )
}

/** 单个开关 + 12px 标签，解释统一放悬停提示（不再堆在标签里） */
export function ImportSwitch({
  label,
  checked,
  onChange,
  disabled = false,
  tooltip,
  testId,
}: {
  label: string
  checked: boolean
  onChange: (checked: boolean) => void
  disabled?: boolean
  tooltip?: string
  testId: string
}) {
  const content = (
    <Space size={6}>
      <Switch size="small" checked={checked} onChange={onChange} disabled={disabled} data-testid={testId} />
      <Typography.Text type={disabled ? 'secondary' : undefined} style={{ fontSize: 12 }}>
        {label}
      </Typography.Text>
    </Space>
  )
  return tooltip ? <Tooltip title={tooltip}>{content}</Tooltip> : content
}

/** 文档状态（草稿 / 已发布）选择器，靠右收尾 */
export function ImportStatusRadio({
  value,
  onChange,
}: {
  value: 'draft' | 'published'
  onChange: (value: 'draft' | 'published') => void
}) {
  return (
    <Space size={6} style={{ marginLeft: 'auto' }}>
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
        状态
      </Typography.Text>
      <Radio.Group
        value={value}
        onChange={event => onChange(event.target.value as 'draft' | 'published')}
        optionType="button"
        size="small"
        options={[
          { value: 'draft', label: '草稿' },
          { value: 'published', label: '已发布' },
        ]}
      />
    </Space>
  )
}

/** 同名冲突处理：标题 + 三档单选（提示随行），两种导入共用 */
export function ImportConflictOptions({
  value,
  onChange,
  testId,
}: {
  value: VaultConflictPolicy
  onChange: (value: VaultConflictPolicy) => void
  testId: string
}) {
  return (
    <div data-testid={testId}>
      <Typography.Text strong style={{ fontSize: 12 }}>
        同名文档处理方式
      </Typography.Text>
      <Radio.Group
        value={value}
        onChange={event => onChange(event.target.value as VaultConflictPolicy)}
        style={{ display: 'flex', flexDirection: 'column', gap: 4, marginTop: 4 }}
      >
        {IMPORT_CONFLICT_OPTIONS.map(option => (
          <Radio key={option.value} value={option.value}>
            {option.label}
            <Typography.Text type="secondary" style={{ marginLeft: 8, fontSize: 12 }}>
              {option.hint}
            </Typography.Text>
          </Radio>
        ))}
      </Radio.Group>
    </div>
  )
}

/** 预览截断提示 */
export function ImportTruncatedHint({ count }: { count: number }) {
  return (
    <Typography.Text type="secondary" style={{ fontSize: 12 }}>
      预览仅展示前 {count} 篇，其余同样会被导入。
    </Typography.Text>
  )
}
