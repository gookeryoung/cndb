/** dashboard 契约模型单元测试 —— 由前后端共享的 schema_cases.json 驱动（ADR 0023 I1）. */
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import type { Field } from '@/api'
import { makeField } from '@/test/fixtures'
import {
  DashboardConfigError,
  DASHBOARD_SCHEMA_VERSION,
  defaultDashboardConfig,
  normalizeDashboard,
  serializeDashboard,
} from './dashboardModel'

interface CaseFile {
  fields: Record<string, string>
  valid: Array<{ name: string; config: Record<string, unknown> }>
  invalid: Array<{ name: string; config: Record<string, unknown>; path: string }>
}

const fixture = JSON.parse(
  readFileSync(resolve(process.cwd(), '../tests/fixtures/dashboard/schema_cases.json'), 'utf8'),
) as CaseFile

const FIELDS: Field[] = Object.entries(fixture.fields).map(([name, field_type], i) =>
  makeField({ id: i + 1, name, field_type: field_type as Field['field_type'] }),
)

describe('normalizeDashboard — 合法用例', () => {
  it('共享用例至少 10 条', () => {
    expect(fixture.valid.length).toBeGreaterThanOrEqual(10)
  })

  it.each(fixture.valid)('$name 解析成功且二次归一幂等', ({ config }) => {
    const first = normalizeDashboard(config, FIELDS)
    const serialized = serializeDashboard(first)
    const second = normalizeDashboard(serialized, FIELDS)
    expect(serializeDashboard(second)).toEqual(serialized)
  })
})

describe('normalizeDashboard — 非法用例', () => {
  it('共享用例至少 10 条', () => {
    expect(fixture.invalid.length).toBeGreaterThanOrEqual(10)
  })

  it.each(fixture.invalid)('$name 定位到 $path', ({ config, path }) => {
    let caught: unknown
    try {
      normalizeDashboard(config, FIELDS)
    } catch (e) {
      caught = e
    }
    expect(caught).toBeInstanceOf(DashboardConfigError)
    expect((caught as DashboardConfigError).path).toBe(path)
  })
})

describe('默认值与裁剪', () => {
  it('空配置补全 schema/画布/设置默认值', () => {
    const cfg = normalizeDashboard({}, FIELDS)
    expect(cfg.schema_version).toBe(DASHBOARD_SCHEMA_VERSION)
    expect(cfg.canvas).toEqual({ cols: 12, row_height: 40, gap: 12, padding: 16 })
    expect(cfg.widgets).toEqual([])
    expect(cfg.global_filters).toEqual([])
    expect(cfg.settings).toEqual({ refresh_interval: 0, theme: 'inherit' })
  })

  it('defaultDashboardConfig 与空配置一致', () => {
    expect(serializeDashboard(defaultDashboardConfig())).toEqual(serializeDashboard(normalizeDashboard({}, FIELDS)))
  })

  it('未知键被裁剪，不进入序列化结果', () => {
    const cfg = normalizeDashboard({
      unknown_root: 'x',
      widgets: [{
        id: 'trim',
        type: 'text',
        unknown_widget: 'x',
        layout: { x: 0, y: 0, w: 12, h: 3 },
        text: { content: '说明', unknown_text: 'x' },
      }],
    }, FIELDS)
    const out = serializeDashboard(cfg)
    expect(out).not.toHaveProperty('unknown_root')
    const widgets = out.widgets as Array<Record<string, unknown>>
    expect(widgets[0]).not.toHaveProperty('unknown_widget')
    expect(widgets[0].text).toEqual({ content: '说明' })
  })

  it('charts[] 不被误读为 dashboard widget 列表', () => {
    const cfg = normalizeDashboard({ charts: [{ chart_type: 'bar' }], row_height: 32 }, FIELDS)
    expect(cfg.widgets).toEqual([])
    expect(cfg.canvas.row_height).toBe(32)
  })

  it('扁平画布键与嵌套 canvas 同时存在时以 canvas 为准', () => {
    const cfg = normalizeDashboard({ row_height: 32, canvas: { row_height: 48, gap: 8 } }, FIELDS)
    expect(cfg.canvas.row_height).toBe(48)
    expect(cfg.canvas.gap).toBe(8)
  })
})
