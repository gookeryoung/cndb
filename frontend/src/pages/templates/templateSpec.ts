/** 工作区模板前端工具：JSON 编辑、diff / 影响摘要（纯函数，便于单测）. */

import type { TemplateDiffChange, TemplateImpact, TemplateSpec } from '@/api'

export function formatSpecJson(spec: TemplateSpec | undefined | null): string {
  return JSON.stringify(spec ?? { forms: [], documents: [], stages: [] }, null, 2)
}

export function parseSpecJson(text: string): { spec?: TemplateSpec; error?: string } {
  let raw: unknown
  try {
    raw = JSON.parse(text)
  } catch (err) {
    return { error: `JSON 解析失败：${err instanceof Error ? err.message : String(err)}` }
  }
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) {
    return { error: '规格必须是 JSON 对象（含 forms / documents / stages）' }
  }
  const spec = raw as Partial<TemplateSpec>
  if (!Array.isArray(spec.forms) || !Array.isArray(spec.documents) || !Array.isArray(spec.stages)) {
    return { error: '规格缺少 forms / documents / stages 数组' }
  }
  return { spec: spec as TemplateSpec }
}

export const SEVERITY_LABEL: Record<TemplateDiffChange['severity'], string> = {
  breaking: '需确认',
  warn: '注意',
  info: '变更',
}

export const SEVERITY_COLOR: Record<TemplateDiffChange['severity'], string> = {
  breaking: 'red',
  warn: 'orange',
  info: 'blue',
}

export function impactSummaryLines(impact: TemplateImpact): string[] {
  const s = impact.summary
  const lines = [
    `使用中工作区 ${s.workspace_count} 个，其中 ${s.affected_workspaces} 个会受影响`,
    `新建数据表 ${s.tables_to_create} 张、新增字段 ${s.fields_to_add} 个、创建文档占位 ${s.documents_to_create} 份`,
  ]
  if (s.required_fields_needing_backfill > 0) {
    lines.push(`新增必填字段 ${s.required_fields_needing_backfill} 个，约 ${s.rows_missing_required} 条存量行需要补值（不阻塞保存）`)
  }
  if (s.stages_fallback > 0) lines.push(`${s.stages_fallback} 个工作区的当前阶段被删除，将回落到第一阶段`)
  if (s.fields_type_conflict > 0) lines.push(`${s.fields_type_conflict} 个字段类型变更需人工迁移（模板不会自动改列）`)
  if (s.orphan_forms + s.orphan_fields + s.orphan_documents > 0) {
    lines.push(`保留已移出模板的表 ${s.orphan_forms} 张 / 字段 ${s.orphan_fields} 个 / 文档 ${s.orphan_documents} 份`)
  }
  return lines
}

export function diffChangeLabel(change: TemplateDiffChange): string {
  return `${SEVERITY_LABEL[change.severity]} · ${change.message}`
}
