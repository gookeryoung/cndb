export type ID = number | string

export type WorkspaceVisibility = 'public' | 'member' | 'private'

/** 用户角色 —— 三员 + 普通用户（参考 GB/T 22239 等级保护模型） */
export type UserRole = 'system_admin' | 'security_admin' | 'audit_admin' | 'user'

/** 角色中文显示名映射 */
export const USER_ROLE_LABEL: Record<UserRole, string> = {
  system_admin: '系统管理员',
  security_admin: '安全管理员',
  audit_admin: '审计管理员',
  user: '普通用户',
}

export interface UserResponse {
  id: ID
  username: string
  email: string | null
  nickname?: string
  role: UserRole
  is_active?: boolean
  is_superuser?: boolean
  created_at?: string
}

export interface LoginRequest { login: string; password: string }
/** 当前用户自助更新个人资料请求体 —— 仅提交的字段会被更新，邮箱传空串表示清空. */
export interface ProfileUpdateRequest { nickname?: string; email?: string }
/** 公开注册请求体 —— 已收窄为仅普通用户，不接受 role 参数. */
export interface RegisterRequest { username: string; email?: string | null; password: string; nickname?: string }
/** 管理员创建用户请求体 —— role 必填（三员 + user 任意）. */
export interface AdminRegisterRequest extends Omit<RegisterRequest, 'password'> { password: string; role: UserRole }
export interface LoginResponse { access_token: string; token_type: string }

export interface Workspace {
  id: ID; name: string; description?: string; default_role?: string
  pinned?: boolean; created_at?: string; updated_at?: string
  visibility?: WorkspaceVisibility; tags?: string[]; allow_edit?: boolean
  current_user_role?: WorkspaceRole | null
}
export interface WorkspaceDetail extends Workspace {
  member_count?: number; table_count?: number
  view_count?: number; total_rows?: number
  owner?: { id: ID; username: string; nickname?: string } | null
  current_user_role?: WorkspaceRole | null
}
export interface WorkspaceCreate {
  name: string; description?: string; default_role?: string
  visibility?: WorkspaceVisibility; tags?: string[]; allow_edit?: boolean
}
export interface WorkspaceUpdate {
  name?: string; description?: string; default_role?: string
  visibility?: WorkspaceVisibility; tags?: string[]; allow_edit?: boolean
}
export type WorkspaceRole = 'owner' | 'admin' | 'editor' | 'viewer'

/** 成员中的用户简要信息（对齐后端 MemberUserBrief） */
export interface MemberUserBrief {
  id: ID; username: string; nickname?: string; email?: string | null
}

/** 工作区成员（对齐后端 WorkspaceMemberResponse） */
export interface WorkspaceMember {
  id: ID; workspace_id: ID; user_id: ID
  role: WorkspaceRole; pinned?: boolean; created_at?: string
  user: MemberUserBrief
}

/** 工作区级整体导出数据结构 */
export interface WorkspaceExportData {
  version: string
  exported_at: string
  workspace: {
    name: string; description: string; visibility: WorkspaceVisibility; tags: string[]; allow_edit: boolean
  }
  tables: Array<{
    name: string; description: string
    fields: Array<Record<string, unknown>>
    views: Array<Record<string, unknown>>
    rows: Array<Record<string, unknown>>
  }>
}

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
export interface TableUpdate { name?: string; description?: string }

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

export type FieldType =
  | 'text' | 'longtext' | 'number' | 'float' | 'boolean'
  | 'date' | 'datetime' | 'timestamp' | 'select' | 'multiselect'
  | 'email' | 'url' | 'phone' | 'link' | 'lookup' | 'attachment' | 'percentage'
  // 历史别名（后端自动归一化）
  | 'long_text' | 'decimal' | 'multi_select' | 'json'
  | 'formula' | 'auto_id' | 'created_time' | 'updated_time'
  | 'created_by' | 'updated_by'

export interface Field {
  id: ID; name: string; field_type: FieldType; db_column_name?: string
  order?: number; config?: Record<string, unknown>; required?: boolean
  /** 字段唯一约束 */
  is_unique?: boolean
  /** 默认值（后端支持任意类型） */
  default_value?: unknown
  /** 是否在视图中隐藏（后端 FieldUpdate 支持，前端 Field 保留字段） */
  hidden?: boolean
  description?: string; is_primary?: boolean; created_at?: string
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

export type RowValues = Record<string, unknown>

/** 后端返回的行数据 — 扁平 dict，业务字段直接以字段名作为 key，不再嵌套 values.
 * 例如：{ id: 1, '姓名': '张三', '薪资': 15000, created_at: '...' }
 */
export interface RowResponse {
  id: ID
  created_at?: string
  updated_at?: string
  created_by?: ID | null
  updated_by?: ID | null
  /** 业务字段以字段名直接作为 key，类型由各字段定义决定 */
  [fieldName: string]: unknown
}

export type RowDetail = RowResponse

/** 创建行的请求体：values 字段承载业务值 */
export interface RowCreate { values: RowValues }

/** 更新行的请求体：values 字段承载待更新的业务值子集 */
export interface RowUpdate { values: RowValues }
export interface RowListResponse { items: RowResponse[]; total: number; offset: number; limit: number }
export interface RecordListParams {
  offset?: number; limit?: number
  filters?: string | Record<string, unknown> | Array<Record<string, unknown>>
  sorts?: string | Record<string, unknown> | Array<Record<string, unknown>>
  filter_logic?: 'AND' | 'OR'
}

export interface View {
  id: ID; name: string; view_type: string
  filters?: Record<string, unknown> | Array<{ field_name: string; op: string; value?: unknown }> | null
  /** 视图级排序规则（后端字段名 sortings） */
  sortings?: Record<string, unknown> | Array<{ field_name: string; direction: 'asc' | 'desc' }> | null
  /** 多条件组合方式（后端字段名 filter_type） */
  filter_type?: 'AND' | 'OR'
  field_order?: string[] | null; view_options?: Record<string, unknown> | null
  /** 是否默认视图（对齐后端 ViewResponse.is_default） */
  is_default: boolean; created_at?: string
  /** 排序权重（后端 DataView.order） */
  order?: number
}
export type ViewDetail = View
export interface ViewCreate {
  name: string; view_type?: string
  filters?: Record<string, unknown> | Array<{ field_name: string; op: string; value?: unknown }> | null
  sortings?: Record<string, unknown> | Array<{ field_name: string; direction: 'asc' | 'desc' }> | null
  filter_type?: 'AND' | 'OR'
  field_order?: string[] | null; view_options?: Record<string, unknown> | null
  /** 是否设为默认视图（对齐后端 ViewCreate.is_default） */
  is_default?: boolean
}
export interface ViewUpdate {
  name?: string; view_type?: string
  filters?: Record<string, unknown> | Array<{ field_name: string; op: string; value?: unknown }> | null
  sortings?: Record<string, unknown> | Array<{ field_name: string; direction: 'asc' | 'desc' }> | null
  filter_type?: 'AND' | 'OR' | null
  field_order?: string[] | null; view_options?: Record<string, unknown> | null
  /** 是否设为默认视图（对齐后端 ViewUpdate.is_default） */
  is_default?: boolean
}

export interface AuditLog {
  id: ID; table_id?: ID; row_id?: ID; action: string
  actor_id?: ID | null; actor_name?: string
  payload?: Record<string, unknown> | null; created_at?: string
}
export interface Reference {
  id: ID
  from_table_id: ID; from_row_id: ID; from_field_id: ID
  to_table_id: ID; to_row_id: ID; to_field_id: ID; created_at?: string
  /** 前端便捷展示用：被引用表 ID（同 to_table_id） */
  table_id?: ID
  /** 前端便捷展示用：被引用行 ID（同 to_row_id） */
  row_id?: ID
  /** 前端便捷展示用：被引用表名称 */
  table_name?: string
  /** 前端便捷展示用：被引用行摘要 */
  row_summary?: string
}

/** 回收站中的行 — 同样扁平结构 */
export interface TrashedRow {
  id: ID
  original_id?: ID
  deleted_at?: string
  /** 软删时间（后端可能返回 _trashed_at 或 deleted_at） */
  _trashed_at?: string
  [fieldName: string]: unknown
}
export interface WorkspaceTrashResponse {
  tables: TableSummary[]; fields: Field[]; trashed_rows: TrashedRow[]
  /** 各表的软删行计数 */
  row_counts?: Array<{ table_id: ID; table_name: string; trashed_rows: number }>
}

export interface CsvAnalyzeResult { columns: string[]; total_rows: number }
export interface CsvImportResult { table_id: ID; imported_rows: number; table_name?: string; imported?: number }

/** 通用文件导入分析结果（新） */
export interface FileAnalyzeResult {
  columns: Array<{ name: string; field_type: string; sample_values?: string[]; null_ratio?: number; options?: string[] }>
  total_rows: number
  format: string
  filename?: string
  /** 前端做"典型数据 + 实时转换预览"使用（前 50 行） */
  sample_rows?: Array<Record<string, unknown>>
}
/** 通用文件建表导入结果（新） */
export interface FileImportResult {
  table_id: ID
  table_name: string
  imported_rows: number
  field_count: number
  format?: string
  columns?: Array<{ name: string; field_type: string }>
}

export interface PublicForm {
  slug: string; title: string; description?: string
  fields: Field[]; created_at?: string
}
export interface SharedGrid {
  slug: string; title: string; table: TableDetail
  rows: RowResponse[]; total: number
}

/** 报告模板参数定义 */
export interface ReportParameter {
  name: string
  type: 'string' | 'number' | 'date' | 'boolean'
  default?: unknown
  required?: boolean
  label?: string
}

/** 报告主题风格取值（与后端 ThemeStyle 对齐） */
export type ReportTheme = 'business' | 'minimal' | 'modern' | 'engineering' | 'academic'

/** 报告模板（列表精简） */
export interface ReportTemplateSummary {
  id: ID
  table_id: number | null
  name: string
  description: string
  output_format: string
  parameters: ReportParameter[]
  /** 持久化的额外引用表 ID 列表（不含主表自身） */
  extra_table_ids: number[]
  /** 主题风格，默认简约 */
  theme: ReportTheme
}

/** 报告模板（详情，含模板内容） */
export interface ReportTemplate extends ReportTemplateSummary {
  template_content: string
  created_at: string
  updated_at: string
}

export interface ReportTemplateCreate {
  name: string
  description?: string
  output_format?: string
  template_content: string
  table_id?: number | null
  parameters?: ReportParameter[]
  extra_table_ids?: number[]
  theme?: ReportTheme
}

export interface ReportTemplateUpdate {
  name?: string
  description?: string
  output_format?: string
  template_content?: string
  table_id?: number | null
  parameters?: ReportParameter[]
  extra_table_ids?: number[]
  theme?: ReportTheme
}

export interface ReportRenderRequest {
  table_id: number
  params?: Record<string, unknown>
  row_ids?: Array<number | null> | null
  /** 可选：额外引用的数据表 ID 列表 */
  extra_table_ids?: number[]
}

export interface ReportRenderResult {
  filename: string
  content_type: string
  size: number
}

/** 导入任务状态 */
export type ImportTaskStatus =
  | 'pending'
  | 'pending_validation'
  | 'pending_confirm'
  | 'running'
  | 'done'
  | 'failed'

/** 校验报告（DiffReporter 输出结构 — V2 支持 upsert + 字段自动新增） */
export interface ValidationReport {
  total: number
  valid_count: number
  warning_count: number
  error_count: number
  /** V2: 待新增行数（未指定 match_keys 时等于 valid_count） */
  new_count?: number
  /** V2: 待更新行数 */
  update_count?: number
  /** V2: 多行同 key 冲突数 */
  multi_key_conflicts?: number
  skipped_columns: string[]
  missing_required: string[]
  /** V2: 未知列自动新增规划 */
  planned_columns?: Array<{
    name: string; field_type: string; options?: string[]; sample_values?: string[]
  }>
  /** V2: 待新增行预览（限前 200 行） */
  new_preview?: Array<{
    row_number: number; match_key_values: Record<string, unknown>; field_sample: Record<string, unknown>
  }>
  /** V2: 待更新行预览（含字段级 diff） */
  update_preview?: Array<{
    row_number: number; match_key_values: Record<string, unknown>; existing_row_id: number; field_sample: Record<string, unknown>;
    /** 仅包含 changed=true 的业务字段（不含 match_keys）— old 为 DB 旧值, new 为文件新值 */
    field_diffs?: Record<string, { old: unknown; new: unknown; changed: boolean }>
  }>
  warnings: Array<{ row_number: number; field: string; message: string }>
  errors: Array<{ row_number: number; field: string; message: string }>
  actually_imported?: number
  /** V2: execute 后补充 */
  actually_created?: number
  actually_updated?: number
  /** V2: 列级数据质量画像 */
  column_profiles?: Array<{
    name: string
    inferred_type: string
    confidence: number
    fallback_type?: string | null
    null_count: number
    null_ratio: number
    unique_count: number
    sample_values?: string[]
    type_conflicts?: Array<{ row_number: number; value: string; conflicting_type: string }>
    outliers?: Array<{ value: string | number; type: string; row_number?: number | null }>
    /** 数值列: min/max/mean/std */
    min?: number; max?: number; mean?: number; std?: number
    /** 数值列直方图 */
    distribution_bins?: Array<{ bin_label: string; count: number; low: number; high: number }>
    /** 离散列 Top N 分布 */
    value_counts?: Array<{ value: string; count: number }>
    select_options?: string[]
  }>
  /** V2: 整体数据质量 summary */
  data_quality_summary?: {
    total_rows: number
    total_columns: number
    duplicate_rows: number
    empty_columns: string[]
    high_null_columns: string[]
  }
  /** V2: 建议的清洗操作 */
  cleaning_suggestions?: Array<{
    id: string; column: string | null; action: string
    strategy?: string | null; on_fail?: string | null
    affected_count: number; reason: string
    preview_before?: unknown[]; preview_after?: unknown[]
  }>
  /** V2: execute 后实际执行的清洗 */
  cleaning_applied?: Array<{
    action: string; column: string | null; strategy?: string | null; affected_rows: number
  }>
}

export interface ImportTaskInfo {
  task_id: ID; status: ImportTaskStatus; progress: number
  filename: string; format: string
  total_rows?: number | null; imported_rows?: number | null
  error_message?: string | null
  result_ids?: Array<number | string>
  created_at?: string | null; updated_at?: string | null
  /** analyze 阶段产出的校验报告（JSON） */
  validation_report?: ValidationReport | null
}

/** 表权限 */
export interface TablePermission {
  /** 按角色分桶的隐藏字段: { "admin": ["field_name", ...], "editor": [...] } */
  hidden_fields?: Record<string, string[]> | null
  row_filters?: Record<string, unknown> | null
}

// ── Attachment ──────────────────────────────────────

export interface AttachmentFile {
  /** 后端 upload 返回的稳定存储键（uuid.ext） */
  file_key: string
  /** 原始文件名 */
  filename: string
  /** 字节数 */
  size?: number
  /** MIME 类型 */
  mime_type?: string
  /** ISO 时间 */
  created_at?: string
}


// ── User Preferences ───────────────────────────────

/** 用户偏好：每张表的激活视图映射 */
export interface PreferencesResponse {
  /** 每张表的激活视图映射: table_id(str) -> view_id(int) */
  active_views: Record<string, number>
}

// ── API 自动建表 / 数据抓取 ────────────────────────

/** API 抓取通用请求体（对齐后端 ApiFetchRequest） */
export interface ApiFetchRequest {
  url: string
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'
  headers?: Record<string, string>
  params?: Record<string, unknown>
  body?: unknown
  data_path?: string | null
  timeout?: number
  /** 响应处理器：json / tencent_stock / 自定义 */
  response_handler?: string
  /** 响应编码，如 utf-8 / gbk */
  encoding?: string
  /** 查询间隔（秒），默认 60，最短 6 */
  query_interval?: number
}

/** 分析接口返回的列元数据（对齐后端 analyze_json_columns 的输出） */
export interface ApiAnalyzeColumn {
  name: string
  field_type: FieldType
  /** 非空样本数 */
  non_null_count?: number
  /** 空值比例 0-1 */
  null_ratio?: number
  /** 样本值（最多几条） */
  samples?: unknown[]
  /** 推测出的选项列表（select 类型） */
  options?: string[]
}

/** POST /{wid}/import-api/analyze 响应 */
export interface ApiAnalyzeResult {
  columns: ApiAnalyzeColumn[]
  total_rows: number
  sample_row_keys: string[]
}

/** POST /{wid}/import-api 响应（建表 + 导入） */
export interface ApiImportResult {
  table_id: ID
  table_name: string
  imported_rows: number
  field_count: number
  columns: ApiAnalyzeColumn[]
}

/** POST /{wid}/tables/{tid}/import-api 响应（追加） */
export interface ApiAppendResult {
  table_id: ID
  appended_rows: number
}

/** POST /{wid}/import-api/config 请求体 */
export interface ApiConfigRequest {
  config_json: string
  stop_on_error?: boolean
}

/** 配置文件校验结果 */
export interface ApiConfigValidateResult {
  valid: boolean
  table_count: number
  tables: Array<{
    table_name: string
    handler: string
    encoding: string
    query_interval: number
    url: string
  }>
}

/** 配置文件批量建表结果 */
export interface ApiConfigImportResult {
  success_count: number
  fail_count: number
  results: Array<{
    table_name: string
    table_id: ID
    imported_rows: number
    field_count: number
    query_interval: number
  }>
  errors: Array<{ table_name: string; error: string }>
  stopped_on_error: boolean
}
