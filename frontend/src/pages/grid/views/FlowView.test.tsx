/**
 * FlowView 组件测试 —— 流程（Flow）视图.
 *
 * 覆盖：未配置节点字段空态 / 空数据空态 / 节点按流程顺序平铺（节点头 + 计数徽章）/
 * 未配置节点置末尾 / 节点间有向连接线（箭头 + 流入量）/ 节点卡片归属与点击回调。
 */

import { describe, expect, it, vi } from 'vitest'
import { fireEvent, screen } from '@testing-library/react'
import FlowView from './FlowView'
import { renderProviders } from '@/test/render-providers'
import { makeField } from '@/test/fixtures'
import type { Field, RowResponse, View } from '@/api'

const NODE_FIELD = '当前交付节点'
const STAGES = ['需求调研', '方案设计', '开发实施', '测试验收', '运维支持']

const FIELDS: Field[] = [
  makeField({ id: 1, name: '项目名称', field_type: 'text' }),
  makeField({ id: 2, name: NODE_FIELD, field_type: 'select', config: { options: STAGES } }),
]

const ROWS: RowResponse[] = [
  { id: 1, 项目名称: '数字孪生可视化系统', [NODE_FIELD]: '需求调研' },
  { id: 2, 项目名称: '大数据分析决策系统', [NODE_FIELD]: '需求调研' },
  { id: 3, 项目名称: 'DevOps持续交付平台', [NODE_FIELD]: '开发实施' },
  { id: 4, 项目名称: '云原生微服务改造', [NODE_FIELD]: '方案设计' },
  { id: 5, 项目名称: '未分配节点项目', [NODE_FIELD]: null },
] as unknown as RowResponse[]

const DEFAULT_VIEW = {
  id: 1, name: '交付流程', view_type: 'flow', is_default: false,
  view_options: { node_field: NODE_FIELD, title_field: '项目名称', node_order: STAGES },
} as unknown as View

function renderFlow(props?: {
  rows?: RowResponse[]
  view?: View | null
  onRowClick?: (r: RowResponse) => void
}) {
  return renderProviders(
    <FlowView
      rows={props?.rows ?? ROWS}
      fields={FIELDS}
      view={props?.view !== undefined ? props.view : DEFAULT_VIEW}
      density="comfortable"
      onRowClick={props?.onRowClick}
    />,
  )
}

describe('FlowView 流程视图', () => {
  it('未配置流程节点字段显示引导空态', () => {
    renderFlow({
      view: { id: 1, name: '流程', view_type: 'flow', is_default: false, view_options: {} } as unknown as View,
    })

    expect(screen.getByText(/流程视图需配置流程节点字段/)).toBeInTheDocument()
  })

  it('空数据显示引导空态', () => {
    renderFlow({ rows: [] })

    expect(screen.getByText(/这张表还没有数据/)).toBeInTheDocument()
  })

  it('按流程顺序平铺节点，「未配置节点」置末尾', () => {
    renderFlow()

    const nodeHeaders = screen.getAllByTestId('flow-node-header').map((h) => h.textContent)
    expect(nodeHeaders).toHaveLength(4)
    expect(nodeHeaders[0]).toContain('需求调研')
    expect(nodeHeaders[1]).toContain('方案设计')
    expect(nodeHeaders[2]).toContain('开发实施')
    expect(nodeHeaders[3]).toContain('未配置节点')
  })

  it('节点头展示各节点记录数徽章与总记录数', () => {
    renderFlow()

    const headers = screen.getAllByTestId('flow-node-header').map((h) => h.textContent)
    expect(headers[0]).toContain('2') // 需求调研 2 条
    expect(headers[1]).toContain('1') // 方案设计 1 条
    expect(screen.getByText(/4 个节点 · 5 条记录/)).toBeInTheDocument()
  })

  it('节点卡片归属正确并展示标题字段', () => {
    renderFlow()

    const cards = screen.getAllByTestId('flow-card')
    expect(cards).toHaveLength(5)
    expect(screen.getByText('数字孪生可视化系统')).toBeInTheDocument()
    expect(screen.getByText('DevOps持续交付平台')).toBeInTheDocument()
    expect(screen.getByText('未分配节点项目')).toBeInTheDocument()
  })

  it('相邻节点间的连接线带流入量，「未配置节点」方向无流入量', () => {
    renderFlow()

    expect(screen.getAllByTestId('flow-connector')).toHaveLength(3)
    // 需求调研→方案设计、方案设计→开发实施 各 1 条流入；开发实施→未配置节点 无流入量
    expect(screen.getAllByText('1 条流入')).toHaveLength(2)
  })

  it('点击节点卡片触发行详情回调', () => {
    const onRowClick = vi.fn()
    renderFlow({ onRowClick })

    fireEvent.click(screen.getByText('数字孪生可视化系统'))

    expect(onRowClick).toHaveBeenCalledTimes(1)
    expect(onRowClick.mock.calls[0][0].id).toBe(1)
  })
})
