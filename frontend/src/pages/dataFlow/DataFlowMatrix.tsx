/** 数据流程矩阵视图（需求 0098）.
 *
 * 横向列 = 一级过程（flows），纵向行 = 二级子过程（steps）。
 * 默认只渲染一级过程；点击流程头展开该列的子过程，可同时展开多列做横向对齐比较。
 * 纯展示组件：选中 / 展开状态由页面持有；具体内容列表在页面下方独立区域渲染，
 * 与矩阵不共用容器，避免浮层 / 绝对定位导致的重叠。
 */

import { Button, Space, Typography } from 'antd'
import { AuditOutlined, DownOutlined, RightOutlined, TableOutlined } from '@ant-design/icons'
import type { DataFlowFlow } from '@/api'

const { Text } = Typography

/** 列配色数量：与 index.css 的 .cn-flow-matrix-col[data-tone] 一一对应 */
const TONE_COUNT = 5

export interface DataFlowMatrixProps {
  flows: DataFlowFlow[]
  /** 当前查看的一级过程 */
  activeFlowKey: string | null
  /** 当前查看的二级子过程 */
  activeStepKey: string | null
  /** 已展开的一级过程 key */
  expandedKeys: string[]
  /** 点击流程头：展开 / 收起该列 */
  onToggleFlow: (flowKey: string) => void
  /** 点击子过程：切换下方内容 */
  onSelectStep: (flowKey: string, stepKey: string) => void
  onExpandAll: () => void
  onCollapseAll: () => void
}

export default function DataFlowMatrix({
  flows,
  activeFlowKey,
  activeStepKey,
  expandedKeys,
  onToggleFlow,
  onSelectStep,
  onExpandAll,
  onCollapseAll,
}: DataFlowMatrixProps) {
  const expanded = new Set(expandedKeys)
  const rowCount = flows.reduce(
    (max, flow) => (expanded.has(flow.key) ? Math.max(max, flow.steps.length) : max),
    0,
  )
  const rows = Array.from({ length: rowCount }, (_, index) => index)
  // 轨道与列使用同一套行高 / 行距，展开后子过程横向对齐
  const railRows = rowCount > 0
    ? `var(--cn-flow-matrix-head-h) repeat(${rowCount}, var(--cn-flow-matrix-step-h))`
    : 'var(--cn-flow-matrix-head-h)'

  return (
    <section className="cn-flow-matrix" data-testid="data-flow-matrix" aria-label="数据流程矩阵">
      <div className="cn-flow-matrix-toolbar">
        <Space size={8} wrap>
          <Text strong>一级过程 × 二级子过程</Text>
          <Text type="secondary">
            {flows.length} 条一级过程 · 点击流程展开子过程，内容在下方独立区域查看
          </Text>
        </Space>
        <Space size={4}>
          <Button size="small" onClick={onExpandAll} data-testid="data-flow-expand-all">展开全部</Button>
          <Button size="small" onClick={onCollapseAll} data-testid="data-flow-collapse-all">收起全部</Button>
        </Space>
      </div>

      <div className="cn-flow-matrix-scroll">
        {rowCount > 1 && (
          <div className="cn-flow-matrix-rail" style={{ gridTemplateRows: railRows }} aria-hidden>
            <div className="cn-flow-matrix-rail-head">子过程</div>
            {rows.map(row => (
              <div className="cn-flow-matrix-rail-cell" key={row}>{row + 1}</div>
            ))}
          </div>
        )}

        <div className="cn-flow-matrix-columns">
          {flows.map((flow, flowIndex) => {
            const open = expanded.has(flow.key)
            const isActiveFlow = flow.key === activeFlowKey
            return (
              <div
                className={`cn-flow-matrix-col${open ? ' is-open' : ''}`}
                data-tone={flowIndex % TONE_COUNT}
                key={flow.key}
              >
                {flowIndex < flows.length - 1 && <span className="cn-flow-matrix-arrow" aria-hidden />}
                <button
                  type="button"
                  className={`cn-flow-matrix-head${isActiveFlow ? ' is-active' : ''}`}
                  data-testid={`data-flow-card-${flow.key}`}
                  aria-expanded={open}
                  aria-controls={`data-flow-steps-${flow.key}`}
                  onClick={() => onToggleFlow(flow.key)}
                >
                  <span className="cn-flow-matrix-head-title">
                    <span className="cn-flow-matrix-index" aria-hidden>{flowIndex + 1}</span>
                    <span className="cn-flow-matrix-name" title={flow.name}>{flow.name}</span>
                    <span className="cn-flow-matrix-chevron" aria-hidden>
                      {open ? <DownOutlined /> : <RightOutlined />}
                    </span>
                  </span>
                  <span className="cn-flow-matrix-desc" title={flow.description || ''}>
                    {flow.description || '—'}
                  </span>
                  <span className="cn-flow-matrix-stats">
                    {flow.step_count} 步子过程 · {flow.form_count} 个表单 · {flow.record_count} 条记录
                  </span>
                </button>

                {open && (
                  <div
                    className="cn-flow-matrix-steps"
                    id={`data-flow-steps-${flow.key}`}
                    data-testid={`data-flow-steps-${flow.key}`}
                    style={{ gridTemplateRows: `repeat(${rowCount}, var(--cn-flow-matrix-step-h))` }}
                  >
                    {rows.map(row => {
                      const step = flow.steps[row]
                      if (!step) return <div className="cn-flow-matrix-gap" key={`gap-${row}`} aria-hidden />
                      const isActiveStep = step.key === activeStepKey
                      const isLast = row === flow.steps.length - 1
                      return (
                        <button
                          type="button"
                          key={step.key}
                          className={`cn-flow-matrix-step${isActiveStep ? ' is-active' : ''}${isLast ? ' is-last' : ''}${step.form ? '' : ' is-approval'}`}
                          data-testid={`data-flow-step-${step.key}`}
                          aria-current={isActiveStep ? 'step' : undefined}
                          aria-label={`${flow.name} 子过程 ${row + 1}：${step.name}${step.form ? '（数据表单）' : '（审批 / 确认节点）'}`}
                          onClick={() => onSelectStep(flow.key, step.key)}
                        >
                          <span className="cn-flow-matrix-step-no" aria-hidden>{flowIndex + 1}.{row + 1}</span>
                          <span className="cn-flow-matrix-step-name" title={step.name}>{step.name}</span>
                          <span className="cn-flow-matrix-step-badge" aria-hidden>
                            {step.form ? <TableOutlined /> : <AuditOutlined />}
                          </span>
                        </button>
                      )
                    })}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      </div>
    </section>
  )
}
