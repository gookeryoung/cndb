/** 装配约束面板（ADR 0086 §7）：只读展示 IR v4 constraints.
 *
 * 前端零求解（I7）：只呈现后端求解结果（类型 / 引用 / 状态 / 行号），
 * 点击定位到源行；不提供图形化拖拽求解。
 */

import { Button, Space, Tag, Tooltip, Typography } from 'antd'
import type { DesignIRConstraint } from '@/api'

const { Text } = Typography

const TYPE_LABEL: Record<string, string> = {
  fixed: '固定',
  coincident: '重合',
  concentric: '同心',
  distance: '距离',
  angle: '角度',
}

interface Props {
  constraints: DesignIRConstraint[]
  /** 点击约束跳转到源行（编辑器 revealLine） */
  onReveal?: (line: number) => void
}

export default function DesignConstraintsPanel({ constraints, onReveal }: Props) {
  if (constraints.length === 0) return null
  return (
    <div className="cn-dsl-constraints" data-testid="design-constraints">
      <Space size={4} wrap align="center">
        <Text type="secondary">约束：</Text>
        {constraints.map(item => (
          <Tooltip
            key={item.id}
            title={`${item.a}${item.b ? ' ↔ ' + item.b : ''} · 第 ${item.line} 行`}
          >
            <Button
              type="text"
              size="small"
              style={{ padding: '0 4px' }}
              aria-label={`约束 ${item.id}（第 ${item.line} 行）`}
              onClick={() => onReveal?.(item.line)}
            >
              <Tag
                color={item.status === 'warning' ? 'warning' : 'processing'}
                style={{ marginInlineEnd: 0 }}
              >
                {item.id} {TYPE_LABEL[item.type] ?? item.type}
                {item.status === 'warning' ? '（欠约束）' : ''}
              </Tag>
            </Button>
          </Tooltip>
        ))}
      </Space>
    </div>
  )
}
