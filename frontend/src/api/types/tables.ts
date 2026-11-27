/** 数据表、表成员、字段与字段导入分析. */

import type { ID } from './common'
import type { WorkspaceRole } from './workspaces'

// ── 数据表关联图（需求 0187 P0） ──

/** 关联图边的目标形态：ok = 本区可读表；虚拟目标见 target_state */
export type LinkGraphTargetState = 'ok' | 'other_workspace' | 'trashed' | 'restricted'

/** 关联图节点（真实表或聚合虚拟节点） */
export interface LinkGraphNode {
  id: number
  name: string
  description: string
  group_id?: number | null
  group_name: string
  field_count: number
  in_degree: number
  out_degree: number
  /** 自关联（树 / WBS 的父字段）：不画自环，改标徽标 */
  self_loop: boolean
  /** 虚拟节点（其他工作区 / 已删除不可访问的聚合目标）恒为 true，id 为负 */
  virtual: boolean
  /** 当前用户能否改这张表的字段结构（EDIT_SCHEMA，ADR 0187 E5/D8）；虚拟节点恒 false */
  can_edit: boolean
}

/** 关联图边（一条 link 字段 = 一条边；lookup 只计入 reference_field_count） */
export interface LinkGraphEdge {
  id: number
  field_name: string
  source: number
  target: number
  multiple: boolean
  reference_field_count: number
  target_state: LinkGraphTargetState
  /** 能否编辑这条边（取**源表**的 EDIT_SCHEMA，ADR 0187 E5/D8） */
  can_edit: boolean
}

/** GET /tables/link-graph 响应 */
export interface LinkGraph {
  nodes: LinkGraphNode[]
  edges: LinkGraphEdge[]
  /** 当前用户可读的表总数（含未展示） */
  total: number
  truncated: boolean
  /** 指向「可读但落在节点窗口外」的边的数量（0182 C2 同口径） */
  edges_out_of_view: number
}

export interface TableGroup {
  id: ID
  workspace_id?: ID
  name: string
  order?: number
  /** 系统「未分组」占位行：参与排序，前端显示「未分组」，不可改名 / 删除 */
  is_ungrouped?: boolean
}

export interface TableSummary {
  id: ID; name: string; description?: string
  /** 分组归属（空 = 未分组，默认） */
  group_id?: number | null
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
  /** 表级读取门槛（owner/editor/viewer；空串表示未配置、按工作区角色默认） */
  read_role?: string
  /** 是否对普通成员（viewer）受限：read_role 高于 viewer 时为 true */
  is_restricted?: boolean
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

// ── 行级权限规则（ADR 0004） ──

/** 授权主体类型：指定成员 / 表级成员档 */
export type RowSubjectType = 'user' | 'member_role'
/** 行级动作：可查看 / 可编辑（edit 隐含 view） */
export type RowActionType = 'view' | 'edit'

/** 行级权限规则（对齐后端 RowRuleResponse） */
export interface RowPermissionRule {
  id: number
  table_id: number
  subject_type: RowSubjectType
  subject_id: string
  action: RowActionType
  filters: Array<{ field_name: string; op: string; value?: unknown }>
  filter_type: 'AND' | 'OR'
  granted_by_id?: number | null
  /** 主体展示名（user 型为昵称/用户名；member_role 型为「查看者 / 编辑者」） */
  subject_name: string
  created_at: string
  updated_at: string
}

/** 可授权主体（GET /row-permissions/subjects 数据源） */
export interface RowRuleSubject {
  subject_type: RowSubjectType
  subject_id: string
  name: string
}

/** 规则命中行预览结果 */
export interface RowRulePreviewResponse {
  matched: number
  sample: Array<Record<string, unknown>>
}

/** 创建行级权限规则请求体 */
export interface RowRuleCreatePayload {
  subject_type: RowSubjectType
  subject_id: string
  action: RowActionType
  filters: Array<{ field_name: string; op: string; value?: unknown }>
  filter_type: 'AND' | 'OR'
}

/** 修改行级权限规则请求体（主体 / 动作不可改） */
export interface RowRuleUpdatePayload {
  filters?: Array<{ field_name: string; op: string; value?: unknown }>
  filter_type?: 'AND' | 'OR'
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
  /** 分组归属（空 = 未分组，默认） */
  group_id?: number | null
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
  /** 后端增强 —— 表是否配置了行级权限（默认档 row_filters 或任意行规则）；评分矩阵据此禁用录入 */
  row_rules_active?: boolean
}
export interface TableCreate {
  name: string
  description?: string
  /** 分组归属（省略 / null = 不分组） */
  group_id?: number | null
  /** 可选：从其他表引入字段 —— 建表即带字段 schema */
  import_from_table_id?: number
  import_field_ids?: number[]
  import_field_names?: string[]
  import_all_fields?: boolean
}
export interface TableUpdate {
  name?: string
  description?: string
  /** 分组归属（null = 移出分组） */
  group_id?: number | null
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
  | 'email' | 'url' | 'phone' | 'link' | 'lookup' | 'formula' | 'attachment' | 'percentage' | 'image'
  // 历史别名（后端 _FIELD_TYPE_ALIASES 自动归一化，见 field_types/registry.py）
  | 'long_text' | 'decimal' | 'multi_select' | 'json'

/** 字段敏感级（ADR 0188）：public 公开 / internal 内部（缺省）/ confidential 机密 */
export type FieldSensitivity = 'public' | 'internal' | 'confidential'

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
  // ── 业务元数据（ADR 0188）：数据字典 / 企业数据标准的落点 ──
  /** 业务口径（算的是什么、含不含税、取值边界） */
  business_meaning?: string | null
  /** 计量单位 */
  unit?: string | null
  /** 敏感级：public / internal / confidential；空 = internal */
  sensitivity?: FieldSensitivity | null
  /** 字段责任人用户 id */
  owner_id?: number | null
  /** 责任人显示名（后端按 owner 关系填充，只读） */
  owner_name?: string | null
  /** 标准来源（标准字段库 key / 规范条目） */
  standard_ref?: string | null
  /** 示例值 */
  example_value?: string | null
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
/** 字段业务元数据（ADR 0188）：新建 / 更新共用 */
export interface FieldBusinessMetadata {
  business_meaning?: string | null
  unit?: string | null
  sensitivity?: FieldSensitivity | null
  owner_id?: number | null
  standard_ref?: string | null
  example_value?: string | null
}

export interface FieldCreate extends FieldBusinessMetadata {
  name: string; field_type: FieldType; order?: number
  config?: Record<string, unknown>; required?: boolean; description?: string
  is_unique?: boolean; default_value?: unknown; hidden?: boolean
}
export interface FieldUpdate extends FieldBusinessMetadata {
  name?: string; field_type?: FieldType; order?: number
  config?: Record<string, unknown>; required?: boolean; description?: string; hidden?: boolean
  is_unique?: boolean; default_value?: unknown
}

// ─────────────────── 数据表字段字典（ADR 0188） ───────────────────

/** 数据字典导出格式 */
export type TableDictionaryFormat = 'md' | 'xlsx' | 'json' | 'docx' | 'pdf'

export interface TableDictionaryParams {
  format: TableDictionaryFormat
  /** 是否输出物理列名 / 物理表名等内部实现细节（默认 false） */
  include_internal?: boolean
  /** 排版模板（仅 docx / pdf 生效）：builtin:research / builtin:official 等 */
  template?: string
}

/** 标准符合度单项指标（ADR 0188 C4） */
export interface TableDictionaryMetric {
  covered: number
  total: number
  ratio: number
  /** 未满足该项的字段名（点击可跳字段编辑） */
  missing_fields: string[]
}

/** 标准符合度报告 */
export interface TableDictionaryScore {
  table_id: number
  table_name: string
  field_count: number
  schema_hash: string
  metrics: Record<string, TableDictionaryMetric>
  metric_labels: Record<string, string>
  overall: { ratio: number; covered: number; total: number }
}
