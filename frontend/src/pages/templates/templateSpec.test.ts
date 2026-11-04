import { describe, expect, it } from 'vitest'
import {
  SEVERITY_LABEL, diffChangeLabel, formatSpecJson, impactSummaryLines, parseSpecJson,
} from './templateSpec'
import type { TemplateImpact } from '@/api'

const SPEC = {
  forms: [{ key: 'a', name: 'A', fields: [{ name: 'x', type: 'text' }] }],
  documents: [],
  stages: [{ key: 's', name: 'S', forms: ['a'], documents: [] }],
}

describe('templateSpec', () => {
  it('format / parse roundtrip', () => {
    const text = formatSpecJson(SPEC)
    expect(text).toContain('"forms"')
    const parsed = parseSpecJson(text)
    expect(parsed.error).toBeUndefined()
    expect(parsed.spec?.forms[0].key).toBe('a')
  })

  it('rejects invalid json and missing sections', () => {
    expect(parseSpecJson('{oops').error).toMatch('JSON 解析失败')
    expect(parseSpecJson('[]').error).toMatch('JSON 对象')
    expect(parseSpecJson('{"forms":[]}').error).toMatch('forms / documents / stages')
  })

  it('summarizes impact and diff severity', () => {
    const impact = {
      summary: {
        workspace_count: 3, affected_workspaces: 2, tables_to_create: 1, fields_to_add: 2,
        required_fields_needing_backfill: 1, documents_to_create: 2, rows_missing_required: 5,
        stages_fallback: 1, fields_type_conflict: 0, orphan_forms: 1, orphan_fields: 0, orphan_documents: 1,
      },
    } as TemplateImpact
    const lines = impactSummaryLines(impact)
    expect(lines[0]).toContain('3 个')
    expect(lines.join('\n')).toContain('5 条存量行')
    expect(lines.join('\n')).toContain('回落到第一阶段')
    expect(lines.join('\n')).toContain('保留已移出模板')
    expect(SEVERITY_LABEL.breaking).toBe('需确认')
    expect(diffChangeLabel({ kind: 'field_added', target: 'a.x', message: '新增字段', severity: 'info', detail: {} }))
      .toBe('变更 · 新增字段')
  })
})
