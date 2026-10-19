/**
 * flowBoard 纯逻辑层测试 —— 流程视图节点平铺与有向流转边.
 *
 * 覆盖：节点归属 key 类型分派 / 空值归「未配置节点」/ 节点顺序解析
 * （显式 node_order、字段 options 回退、数据首次出现、未配置节点恒末尾）/
 * 流程图构建（节点分组、相邻有向边、边不跨「未配置节点」、边 count 取下游记录数）。
 */

import { describe, expect, it } from 'vitest'
import type { Field, RowResponse } from '@/api'
import { makeField } from '@/test/fixtures'
import {
  FLOW_UNGROUPED_LABEL,
  buildFlowGraph,
  flowNodeKey,
  resolveFlowNodeOrder,
} from './flowBoard'

const NODE_FIELD = '当前交付节点'
const STAGES = ['需求调研', '方案设计', '开发实施', '测试验收', '运维支持']

const FIELDS: Field[] = [
  makeField({ id: 1, name: '项目名称', field_type: 'text' }),
  makeField({ id: 2, name: NODE_FIELD, field_type: 'select', config: { options: STAGES } }),
]

/** 产品开发典型示例：5 个交付节点按流程顺序推进，末尾一条未配置节点 */
const ROWS: RowResponse[] = [
  { id: 1, 项目名称: '数字孪生可视化系统', [NODE_FIELD]: '需求调研' },
  { id: 2, 项目名称: '大数据分析决策系统', [NODE_FIELD]: '需求调研' },
  { id: 3, 项目名称: 'DevOps持续交付平台', [NODE_FIELD]: '开发实施' },
  { id: 4, 项目名称: '云原生微服务改造', [NODE_FIELD]: '方案设计' },
  { id: 5, 项目名称: '未分配节点项目', [NODE_FIELD]: null },
] as unknown as RowResponse[]

describe('flowNodeKey 节点归属', () => {
  it('select 取 options 标签', () => {
    expect(flowNodeKey({ id: 1, [NODE_FIELD]: '需求调研' } as unknown as RowResponse, FIELDS[1])).toBe('需求调研')
  })

  it('link 取首值标签', () => {
    const linkField = makeField({ id: 3, name: '关联项目', field_type: 'link' })
    expect(flowNodeKey({ id: 1, 关联项目: [{ label: '课题A' }] } as unknown as RowResponse, linkField)).toBe('课题A')
  })

  it('multi_select 取首值标签', () => {
    const multiField = makeField({ id: 4, name: '标签', field_type: 'multi_select', config: { options: ['紧急', '常规'] } })
    expect(flowNodeKey({ id: 1, 标签: ['紧急', '常规'] } as unknown as RowResponse, multiField)).toBe('紧急')
  })

  it('boolean 按 是/否 归属，空值返回空串', () => {
    const boolField = makeField({ id: 5, name: '是否', field_type: 'boolean' })
    expect(flowNodeKey({ id: 1, 是否: true } as unknown as RowResponse, boolField)).toBe('是')
    expect(flowNodeKey({ id: 2, 是否: false } as unknown as RowResponse, boolField)).toBe('否')
    expect(flowNodeKey({ id: 3, 是否: null } as unknown as RowResponse, boolField)).toBe('')
  })

  it('text 与未知类型 String 化；空值/字段缺失返回空串', () => {
    const textField = makeField({ id: 6, name: '负责人', field_type: 'text' })
    expect(flowNodeKey({ id: 1, 负责人: '陈立' } as unknown as RowResponse, textField)).toBe('陈立')
    expect(flowNodeKey({ id: 1, 负责人: null } as unknown as RowResponse, textField)).toBe('')
    expect(flowNodeKey({} as unknown as RowResponse, undefined)).toBe('')
  })
})

describe('resolveFlowNodeOrder 节点顺序', () => {
  it('优先采用显式 node_order', () => {
    const present = ['开发实施', '需求调研', '方案设计']
    expect(resolveFlowNodeOrder(present, FIELDS[1], STAGES)).toEqual(['需求调研', '方案设计', '开发实施'])
  })

  it('无 node_order 回退到字段 options 顺序', () => {
    const present = ['开发实施', '需求调研', '方案设计']
    expect(resolveFlowNodeOrder(present, FIELDS[1], undefined)).toEqual(['需求调研', '方案设计', '开发实施'])
  })

  it('既无 node_order 也无可选项时按数据首次出现顺序', () => {
    const textField = makeField({ id: 6, name: '阶段', field_type: 'text' })
    expect(resolveFlowNodeOrder(['B', 'A', 'C'], textField, undefined)).toEqual(['B', 'A', 'C'])
  })

  it('未在来源中出现的节点按首次出现顺序补齐，未配置节点恒排末尾', () => {
    const present = ['Z', '未配置节点', 'A']
    expect(resolveFlowNodeOrder(present, undefined, ['A'])).toEqual(['A', 'Z', FLOW_UNGROUPED_LABEL])
  })
})

describe('buildFlowGraph 流程图构建', () => {
  it('按流程顺序分组节点，未配置节点置末尾', () => {
    const graph = buildFlowGraph(ROWS, FIELDS, NODE_FIELD, STAGES)
    expect(graph.nodes.map((n) => n.key)).toEqual(['需求调研', '方案设计', '开发实施', FLOW_UNGROUPED_LABEL])
    expect(graph.nodes.find((n) => n.key === '需求调研')!.rows.map((r) => r.id)).toEqual([1, 2])
    expect(graph.nodes.find((n) => n.key === FLOW_UNGROUPED_LABEL)!.rows.map((r) => r.id)).toEqual([5])
  })

  it('流转边仅连接相邻的已配置节点，count 取下游记录数', () => {
    const graph = buildFlowGraph(ROWS, FIELDS, NODE_FIELD, STAGES)
    expect(graph.edges).toEqual([
      { from: '需求调研', to: '方案设计', count: 1 },
      { from: '方案设计', to: '开发实施', count: 1 },
    ])
  })

  it('无 node_order 时回退字段 options 后顺序一致', () => {
    const graph = buildFlowGraph(ROWS, FIELDS, NODE_FIELD)
    expect(graph.nodes.map((n) => n.key)).toEqual(['需求调研', '方案设计', '开发实施', FLOW_UNGROUPED_LABEL])
  })

  it('空行集合产出空图', () => {
    const graph = buildFlowGraph([], FIELDS, NODE_FIELD, STAGES)
    expect(graph.nodes).toEqual([])
    expect(graph.edges).toEqual([])
  })
})
