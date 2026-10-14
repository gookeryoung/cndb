/** 数据表、表成员、字段与字段导入分析. */

import type { ID } from './common'
import type { WorkspaceRole } from './workspaces'

export interface TableSummary {
  id: ID; name: string; description?: string
  record_count?: number | null; field_count?: number | null; view_count?: number | null
  /** 排序权重（后端 DataTable.order） */
  order?: number
  /** 软删标记（后端 TableResponse 新增，TablesList 不展示但 API 有返回） */
  trashed?: boolean
  trashed_at?: string | null
  updated_at?: string
  /** 表拥有者（owner） */
  owner?: TableOwnerInfo | null
  /** 显式成员数（不含 owner，可空） */
  member_count?: number
  /** 当前用户在该表的访问级别（owner > write > read > none） */
  my_access?: 'owner' | 'write' | 'read' | 'none'
}

/** 表拥有者简要信息 */
export interface TableOwnerInfo {
  id: number | string
  username: string
}

/** 表成员（对齐后端 TableMember） */
export interface TableMember {
  user_id: number | string
  username: string
  role: 'read' | 'write'
}

/** 添加表成员请求体 */
export interface MemberCreate {
  user_id: number
  role: 'read' | 'write'
}

/** 更新表成员授权请求体 */
export interface MemberUpdate {
  role: 'read' | 'write'
}

/** 转让所有权请求体 */
export interface OwnerTransferPayload {
  user_id: number
}
/** 视图精简摘要（嵌入 TableDetail） */
export interface ViewBrief {
  id: ID; name: string; view_type: string; is_default: boolean
}
/** 表所属工作区的 owner 简要信息（对齐后端 OwnerBrief） */
export interface OwnerBrief {
  id: ID; username: string; nickname?: string
}
/** 表所属工作区精简摘要（避免前端额外调 workspaceApi.get） */
export interface WorkspaceBrief {
  id: ID; name: string; visibility?: string; allow_edit?: boolean
  current_user_role?: WorkspaceRole | null
}
export interface TableDetail {
  id: ID; workspace_id: ID; name: string; db_table_name?: string; description?: string
  fields: Field[]; created_at?: string; updated_at?: string
  /** 后端增强 —— 可选统计字段 */
  field_count?: number | null; record_count?: number | null; view_count?: number | null
  /** 后端增强 —— 表级拥有者（DataTable.owner_id 关联的用户，来自 TableResponse） */
  owner?: TableOwnerInfo | null
  /** 后端增强 —— 视图精简摘要（避免前端再调一次 viewApi.list） */
  views?: ViewBrief[]
  /** 后端增强 —— 当前用户在该表可执行的动作集合 */
  current_user_actions?: string[]
  /** 后端增强 —— 所属工作区的 owner（WorkspaceRole.owner 成员，与表级 owner 区分） */
  workspace_owner?: OwnerBrief | null
  /** 后端增强 —— 所属工作区精简摘要 */
  workspace?: WorkspaceBrief | null
  /** 后端增强 —— 是否在回收站（软删） */
  trashed?: boolean
}
export interface TableCreate {
  name: string
  description?: string
  /** 可选：从其他表引入字段 —— 建表即带字段 schema */
  import_from_table_id?: number
  import_field_ids?: number[]
  import_field_names?: string[]
  import_all_fields?: boolean
}
export interface TableUpdate {
  name?: string
  description?: string
}

// ── 字段从其他表引入 ──

export interface FieldImportRequest {
  source_table_id: number
  field_ids?: number[]
  field_names?: string[]
  import_all_fields?: boolean
  exclude_trashed?: boolean
  skip_conflicts?: boolean
  /** 源字段 → 目标字段 重命名/跳过映射；None 表示跳过 */
  field_mapping?: Record<string, string | null> | null
  /** 引入模式：copy=复制字段定义（默认）；link=字段关联（自动建 link 字段 + lookup 字段，值实时解析） */
  import_mode?: 'copy' | 'link'
  /** 预览模式：只返回建议映射/缺口分析，不实际创建 */
  preview_only?: boolean
}

/** link 模式预览返回的将创建字段清单项 */
export interface PlannedImportField {
  name: string
  field_type: 'link' | 'lookup'
}

export interface FieldImportGapAnalysis {
  matched: Array<{ source: string; target: string }>
  unmapped_source: string[]
  target_missing: string[]
  conflicts: Array<{ src_a: string; src_b: string; dst: string }>
  /** link 模式预览：将创建的字段清单（自动 link 字段 + lookup 字段） */
  planned_fields?: PlannedImportField[]
}

export interface FieldImportSuggestion {
  source: string
  target: string | null
  score: number
  reason: string
  will_map: boolean
}

export interface FieldImportResponse {
  created: Field[]
  skipped: string[]
  total_source_count: number
  /** 总是返回 — 四象限缺口分析 */
  gap_analysis?: FieldImportGapAnalysis | null
  /** 智能建议列表 — preview_only=True 时主要返回这个 */
  suggestions?: FieldImportSuggestion[] | null
}

/** 字段改为单选/多选时的「识别选项」请求体 */
export interface FieldDetectOptionsRequest {
  /** 目标类型：select=整值识别；multiselect=按 delimiter 拆分 */
  target_type: 'select' | 'multiselect'
  /** multiselect 识别分隔符，默认半角逗号；select 忽略 */
  delimiter?: string
}

/** 识别结果：按首现顺序排列的唯一值列表（不持久化，用户确认后随 config 保存） */
export interface FieldDetectOptionsResponse {
  options: string[]
}

export type FieldType =
  | 'text' | 'longtext' | 'number' | 'float' | 'boolean'
  | 'date' | 'datetime' | 'timestamp' | 'select' | 'multiselect'
  | 'email' | 'url' | 'phone' | 'link' | 'lookup' | 'attachment' | 'percentage' | 'image'
  // 历史别名（后端 _FIELD_TYPE_ALIASES 自动归一化，见 field_types/registry.py）
  | 'long_text' | 'decimal' | 'multi_select' | 'json'

export interface Field {
  id: ID; name: string; field_type: FieldType; db_column_name?: string
  order?: number; config?: Record<string, unknown>; required?: boolean
  /** 字段唯一约束 */
  is_unique?: boolean
  /** 默认值（后端支持任意类型） */
  default_value?: unknown
  /** 是否在视图中隐藏（后端 FieldUpdate 支持，前端 Field 保留字段） */
  hidden?: boolean
  description?: string; created_at?: string
  /** 所属表 ID（回收站字段列表等场景使用） */
  table_id?: ID
  /** 所属表名称（回收站字段列表等场景使用） */
  table_name?: string
  /** 软删标记 */
  trashed?: boolean
  /** 软删时间（回收站场景） */
  trashed_at?: string | null
  updated_at?: string
}
export interface FieldCreate {
  name: string; field_type: FieldType; order?: number
  config?: Record<string, unknown>; required?: boolean; description?: string
  is_unique?: boolean; default_value?: unknown; hidden?: boolean
}
export interface FieldUpdate {
  name?: string; field_type?: FieldType; order?: number
  config?: Record<string, unknown>; required?: boolean; description?: string; hidden?: boolean
  is_unique?: boolean; default_value?: unknown
}
