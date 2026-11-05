/** 设计参数｜约束常驻面板（ADR 0103 C5 / D2）.
 *
 * 预览栏底部可折叠 Tabs：参数（改值即时重编译，前端零求值）+ 约束（IR 求解结果只读）。
 * 替代原右侧参数抽屉与预览底部约束横条；展开上限 280px 内部滚动，折叠态只留 36px 细条。
 * 覆盖数 / 约束数进 Tab 徽标，改参 / 重置沿用既有口径（ADR 0079 D3 / 0086 §7）。
 */

import { Button, Empty, InputNumber, Tabs, Tag, Tooltip, Typography } from 'antd'
import {
  DownOutlined, RollbackOutlined, SlidersOutlined, UpOutlined,
} from '@ant-design/icons'
import type { InputNumberProps } from 'antd'
import type { DesignIRConstraint, DesignIRParam } from '@/api'
import DesignConstraintsPanel from './DesignConstraintsPanel'

const { Text } = Typography

interface Props {
  params: DesignIRParam[]
  constraints: DesignIRConstraint[]
  /** 参数覆盖（param 名 → 实时值） */
  overrides: Record<string, number>
  /** 折叠态（本地偏好，I5） */
  collapsed: boolean
  onToggleCollapsed: () => void
  onParamChange: (name: string, value: InputNumberProps['value']) => void
  onReset: () => void
  /** 约束点击 → 定位源行 */
  onReveal: (line: number) => void
}

export default function DesignParamsPanel({
  params, constraints, overrides, collapsed, onToggleCollapsed, onParamChange, onReset, onReveal,
}: Props) {
  const overrideCount = Object.keys(overrides).length

  if (collapsed) {
    return (
      <div className="cn-dsl-params cn-dsl-params--collapsed" data-testid="design-params-panel">
        <Button
          type="text"
          size="small"
          icon={<UpOutlined />}
          aria-label="展开参数面板"
          data-testid="design-params-expand"
          onClick={onToggleCollapsed}
        >
          参数 {params.length} · 约束 {constraints.length}
        </Button>
        {overrideCount > 0 && (
          <Tag color="processing" className="cn-dsl-btn-tag">{overrideCount} 覆盖</Tag>
        )}
      </div>
    )
  }

  const paramsTab = params.length === 0 ? (
    <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="当前设计没有参数" />
  ) : (
    <div className="cn-dsl-param-list">
      {params.map(param => {
        const overridden = overrides[param.name] != null
        return (
          <div key={param.name} className="cn-dsl-param-row">
            <div className="cn-dsl-param-name">
              <Text code>{param.name}</Text>
              <Text type="secondary" className="cn-dsl-param-default">默认 {param.value}</Text>
              {overridden && <Tag color="processing" className="cn-dsl-status-tag">已覆盖</Tag>}
            </div>
            <InputNumber
              size="small"
              value={overrides[param.name] ?? param.value}
              step={1}
              aria-label={`参数 ${param.name}`}
              onChange={value => onParamChange(param.name, value)}
            />
          </div>
        )
      })}
    </div>
  )

  const constraintsTab = constraints.length === 0 ? (
    <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="当前设计没有装配约束" />
  ) : (
    <DesignConstraintsPanel constraints={constraints} onReveal={onReveal} />
  )

  return (
    <div className="cn-dsl-params" data-testid="design-params-panel">
      <Tabs
        size="small"
        className="cn-dsl-params-tabs"
        defaultActiveKey="params"
        items={[
          {
            key: 'params',
            label: (
              <span data-testid="design-params-tab">
                <SlidersOutlined /> 参数（{params.length}）
              </span>
            ),
            children: paramsTab,
          },
          {
            key: 'constraints',
            label: <span data-testid="design-constraints-tab">约束（{constraints.length}）</span>,
            children: constraintsTab,
          },
        ]}
        tabBarExtraContent={(
          <span className="cn-dsl-params-actions">
            {overrideCount > 0 && (
              <Tooltip title="清除全部参数覆盖">
                <Button size="small" icon={<RollbackOutlined />} onClick={onReset}>重置</Button>
              </Tooltip>
            )}
            <Button
              size="small"
              type="text"
              icon={<DownOutlined />}
              aria-label="折叠参数面板"
              data-testid="design-params-collapse"
              onClick={onToggleCollapsed}
            />
          </span>
        )}
      />
    </div>
  )
}
