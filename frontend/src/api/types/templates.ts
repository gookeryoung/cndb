/** 工作区模板与生命周期（需求 0094）类型. */

import type { ID, WorkspaceModule } from './common'

export interface TemplateSpecField {
  name: string
  type: string
  required?: boolean
  is_unique?: boolean
  config?: Record<string, unknown>
  hidden?: boolean
  default_value?: unknown
}

export interface TemplateSpecForm {
  key: string
  name: string
  description?: string
  fields: TemplateSpecField[]
}

export interface TemplateSpecDocument {
  key: string
  title: string
  required?: boolean
  naming?: string
  content?: string
}

export interface TemplateSpecStage {
  key: string
  name: string
  description?: string
  order?: number
  forms: string[]
  documents: string[]
}

export interface TemplateSpec {
  forms: TemplateSpecForm[]
  documents: TemplateSpecDocument[]
  stages: TemplateSpecStage[]
}

export interface WorkspaceTemplate {
  id: ID
  name: string
  description: string
  category: string
  modules: WorkspaceModule[]
  spec: TemplateSpec
  version: number
  is_builtin: boolean
  created_by_id: ID | null
  updated_at: string
  counts: { stage_count: number; form_count: number; field_count: number; document_rule_count: number }
  workspace_count: number
}

export interface TemplateRevision {
  version: number
  change_summary: string
  spec: TemplateSpec
  created_at: string
}

export interface TemplateDiffChange {
  kind: string
  target: string
  message: string
  severity: 'info' | 'warn' | 'breaking'
  detail: Record<string, unknown>
}

export interface TemplateDiff {
  forms: { added: Array<{ key: string; name: string }>; removed: Array<{ key: string; name: string }>; modified: Array<{ key: string; name: string; changes: string[] }> }
  documents: { added: Array<{ key: string; name: string }>; removed: Array<{ key: string; name: string }>; modified: Array<{ key: string; name: string; changes: string[] }> }
  stages: { added: Array<{ key: string; name: string }>; removed: Array<{ key: string; name: string }>; modified: Array<{ key: string; name: string; changes: string[] }> }
  changes: TemplateDiffChange[]
  counts: { added: number; removed: number; modified: number; total: number }
  requires_force: boolean
}

export interface TemplateImpactWorkspace {
  workspace_id: ID
  workspace_name: string
  template_version: number | null
  current_stage: string | null
  requires_force: boolean
  changes: Array<{ kind: string; severity: string; message: string }>
}

export interface TemplateImpact {
  template_id: ID
  template_version: number
  summary: {
    workspace_count: number
    affected_workspaces: number
    tables_to_create: number
    fields_to_add: number
    required_fields_needing_backfill: number
    documents_to_create: number
    rows_missing_required: number
    stages_fallback: number
    fields_type_conflict: number
    orphan_forms: number
    orphan_fields: number
    orphan_documents: number
  }
  workspaces: TemplateImpactWorkspace[]
  truncated: boolean
  requires_force: boolean
}

export interface TemplatePreview {
  diff: TemplateDiff
  impact: TemplateImpact
  requires_force: boolean
  spec: TemplateSpec
}

export interface TemplateUpdateResult {
  template: WorkspaceTemplate
  diff: TemplateDiff
  impact: TemplateImpact
  requires_force: boolean
  applied: boolean
  sync: { created_tables: number; added_fields: number; created_documents: number }
}

export interface LifecycleCheckForm {
  key: string
  name: string
  required: boolean
  table_exists: boolean
  row_count: number
  satisfied: boolean
}

export interface LifecycleCheckDocument {
  key: string
  title: string
  required: boolean
  exists: boolean
  satisfied: boolean
}

export interface LifecycleStage {
  key: string
  name: string
  description: string
  order: number
  is_current: boolean
  is_completed: boolean
  gate_satisfied: boolean
  forms: LifecycleCheckForm[]
  documents: LifecycleCheckDocument[]
}

export interface WorkspaceLifecycle {
  template_id: ID
  template_name: string
  template_version: number
  current_version: number
  current_stage: string | null
  current_stage_index: number
  stage_count: number
  can_advance: boolean
  next_stage: { key: string; name: string } | null
  stages: LifecycleStage[]
  history: Array<{
    from: string | null; to: string; at: string; by: number | null
    reason: string; forced: boolean
  }>
  version_mismatch: boolean
}
