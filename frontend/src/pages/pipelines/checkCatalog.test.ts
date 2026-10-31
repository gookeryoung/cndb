/** checkCatalog 工具函数单测 —— 触发摘要 / 状态判断 / DSL 片段生成. */

import { describe, expect, it } from 'vitest'
import {
  PIPELINE_STATUS_META, buildStepSnippet, defaultWorkflowContent, describeTriggers, isActiveRun,
} from './checkCatalog'
import type { PipelineCheckSpec } from '@/api'

const SPEC: PipelineCheckSpec = {
  uses: 'table/null-rate',
  title: '空值比例',
  category: 'table',
  severity: 'warn',
  target_types: ['table'],
  inputs: [
    { name: 'table', type: 'string', description: '', required: true, default: null },
    { name: 'fields', type: 'array', description: '', required: true, default: null },
    { name: 'max_rate', type: 'number', description: '', required: false, default: 0.2 },
    { name: 'note', type: 'string', description: '', required: false, default: undefined },
  ],
}

describe('checkCatalog', () => {
  it('describeTriggers 覆盖手动 / 事件 / 定时', () => {
    expect(describeTriggers(undefined)).toBe('手动')
    expect(describeTriggers({ manual: false })).toBe('未配置触发')
    expect(describeTriggers({ manual: false, events: ['record.updated'] })).toBe('事件 record.updated')
    expect(describeTriggers({ manual: true, events: ['a', 'b'], schedule: '0 6 * * *' }))
      .toBe('手动 · 事件 a / b · 定时 0 6 * * *')
  })

  it('buildStepSnippet 只生成必填与有默认值的输入', () => {
    const snippet = buildStepSnippet(SPEC)
    expect(snippet).toContain('      - uses: table/null-rate')
    expect(snippet).toContain('          table: 表名')
    expect(snippet).toContain('          fields: [值]')
    expect(snippet).toContain('          max_rate: 0.2')
    expect(snippet).not.toContain('note')
  })

  it('buildStepSnippet 无输入时只输出 uses 行', () => {
    expect(buildStepSnippet({ ...SPEC, inputs: [] })).toBe('      - uses: table/null-rate')
  })

  it('默认模板可被前端直接填入抽屉', () => {
    expect(defaultWorkflowContent()).toContain('name: 数据质量巡检')
    expect(defaultWorkflowContent()).toContain('uses: table/null-rate')
  })

  it('isActiveRun 仅在排队 / 运行中为真', () => {
    expect(isActiveRun('pending')).toBe(true)
    expect(isActiveRun('running')).toBe(true)
    expect(isActiveRun('success')).toBe(false)
    expect(isActiveRun('partial')).toBe(false)
    expect(isActiveRun('failed')).toBe(false)
    expect(isActiveRun('canceled')).toBe(false)
  })

  it('状态文案覆盖全部运行状态', () => {
    expect(PIPELINE_STATUS_META.success.label).toBe('通过')
    expect(PIPELINE_STATUS_META.failed.label).toBe('未通过')
    expect(Object.keys(PIPELINE_STATUS_META)).toHaveLength(6)
  })
})
