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
export interface RegisterRequest { username: string; email?: string | null; password: string; nickname?: string; role?: UserRole }
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
export interface WorkspaceInvite { username: string; role: WorkspaceRole }

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
  /** 软删标记（后端 TableResponse 新增，TablesList 不展示但 API 有返回） */
  trashed?: boolean
  trashed_at?: string | null
  updated_at?: string
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
  /** 后端增强 —— 视图精简摘要（避免前端再调一次 viewApi.list） */
  views?: ViewBrief[]
  /** 后端增强 —— 当前用户在该表可执行的动作集合 */
  current_user_actions?: string[]
  /** 后端增强 —— 所属工作区的 owner */
  owner?: OwnerBrief | null
  /** 后端增强 —— 所属工作区精简摘要 */
  workspace?: WorkspaceBrief | null
  /** 后端增强 —— 是否在回收站（软删） */
  trashed?: boolean
}
export interface TableCreate { name: string; description?: string }
export interface TableUpdate { name?: string; description?: string }

export type FieldType =
  | 'text' | 'longtext' | 'number' | 'float' | 'boolean'
  | 'date' | 'datetime' | 'timestamp' | 'select' | 'multiselect'
  | 'email' | 'url' | 'phone' | 'link' | 'attachment' | 'percentage'
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
  is_unique?: boolean; default_value?: unknown
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
  id: ID; name: string; view_type?: string
  filters?: Record<string, unknown> | Array<{ field_name: string; op: string; value?: unknown }> | null
  /** 视图级排序规则（后端字段名 sortings） */
  sortings?: Record<string, unknown> | Array<{ field_name: string; direction: 'asc' | 'desc' }> | null
  /** 多条件组合方式（后端字段名 filter_type） */
  filter_type?: 'AND' | 'OR'
  field_order?: string[] | null; view_options?: Record<string, unknown> | null
  default?: boolean; created_at?: string
}
export type ViewDetail = View
export interface ViewCreate {
  name: string; view_type?: string
  filters?: Record<string, unknown> | Array<{ field_name: string; op: string; value?: unknown }> | null
  sortings?: Record<string, unknown> | Array<{ field_name: string; direction: 'asc' | 'desc' }> | null
  filter_type?: 'AND' | 'OR'
  field_order?: string[] | null; view_options?: Record<string, unknown> | null
  default?: boolean
}
export interface ViewUpdate {
  name?: string; view_type?: string
  filters?: Record<string, unknown> | Array<{ field_name: string; op: string; value?: unknown }> | null
  sortings?: Record<string, unknown> | Array<{ field_name: string; direction: 'asc' | 'desc' }> | null
  filter_type?: 'AND' | 'OR' | null
  field_order?: string[] | null; view_options?: Record<string, unknown> | null
  default?: boolean
}

export interface AuditLog {
  id: ID; table_id?: ID; row_id?: ID; action: string
  actor_id?: ID | null; actor_name?: string
  payload?: Record<string, unknown> | null; created_at?: string
}
export interface Comment {
  id: ID; row_id?: ID; author_id?: ID | null; author_name?: string
  content: string; created_at?: string; updated_at?: string
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

export interface GraphNode {
  /** 字符串化的表 ID（前端 Map key 用） */
  id: string
  /** 节点显示名称 */
  label: string
  /** 节点类型：table/view/workflow 等 */
  type?: string
  /** 原始表 ID（数字，用于跳转） */
  table_id?: number
  /** 原始表名（兼容保留，等同于 label） */
  name?: string
  /** 字段数（不含软删） */
  field_count?: number
  /** 物理行数（表结构异常时为 null） */
  row_count?: number | null
  /** 视图数 */
  view_count?: number
  /** 入度（被多少张表引用） */
  link_count?: number
  /** 软删标记 */
  trashed?: boolean
}
export interface GraphEdge {
  /** 源节点 id(str) */
  source: string
  /** 目标节点 id(str) */
  target: string
  /** 边标签（link 字段名） */
  label?: string
  /** link 字段名（兼容保留） */
  link_field_name?: string
}
export interface GraphResponse {
  nodes: GraphNode[]
  edges: GraphEdge[]
  topo_order?: string[]
}
export interface DependencyResponse { forward: Record<string, string[]>; reverse: Record<string, string[]> }

export interface CsvAnalyzeResult { columns: string[]; total_rows: number }
export interface CsvImportResult { table_id: ID; imported_rows: number; table_name?: string; imported?: number }

export interface PublicForm {
  slug: string; title: string; description?: string
  fields: Field[]; created_at?: string
}
export interface SharedGrid {
  slug: string; title: string; table: TableDetail
  rows: RowResponse[]; total: number
}

export interface HealthPingResponse { status: string; timestamp: string; python: string; platform: string }
export interface HealthReadyResponse { status: string }

/** 报告模板参数定义 */
export interface ReportParameter {
  name: string
  type: 'string' | 'number' | 'date' | 'boolean'
  default?: unknown
  required?: boolean
  label?: string
}

/** 报告模板（列表精简） */
export interface ReportTemplateSummary {
  id: ID
  table_id: number | null
  name: string
  description: string
  output_format: string
  parameters: ReportParameter[]
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
}

export interface ReportTemplateUpdate {
  name?: string
  description?: string
  output_format?: string
  template_content?: string
  table_id?: number | null
  parameters?: ReportParameter[]
}

export interface ReportRenderRequest {
  table_id: number
  params?: Record<string, unknown>
  row_ids?: Array<number | null> | null
}

export interface ReportRenderResult {
  filename: string
  content_type: string
  size: number
}

/** 导入任务状态 */
export type ImportTaskStatus = 'pending' | 'running' | 'done' | 'failed'
export interface ImportTaskInfo {
  task_id: ID; status: ImportTaskStatus; progress: number
  filename: string; format: string
  total_rows?: number | null; imported_rows?: number | null
  error_message?: string | null
  result_ids?: Array<number | string>
  created_at?: string | null; updated_at?: string | null
}

/** 表权限 */
export interface TablePermission {
  /** 按角色分桶的隐藏字段: { "admin": ["field_name", ...], "editor": [...] } */
  hidden_fields?: Record<string, string[]> | null
  row_filters?: Record<string, unknown> | null
  /** 角色级备注字段 (后端: comment_role) */
  comment_role?: string
}

// ── Workflows ───────────────────────────────────────

/** 节点绑定表的摘要 */
export interface NodeTableBrief {
  id: ID
  name: string
  view_count: number
  row_count: number | null
}

/** 工作流节点 */
export interface WorkflowNode {
  id: ID
  workflow_id: ID
  name: string
  table_id: ID | null
  pos_x: number
  pos_y: number
  config: Record<string, unknown>
  /** 绑定表摘要；表被软删/移出工作区时为 null（未绑定） */
  table: NodeTableBrief | null
  created_at?: string
  updated_at?: string
}

/** 工作流边 */
export interface WorkflowEdge {
  id: ID
  workflow_id: ID
  source_node_id: ID
  target_node_id: ID
  label: string
  created_at?: string
  updated_at?: string
}

/** 工作流列表项 */
export interface WorkflowSummary {
  id: ID
  workspace_id: ID
  name: string
  description: string
  order: number
  node_count: number
  created_at?: string
  updated_at?: string
}

/** 工作流详情 */
export interface WorkflowDetail extends WorkflowSummary {
  nodes: WorkflowNode[]
  edges: WorkflowEdge[]
}

export interface WorkflowCreate {
  name: string
  description?: string
}
export interface WorkflowUpdate {
  name?: string
  description?: string
  order?: number
}

export interface WorkflowNodeCreate {
  name: string
  table_id?: ID | null
  pos_x?: number
  pos_y?: number
  config?: Record<string, unknown>
}
export interface WorkflowNodeUpdate {
  name?: string
  table_id?: ID | null
  pos_x?: number
  pos_y?: number
  config?: Record<string, unknown>
}

export interface WorkflowEdgeCreate {
  source_node_id: ID
  target_node_id: ID
  label?: string
}
export interface WorkflowEdgeUpdate {
  label?: string
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

/** 设置单表激活视图 */
export interface ActiveViewUpsert {
  active_view_id: number | null
}

/** 查询单表激活视图偏好的响应 */
export interface ActiveViewResponse {
  table_id: number
  active_view_id: number | null
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
