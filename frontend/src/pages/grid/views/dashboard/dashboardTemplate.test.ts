/** dashboard 模板纯函数测试（ADR 0023 P3：另存 / 字段认领 / 落地校验）.*/
import { describe, expect, it } from 'vitest'
import type { Field } from '@/api'
import { makeField } from '@/test/fixtures'
import { DashboardConfigError, normalizeDashboard, serializeDashboard } from './dashboardModel'
import {
  applyDashboardTemplate,
  applyTemplateMapping,
  buildDashboardTemplate,
  collectTemplateRefs,
  collectTemplateTableIds,
  matchingTargetFields,
  planTemplateFields,
} from './dashboardTemplate'

const SOURCE_FIELDS: Field[] = [
  makeField({ id: 1, name: '金额', field_type: 'number' }),
  makeField({ id: 2, name: '日期', field_type: 'date' }),
  makeField({ id: 3, name: '状态', field_type: 'select' }),
  makeField({ id: 9, name: '备注', field_type: 'text' }),
]

/** 覆盖 chart / kpi / table / 全局筛选 / 排序的配置 */
const CONFIG = {
  schema_version: 1,
  widgets: [
    {
      id: 'w_chart_1',
      type: 'chart',
      layout: { x: 0, y: 0, w: 6, h: 8 },
      query: {
        filters: [{ field_name: '状态', op: 'eq', value: '进行中' }],
        filter_logic: 'AND',
        sortings: [{ field_name: '日期', direction: 'desc' }],
      },
      chart: { type: 'bar', x: '状态', y: ['金额'], series: '日期', agg: 'sum', stack: 'none', sort: 'none', dual_axis: false, format: {} },
    },
    {
      id: 'w_kpi_1',
      type: 'kpi',
      layout: { x: 6, y: 0, w: 3, h: 4 },
      query: { filters: [], filter_logic: 'AND', sortings: [] },
      kpi: {
        value: { field: '金额', agg: 'sum' },
        compare: { mode: 'prev_period', date_field: '日期', granularity: 'month' },
        sparkline: { field: '金额', agg: 'sum', points: 12 },
      },
    },
    {
      id: 'w_table_1',
      type: 'table',
      layout: { x: 0, y: 8, w: 6, h: 6 },
      query: { filters: [], filter_logic: 'AND', sortings: [] },
      table: { columns: ['日期', '金额', '备注'], row_limit: 20 },
    },
  ],
  global_filters: [{ id: 'g_date', kind: 'date_range', field: '日期' }],
  settings: { refresh_interval: 0, theme: 'inherit' },
}

const CONFIG_WITH_TABLE_ID = {
  ...CONFIG,
  widgets: [
    { ...CONFIG.widgets[0], query: { ...CONFIG.widgets[0].query, table_id: 2 } },
    CONFIG.widgets[1],
    CONFIG.widgets[2],
  ],
}

describe('collectTemplateRefs', () => {
  it('按结构收集全部字段引用路径', () => {
    const refs = collectTemplateRefs(CONFIG as Record<string, unknown>)
    const byField = new Map(refs.map((ref) => [ref.path.join('.'), ref.field]))
    expect(byField.get('widgets.0.query.filters.0.field_name')).toBe('状态')
    expect(byField.get('widgets.0.query.sortings.0.field_name')).toBe('日期')
    expect(byField.get('widgets.0.chart.x')).toBe('状态')
    expect(byField.get('widgets.0.chart.y.0')).toBe('金额')
    expect(byField.get('widgets.0.chart.series')).toBe('日期')
    expect(byField.get('widgets.1.kpi.value.field')).toBe('金额')
    expect(byField.get('widgets.1.kpi.compare.date_field')).toBe('日期')
    expect(byField.get('widgets.1.kpi.sparkline.field')).toBe('金额')
    expect(byField.get('widgets.2.table.columns.2')).toBe('备注')
    expect(byField.get('global_filters.0.field')).toBe('日期')
  })

    it('损坏结构跳过且不抛错', () => {
    const refs = collectTemplateRefs({
      widgets: [{ type: 'chart', query: 'bad', chart: { x: 1, y: ['金额'] } }, 'garbage'],
      global_filters: 'bad',
    })
    expect(refs.map((ref) => ref.field)).toEqual(['金额'])
  })
})

describe('collectTemplateTableIds', () => {
  it('去重收集跨表 widget 的目标表 id，忽略缺省与非法值', () => {
    expect(collectTemplateTableIds(CONFIG_WITH_TABLE_ID as Record<string, unknown>)).toEqual(['2'])
    expect(collectTemplateTableIds({
      widgets: [
        { query: { table_id: 3 } },
        { query: { table_id: 3 } },
        { query: { filters: [] } },
        { query: { table_id: 0 } },
        { query: 'bad' },
        'garbage',
      ],
    })).toEqual(['3'])
  })
})

describe('buildDashboardTemplate', () => {
  it('只快照被引用字段的类型，并剥离来源表', () => {
    const built = buildDashboardTemplate(
      CONFIG_WITH_TABLE_ID as unknown as Parameters<typeof buildDashboardTemplate>[0],
      SOURCE_FIELDS,
    )
    expect(built.fields).toEqual({ 金额: 'number', 日期: 'date', 状态: 'select', 备注: 'text' })
    const widgets = built.config.widgets as Array<Record<string, unknown>>
    expect((widgets[0].query as Record<string, unknown>).table_id).toBeUndefined()
    // 未引用的字段不进快照
    expect(built.fields).not.toHaveProperty('未使用')
  })

  it('跨表 widget 引用字段按目标表补录快照，同名冲突时基表优先', () => {
    const crossConfig = {
      widgets: [
        {
          id: 'w_kpi_cross',
          type: 'kpi',
          layout: { x: 0, y: 0, w: 3, h: 4 },
          query: { table_id: 7, filters: [], filter_logic: 'AND', sortings: [] },
          kpi: { value: { field: '薪资', agg: 'sum' } },
        },
        {
          id: 'w_kpi_base',
          type: 'kpi',
          layout: { x: 3, y: 0, w: 3, h: 4 },
          query: { filters: [], filter_logic: 'AND', sortings: [] },
          kpi: { value: { field: '金额', agg: 'sum' } },
        },
      ],
    }
    const extraFields: Field[] = [
      makeField({ id: 71, name: '薪资', field_type: 'number' }),
      makeField({ id: 72, name: '金额', field_type: 'text' }),
      makeField({ id: 73, name: '未引用', field_type: 'text' }),
    ]
    const built = buildDashboardTemplate(
      crossConfig as unknown as Parameters<typeof buildDashboardTemplate>[0],
      SOURCE_FIELDS,
      { '7': extraFields },
    )
    expect(built.fields).toEqual({ 金额: 'number', 薪资: 'number' })
    const widgets = built.config.widgets as Array<Record<string, unknown>>
    expect((widgets[0].query as Record<string, unknown>).table_id).toBeUndefined()
    expect(built.fields).not.toHaveProperty('未引用')
  })

  it('未提供目标表字段时只快照基表字段（跨表字段缺失由落地映射兜底）', () => {
    const built = buildDashboardTemplate(
      CONFIG_WITH_TABLE_ID as unknown as Parameters<typeof buildDashboardTemplate>[0],
      SOURCE_FIELDS,
    )
    expect(built.fields).not.toHaveProperty('薪资')
  })

  it('输出可被模板落地重新归一（结构无损）', () => {
    const built = buildDashboardTemplate(
      normalizeDashboard(CONFIG, SOURCE_FIELDS),
      SOURCE_FIELDS,
    )
    const { mapping } = planTemplateFields(built.fields, SOURCE_FIELDS)
    const restored = applyDashboardTemplate(built.config, mapping, SOURCE_FIELDS)
    expect(serializeDashboard(restored)).toEqual(serializeDashboard(normalizeDashboard(CONFIG, SOURCE_FIELDS)))
  })
})

describe('planTemplateFields', () => {
  it('同名同类型自动认领，缺失 / 类型不符进待办', () => {
    const targetFields: Field[] = [
      makeField({ id: 11, name: '金额', field_type: 'number' }),
      makeField({ id: 12, name: '日期', field_type: 'datetime' }),
      makeField({ id: 13, name: '备注', field_type: 'text' }),
    ]
    const plan = planTemplateFields({ 金额: 'number', 日期: 'date', 状态: 'select' }, targetFields)
    expect(plan.mapping).toEqual({ 金额: '金额' })
    expect(plan.issues).toEqual([
      { field: '日期', type: 'date' },
      { field: '状态', type: 'select' },
    ])
  })

  it('类型别名视为同类型（decimal ~ float）', () => {
    const plan = planTemplateFields(
      { 金额: 'decimal' },
      [makeField({ id: 21, name: '金额', field_type: 'float' })],
    )
    expect(plan.mapping).toEqual({ 金额: '金额' })
    expect(plan.issues).toEqual([])
  })

  it('旧模板无类型快照时按名称认领', () => {
    const plan = planTemplateFields(
      { 金额: '' },
      [makeField({ id: 31, name: '金额', field_type: 'text' })],
    )
    expect(plan.mapping).toEqual({ 金额: '金额' })
  })
})

describe('matchingTargetFields', () => {
  it('优先同类型，同类型为空时退回全部', () => {
    const fields: Field[] = [
      makeField({ id: 41, name: 'A', field_type: 'number' }),
      makeField({ id: 42, name: 'B', field_type: 'text' }),
    ]
    expect(matchingTargetFields(fields, 'number').map((f) => f.name)).toEqual(['A'])
    expect(matchingTargetFields(fields, 'select').map((f) => f.name)).toEqual(['A', 'B'])
    expect(matchingTargetFields(fields, '').map((f) => f.name)).toEqual(['A', 'B'])
  })
})

describe('applyTemplateMapping', () => {
  it('按映射重写全部引用位置且不修改入参', () => {
    const mapping = { 金额: '实收金额', 日期: '创建日期', 状态: '阶段', 备注: '说明' }
    const rewritten = applyTemplateMapping(CONFIG as Record<string, unknown>, mapping)
    const fields = collectTemplateRefs(rewritten).map((ref) => ref.field)
    expect(fields).toEqual(['阶段', '创建日期', '阶段', '实收金额', '创建日期', '实收金额', '创建日期', '实收金额', '创建日期', '实收金额', '说明', '创建日期'])
    expect(collectTemplateRefs(CONFIG as Record<string, unknown>).map((ref) => ref.field)).toContain('金额')
  })

    it('未提供的映射保持原字段名', () => {
    const rewritten = applyTemplateMapping(CONFIG as Record<string, unknown>, { 金额: '实收金额' })
    const fields = collectTemplateRefs(rewritten).map((ref) => ref.field)
    expect(fields).toContain('状态')
    expect(fields).toContain('实收金额')
  })
})

describe('applyDashboardTemplate', () => {
  it('映射完整时返回可用的归一配置', () => {
    const target: Field[] = [
      makeField({ id: 51, name: '实收金额', field_type: 'number' }),
      makeField({ id: 52, name: '创建日期', field_type: 'date' }),
      makeField({ id: 53, name: '阶段', field_type: 'select' }),
      makeField({ id: 54, name: '说明', field_type: 'text' }),
    ]
    const mapping = { 金额: '实收金额', 日期: '创建日期', 状态: '阶段', 备注: '说明' }
    const config = applyDashboardTemplate(CONFIG as Record<string, unknown>, mapping, target)
    expect(config.widgets[0].query.filters[0].field_name).toBe('阶段')
    expect(config.global_filters[0].field).toBe('创建日期')
  })

  it('存在未认领字段时报 DashboardConfigError（模板不是校验后门）', () => {
    const target: Field[] = [
      makeField({ id: 61, name: '实收金额', field_type: 'number' }),
      makeField({ id: 62, name: '创建日期', field_type: 'date' }),
      makeField({ id: 63, name: '阶段', field_type: 'select' }),
      makeField({ id: 64, name: '说明', field_type: 'text' }),
    ]
    expect(() =>
      applyDashboardTemplate(CONFIG as Record<string, unknown>, { 金额: '实收金额' }, target),
    ).toThrow(DashboardConfigError)
    try {
      applyDashboardTemplate(CONFIG as Record<string, unknown>, {}, target)
    } catch (error) {
      expect((error as DashboardConfigError).message).toContain('模板落地失败')
      expect((error as DashboardConfigError).path).toBe('widgets[0].query.filters[0].field_name')
      return
    }
    throw new Error('应当抛出 DashboardConfigError')
  })
})
