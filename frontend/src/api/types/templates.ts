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

export interface TemplateSpecFlowStep {
  key: string
  name: string
  description?: string
  form?: string | null
  documents?: string[]
}

export interface TemplateSpecFlow {
  key: string
  name: string
  description?: string
  steps: TemplateSpecFlowStep[]
}

export interface TemplateSpec {
  forms: TemplateSpecForm[]
  documents: TemplateSpecDocument[]
  stages: TemplateSpecStage[]
  flows?: TemplateSpecFlow[]
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
  counts: {
    stage_count: number; form_count: number; field_count: number; document_rule_count: number;
    flow_count?: number; step_count?: number;
  }
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
  flows?: { added: Array<{ key: string; name: string }>; removed: Array<{ key: string; name: string }>; modified: Array<{ key: string; name: string; changes: string[] }> }
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

/** 数据流程（需求 0095）：模板驱动的表单式增删查改元数据. */
export interface DataFlowField {
  name: string
  field_type: string
  required: boolean
  config: Record<string, unknown>
  order: number
  hidden: boolean
  default_value?: unknown
}

export interface DataFlowForm {
  key: string
  name: string
  description: string
  table_id: number | null
  table_name: string | null
  flow: {
    enabled: boolean
    list_fields: string[]
    search_fields: string[]
    form_groups: Array<{ title: string; fields: string[] }>
    detail_groups: Array<{ title: string; fields: string[] }>
    hints: Record<string, string>
    default_values: Record<string, unknown>
    allow_create: boolean
    allow_edit: boolean
    allow_delete: boolean
    default_sort: { field: string; order: 'asc' | 'desc' } | null
    empty_text: string
  }
  fields: DataFlowField[]
  record_count: number
  can_create: boolean
  can_edit: boolean
  can_delete: boolean
}

export interface DataFlowStage {
  key: string
  name: string
  description: string
  order: number
  is_current: boolean
  is_completed: boolean
  gate_satisfied: boolean
  forms: DataFlowForm[]
}

export interface DataFlowStep {
  key: string
  name: string
  description: string
  form: DataFlowForm | null
  documents: string[]
}

export interface DataFlowFlow {
  key: string
  name: string
  description: string
  stage?: string | null
  stage_name?: string | null
  steps: DataFlowStep[]
  form_count: number
  step_count: number
  record_count: number
}

export interface WorkspaceDataFlow {
  template_id: number
  template_name: string
  template_version: number
  current_version: number
  current_stage: string | null
  current_stage_index: number
  can_advance: boolean
  next_stage: { key: string; name: string } | null
  stages: DataFlowStage[]
  flows?: DataFlowFlow[]
}
