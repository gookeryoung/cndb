/**
 * 引用宽度控件（ADR 0051）：编辑态嵌入块上的紧凑宽度选择。
 *
 * 只负责收集 25–100 的百分比并回调；改写正文占位符由页面侧完成。
 * 不传 `onChange` 时不渲染（查看模式 / 游客分享页只读）。
 */

import { useState } from 'react'
import { Button, InputNumber, Popover, Space, Typography } from 'antd'

import { DEFAULT_REF_WIDTH, MAX_REF_WIDTH, MIN_REF_WIDTH, parseRefWidth } from './refWidth'

const { Text } = Typography

const PRESETS = [25, 50, 75, 100] as const

export default function RefWidthControl({
  value,
  onChange,
  testId,
}: {
  value: number
  onChange: (width: number) => void
  testId?: string
}) {
  const [open, setOpen] = useState(false)
  const current = parseRefWidth(value)

  const apply = (next: number | null) => {
    if (next === null) return
    onChange(parseRefWidth(next))
    setOpen(false)
  }

  return (
    <Popover
      open={open}
      onOpenChange={setOpen}
      trigger="click"
      title="显示宽度"
      content={(
        <div style={{ width: 220 }} data-testid={testId ? `${testId}-panel` : undefined}>
          <Space wrap size={4}>
            {PRESETS.map(p => (
              <Button
                key={p}
                size="small"
                type={current === p ? 'primary' : 'default'}
                data-testid={testId ? `${testId}-preset-${p}` : undefined}
                onClick={() => apply(p)}
              >
                {p}%
              </Button>
            ))}
          </Space>
          <div style={{ marginTop: 8 }}>
            <InputNumber
              aria-label="自定义显示宽度"
              data-testid={testId ? `${testId}-custom` : undefined}
              min={MIN_REF_WIDTH}
              max={MAX_REF_WIDTH}
              value={current}
              addonAfter="%"
              style={{ width: '100%' }}
              onChange={apply}
            />
          </div>
          <Text type="secondary" style={{ fontSize: 11 }}>
            默认 {DEFAULT_REF_WIDTH}%，范围 {MIN_REF_WIDTH}–{MAX_REF_WIDTH}%
          </Text>
        </div>
      )}
    >
      <Button
        size="small"
        type="text"
        data-testid={testId}
        aria-label="调整显示宽度"
        onClick={e => e.preventDefault()}
      >
        宽度 {current}%
      </Button>
    </Popover>
  )
}
