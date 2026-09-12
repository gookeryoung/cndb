export type ID = number | string

export interface UserResponse {
  id: ID
  username: string
  email: string
  is_active?: boolean
  created_at?: string
}

export interface LoginRequest { login: string; password: string }
export interface RegisterRequest { username: string; email: string; password: string }
export interface LoginResponse { access_token: string; token_type: string }

export interface ApiToken {
  id: ID; name: string; token: string
  created_at?: string; expires_at?: string | null
}
export interface ApiTokenCreate { name: string; expires_days?: number }

export interface Workspace {
  id: ID; name: string; description?: string; default_role?: string
  pinned?: boolean; created_at?: string; updated_at?: string
}
export interface WorkspaceDetail extends Workspace { member_count?: number; table_count?: number }
export interface WorkspaceCreate { name: string; description?: string; default_role?: string }
export interface WorkspaceUpdate { name?: string; description?: string; default_role?: string }
export type WorkspaceRole = 'owner' | 'admin' | 'editor' | 'viewer'
export interface WorkspaceMember { id: ID; username: string; email?: string; role: WorkspaceRole; joined_at?: string }
export interface WorkspaceInvite { username: string; role: WorkspaceRole }

export interface TableSummary {
  id: ID; name: string; description?: string
  record_count?: number; field_count?: number; updated_at?: string
}
export interface TableDetail {
  id: ID; workspace_id: ID; name: string; description?: string
  fields: Field[]; created_at?: string; updated_at?: string
}
export interface TableCreate { name: string; description?: string }
export interface TableUpdate { name?: string; description?: string }

export type FieldType =
  | 'text' | 'long_text' | 'number' | 'decimal' | 'boolean'
  | 'date' | 'datetime' | 'select' | 'multi_select'
  | 'email' | 'url' | 'phone' | 'link' | 'attachment'
  | 'formula' | 'auto_id' | 'created_time' | 'updated_time'
  | 'created_by' | 'updated_by'

export interface Field {
  id: ID; name: string; field_type: FieldType; db_column_name?: string
  order?: number; config?: Record<string, unknown>; required?: boolean
  description?: string; hidden?: boolean; is_primary?: boolean; created_at?: string
}
export interface FieldCreate {
  name: string; field_type: FieldType; order?: number
  config?: Record<string, unknown>; required?: boolean; description?: string
}
export interface FieldUpdate {
  name?: string; field_type?: FieldType; order?: number
  config?: Record<string, unknown>; required?: boolean; description?: string; hidden?: boolean
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
  filters?: string | Record<string, unknown>
  sorts?: string | Record<string, unknown>
}

export interface View {
  id: ID; name: string; view_type?: string
  filters?: Record<string, unknown> | null; sorts?: Record<string, unknown> | null
  field_order?: string[] | null; default?: boolean; created_at?: string
}
export interface ViewDetail extends View {}
export interface ViewCreate {
  name: string; view_type?: string
  filters?: Record<string, unknown> | null; sorts?: Record<string, unknown> | null
  field_order?: string[] | null; default?: boolean
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
}

/** 回收站中的行 — 同样扁平结构 */
export interface TrashedRow {
  id: ID
  original_id?: ID
  deleted_at?: string
  [fieldName: string]: unknown
}
export interface WorkspaceTrashResponse {
  tables: TableSummary[]; fields: Field[]; trashed_rows: TrashedRow[]
}

export interface GraphNode { id: string; label: string; type?: string }
export interface GraphEdge { source: string; target: string; label?: string }
export interface GraphResponse { nodes: GraphNode[]; edges: GraphEdge[]; topo_order?: string[] }
export interface DependencyResponse { forward: Record<string, string[]>; reverse: Record<string, string[]> }

export interface CsvAnalyzeResult { columns: string[]; total_rows: number }
export interface CsvImportResult { table_id: ID; imported_rows: number }

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
  hidden_fields?: string[] | null
  row_filters?: Record<string, unknown> | null
  comment?: string
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

