/** API 客户端 — 对齐 cndb 后端 FastAPI 真实路由.
 *
 * 后端挂载规则：
 * - /api/v1/accounts/auth/*       → 认证（register/login/me）
 * - /api/v1/workspaces/*          → 工作区 + 成员 + pin（route_prefix=""）
 * - /api/v1/workspaces/{wid}/tables/*       → 表 CRUD
 * - /api/v1/workspaces/{wid}/tables/{tid}/fields/*    → 字段
 * - /api/v1/workspaces/{wid}/tables/{tid}/records/*   → 行
 * - /api/v1/workspaces/{wid}/tables/{tid}/views/*     → 视图
 * - /api/v1/workspaces/{wid}/tables/{tid}/permissions → 表级权限
 * - /api/v1/workspaces/{wid}/tables/{tid}/comments/*  → 评论（嵌套在 records 下）
 * - /api/v1/workspaces/{wid}/tables/{tid}/audit       → 审计
 * - /api/v1/workspaces/{wid}/trash/*                  → 回收站概览
 * - /api/v1/workspaces/{wid}/tables/{tid}/trash-rows  → 表级回收站行
 * - /api/v1/workspaces/{wid}/tables/{tid}/export|import|import/async  → 导入导出
 * - /api/v1/workspaces/{wid}/import-csv/*             → CSV 自动建表
 * - /api/v1/workspaces/{wid}/graph|dependencies       → 关系图
 * - /api/v1/public/*               → 公开分享（全局挂载）
 * - /api/v1/health/*               → 健康检查
 * - reports 插件单独挂载（见 reports plugin route_prefix）
 */

import api from './client'
import type {
  LoginRequest, RegisterRequest,
  UserResponse,
  WorkspaceCreate, WorkspaceUpdate, Workspace, WorkspaceDetail, WorkspaceMember,
  TableCreate, TableUpdate, TableSummary, TableDetail,
  RowCreate, RowUpdate, RowResponse, RowListResponse, RecordListParams,
  FieldCreate, FieldUpdate, Field, FieldType,
  ViewCreate, View, ViewUpdate,
  WorkspaceTrashResponse, TrashedRow,
  GraphResponse, DependencyResponse,
  CsvAnalyzeResult, CsvImportResult,
  HealthPingResponse, HealthReadyResponse,
  AuditLog, Comment, Reference,
  ImportTaskInfo, TablePermission,
  ReportTemplate, ReportTemplateSummary, ReportTemplateCreate, ReportTemplateUpdate,
  ReportRenderRequest,
  AttachmentFile,
  PreferencesResponse, ActiveViewResponse,
} from './types'

export type {
  ID, UserResponse, LoginRequest, RegisterRequest,
  Workspace, WorkspaceDetail, WorkspaceCreate, WorkspaceUpdate, WorkspaceRole, WorkspaceMember,
  TableSummary, TableDetail, TableCreate, TableUpdate,
  FieldType, Field, FieldCreate, FieldUpdate,
  RowValues, RowResponse, RowDetail, RowCreate, RowUpdate, RowListResponse, RecordListParams,
  View, ViewDetail, ViewCreate, ViewUpdate,
  AuditLog, Comment, Reference,
  TrashedRow, WorkspaceTrashResponse,
  GraphNode, GraphEdge, GraphResponse, DependencyResponse,
  CsvAnalyzeResult, CsvImportResult,
  PublicForm, SharedGrid,
  HealthPingResponse, HealthReadyResponse,
  ReportTemplate, ReportTemplateSummary, ReportTemplateCreate, ReportTemplateUpdate,
  ReportParameter, ReportRenderRequest, ReportRenderResult,
  ImportTaskStatus, ImportTaskInfo, TablePermission,
  NodeTableBrief, WorkflowNode, WorkflowEdge, WorkflowSummary, WorkflowDetail,
  WorkflowCreate, WorkflowUpdate, WorkflowNodeCreate, WorkflowNodeUpdate,
  WorkflowEdgeCreate, WorkflowEdgeUpdate,
  AttachmentFile,
  PreferencesResponse, ActiveViewResponse,
} from './types'

// ─────────────── Auth ───────────────

export const authApi = {
  register: (data: RegisterRequest) =>
    api.post<UserResponse>('/v1/accounts/auth/register', data).then(r => r.data),
  login: (data: LoginRequest) =>
    api.post<{ access_token: string; token_type: string }>('/v1/accounts/auth/login', data).then(r => r.data),
  me: () =>
    api.get<UserResponse>('/v1/accounts/auth/me').then(r => r.data),
}

// ─────────────── User Preferences ───────────────

export const userApi = {
  /** 获取当前用户全部偏好 */
  getPreferences: () =>
    api.get<PreferencesResponse>('/v1/accounts/preferences').then(r => r.data),
  /** 查询某表的激活视图偏好 */
  getTableActiveView: (tid: number | string) =>
    api.get<ActiveViewResponse>(`/v1/accounts/preferences/tables/${tid}/active-view`).then(r => r.data),
  /** 设置或清除某表的激活视图偏好（upsert） */
  setTableActiveView: (tid: number | string, activeViewId: number | null) =>
    api.put<ActiveViewResponse>(`/v1/accounts/preferences/tables/${tid}/active-view`, { active_view_id: activeViewId }).then(r => r.data),
}

// ─────────────── Workspaces ───────────────

export const workspaceApi = {
  list: () => api.get<Array<Workspace & { pinned?: boolean }>>('/v1/workspaces').then(r => r.data),
  create: (data: WorkspaceCreate) =>
    api.post<Workspace>('/v1/workspaces', data).then(r => r.data),
  get: (wid: number | string) =>
    api.get<WorkspaceDetail>(`/v1/workspaces/${wid}`).then(r => r.data),
  update: (wid: number | string, data: WorkspaceUpdate) =>
    api.patch<Workspace>(`/v1/workspaces/${wid}`, data).then(r => r.data),
  remove: (wid: number | string) =>
    api.delete(`/v1/workspaces/${wid}`).then(r => r.data),
  /** 切换 pin 状态（toggle） */
  togglePin: (wid: number | string) =>
    api.post<{ pinned: boolean }>('/v1/workspaces/pin', { workspace_id: wid }).then(r => r.data),
  members: (wid: number | string) =>
    api.get<WorkspaceMember[]>(`/v1/workspaces/${wid}/members`).then(r => r.data),
  /** 搜索可添加的候选用户 */
  memberCandidates: (wid: number | string, search = '') =>
    api.get<{ results: Array<{ id: number; username: string; nickname?: string; email?: string }> }>(
      `/v1/workspaces/${wid}/members/candidates`, { params: { search } },
    ).then(r => r.data),
  addMember: (wid: number | string, username: string, role: string) =>
    api.post<WorkspaceMember>(`/v1/workspaces/${wid}/members`, { username, role }).then(r => r.data),
  updateMemberRole: (wid: number | string, memberId: number | string, role: string) =>
    api.patch<WorkspaceMember>(`/v1/workspaces/${wid}/members/${memberId}`, { role }).then(r => r.data),
  removeMember: (wid: number | string, memberId: number | string) =>
    api.delete(`/v1/workspaces/${wid}/members/${memberId}`).then(r => r.data),
}

// ─────────────── Tables ───────────────

export const tableApi = {
  list: (wid: number | string, includeTrashed = false) =>
    api.get<TableSummary[]>(`/v1/workspaces/${wid}/tables`, { params: { include_trashed: includeTrashed } }).then(r => r.data),
  create: (wid: number | string, data: TableCreate) =>
    api.post<TableDetail>(`/v1/workspaces/${wid}/tables`, data).then(r => r.data),
  get: (wid: number | string, tid: number | string) =>
    api.get<TableDetail>(`/v1/workspaces/${wid}/tables/${tid}`).then(r => r.data),
  update: (wid: number | string, tid: number | string, data: TableUpdate) =>
    api.patch<TableDetail>(`/v1/workspaces/${wid}/tables/${tid}`, data).then(r => r.data),
  remove: (wid: number | string, tid: number | string) =>
    api.delete(`/v1/workspaces/${wid}/tables/${tid}`).then(r => r.data),
  copy: (wid: number | string, tid: number | string, includeData = false) =>
    api.post<TableDetail>(`/v1/workspaces/${wid}/tables/${tid}/copy`, null, { params: { include_data: includeData } }).then(r => r.data),
  move: (wid: number | string, tid: number | string, targetWorkspaceId: number | string) =>
    api.post<TableDetail>(`/v1/workspaces/${wid}/tables/${tid}/move`, null, { params: { target_workspace_id: targetWorkspaceId } }).then(r => r.data),
  reorder: (wid: number | string, tableIds: Array<number | string>) =>
    api.post<TableSummary[]>(`/v1/workspaces/${wid}/tables/reorder`, tableIds).then(r => r.data),
  references: (wid: number | string, tid: number | string, recordId: number | string) =>
    api.get<Reference[]>(`/v1/workspaces/${wid}/tables/${tid}/records/${recordId}/references`).then(r => r.data),
}

// ─────────────── Records ───────────────

export const recordApi = {
  list: (wid: number | string, tid: number | string, params?: RecordListParams) => {
    // GET 端点：filters/sorts 用 JSON 字符串
    const qp: Record<string, unknown> = { offset: params?.offset, limit: params?.limit }
    if (params?.filters) qp.filters = typeof params.filters === 'string' ? params.filters : JSON.stringify(params.filters)
    if (params?.sorts) qp.sorts = typeof params.sorts === 'string' ? params.sorts : JSON.stringify(params.sorts)
    if (params?.filter_logic) qp.filter_logic = params.filter_logic
    return api.get<RowListResponse>(`/v1/workspaces/${wid}/tables/${tid}/records`, { params: qp }).then(r => r.data)
  },
  create: (wid: number | string, tid: number | string, data: RowCreate) =>
    api.post<RowResponse>(`/v1/workspaces/${wid}/tables/${tid}/records`, data).then(r => r.data),
  get: (wid: number | string, tid: number | string, rid: number | string) =>
    api.get<RowResponse>(`/v1/workspaces/${wid}/tables/${tid}/records/${rid}`).then(r => r.data),
  update: (wid: number | string, tid: number | string, rid: number | string, data: RowUpdate) =>
    api.patch<RowResponse>(`/v1/workspaces/${wid}/tables/${tid}/records/${rid}`, data).then(r => r.data),
  remove: (wid: number | string, tid: number | string, rid: number | string, soft = true) =>
    api.delete(`/v1/workspaces/${wid}/tables/${tid}/records/${rid}`, { params: { soft } }).then(r => r.data),
  restore: (wid: number | string, tid: number | string, rid: number | string) =>
    api.post<RowResponse>(`/v1/workspaces/${wid}/tables/${tid}/records/${rid}/restore`).then(r => r.data),
  // 批量
  bulkCreate: (wid: number | string, tid: number | string, rows: Array<Record<string, unknown>>) =>
    api.post<{ created: number; ids: number[] }>(`/v1/workspaces/${wid}/tables/${tid}/records/bulk-create`, { rows }).then(r => r.data),
  bulkDelete: (wid: number | string, tid: number | string, ids: Array<number | string>) =>
    api.post<{ deleted: number }>(`/v1/workspaces/${wid}/tables/${tid}/records/bulk-delete`, { row_ids: ids }).then(r => r.data),
  bulkUpdate: (wid: number | string, tid: number | string, ids: Array<number | string>, values: Record<string, unknown>) =>
    api.post<{ updated: number }>(`/v1/workspaces/${wid}/tables/${tid}/records/bulk-update`, { row_ids: ids, values }).then(r => r.data),
}

// ─────────────── Fields ───────────────

export const fieldApi = {
  list: (wid: number | string, tid: number | string, includeTrashed = false) =>
    api.get<Field[]>(`/v1/workspaces/${wid}/tables/${tid}/fields`, { params: { include_trashed: includeTrashed } }).then(r => r.data),
  create: (wid: number | string, tid: number | string, data: FieldCreate) =>
    api.post<Field>(`/v1/workspaces/${wid}/tables/${tid}/fields`, data).then(r => r.data),
  update: (wid: number | string, tid: number | string, fid: number | string, data: FieldUpdate) =>
    api.patch<Field>(`/v1/workspaces/${wid}/tables/${tid}/fields/${fid}`, data).then(r => r.data),
  remove: (wid: number | string, tid: number | string, fid: number | string) =>
    api.delete(`/v1/workspaces/${wid}/tables/${tid}/fields/${fid}`).then(r => r.data),
}

// ─────────────── Views ───────────────

export const viewApi = {
  list: (wid: number | string, tid: number | string) =>
    api.get<View[]>(`/v1/workspaces/${wid}/tables/${tid}/views`).then(r => r.data),
  get: (wid: number | string, tid: number | string, vid: number | string) =>
    api.get<View>(`/v1/workspaces/${wid}/tables/${tid}/views/${vid}`).then(r => r.data),
  create: (wid: number | string, tid: number | string, data: ViewCreate) =>
    api.post<View>(`/v1/workspaces/${wid}/tables/${tid}/views`, data).then(r => r.data),
  /** 批量导入视图（JSON 数组，同名自动跳过） */
  importViews: (wid: number | string, tid: number | string, data: ViewCreate[]) =>
    api.post<View[]>(`/v1/workspaces/${wid}/tables/${tid}/views/import`, data).then(r => r.data),
  update: (wid: number | string, tid: number | string, vid: number | string, data: ViewUpdate) =>
    api.patch<View>(`/v1/workspaces/${wid}/tables/${tid}/views/${vid}`, data).then(r => r.data),
  remove: (wid: number | string, tid: number | string, vid: number | string) =>
    api.delete(`/v1/workspaces/${wid}/tables/${tid}/views/${vid}`).then(r => r.data),
  /** 按视图的 filters/sorts 查行 */
  rows: (wid: number | string, tid: number | string, vid: number | string, limit = 100, offset = 0) =>
    api.get<{ rows: RowResponse[]; total: number; view_id: number }>(`/v1/workspaces/${wid}/tables/${tid}/views/${vid}/rows`, { params: { limit, offset } }).then(r => r.data),
  /** 看板视图（按 view_options.group_field 分组） */
  kanban: (wid: number | string, tid: number | string, vid: number | string, limit = 500) =>
    api.get<{ columns: Record<string, RowResponse[]>; total: number; group_field: string }>(`/v1/workspaces/${wid}/tables/${tid}/views/${vid}/kanban`, { params: { limit } }).then(r => r.data),
  /** 日历视图 */
  calendar: (wid: number | string, tid: number | string, vid: number | string, start?: string, end?: string, limit = 500) =>
    api.get<{ rows: RowResponse[]; total: number; start_field: string }>(`/v1/workspaces/${wid}/tables/${tid}/views/${vid}/calendar`, { params: { start, end, limit } }).then(r => r.data),
  /** 生成公开分享 */
  share: (wid: number | string, tid: number | string, vid: number | string) =>
    api.post<{ slug: string; share_url: string; form_url: string | null; is_public: boolean }>(`/v1/workspaces/${wid}/tables/${tid}/views/${vid}/share`).then(r => r.data),
  /** 撤销公开分享 */
  revokeShare: (wid: number | string, tid: number | string, vid: number | string) =>
    api.delete<{ ok: boolean; is_public: boolean }>(`/v1/workspaces/${wid}/tables/${tid}/views/${vid}/share`).then(r => r.data),
}

// ─────────────── Comments（行级） ───────────────

export const commentApi = {
  list: (wid: number | string, tid: number | string, rid: number | string) =>
    api.get<Comment[]>(`/v1/workspaces/${wid}/tables/${tid}/records/${rid}/comments`).then(r => r.data),
  create: (wid: number | string, tid: number | string, rid: number | string, content: string, parentId?: number) =>
    api.post<Comment>(`/v1/workspaces/${wid}/tables/${tid}/records/${rid}/comments`, { content, parent_id: parentId }).then(r => r.data),
  update: (wid: number | string, tid: number | string, cid: number | string, content: string) =>
    api.patch<Comment>(`/v1/workspaces/${wid}/tables/${tid}/comments/${cid}`, { content }).then(r => r.data),
  remove: (wid: number | string, tid: number | string, cid: number | string) =>
    api.delete(`/v1/workspaces/${wid}/tables/${tid}/comments/${cid}`).then(r => r.data),
}

// ─────────────── Audit ───────────────

export const auditApi = {
  list: (wid: number | string, tid: number | string, action?: string, limit = 100, rowId?: number | string) =>
    api.get<AuditLog[]>(`/v1/workspaces/${wid}/tables/${tid}/audit`, { params: { action, limit, row_id: rowId } }).then(r => r.data),
}

// ─────────────── Trash ───────────────

export const trashApi = {
  /** 工作区级回收站概览（软删表 + 软删字段 + 各表软删行计数） */
  overview: (wid: number | string) =>
    api.get<WorkspaceTrashResponse>(`/v1/workspaces/${wid}/trash`).then(r => r.data),
  restoreTable: (wid: number | string, tid: number | string) =>
    api.post<{ restored_table_id: number; restored_table_name: string }>(`/v1/workspaces/${wid}/trash/tables/${tid}/restore`).then(r => r.data),
  restoreField: (wid: number | string, fid: number | string) =>
    api.post<{ restored_field_id: number; restored_field_name: string; table_id: number }>(`/v1/workspaces/${wid}/trash/fields/${fid}/restore`).then(r => r.data),
  /** 列出某表的软删行 */
  rows: (wid: number | string, tid: number | string, limit = 500, offset = 0) =>
    api.get<{ rows: TrashedRow[]; total: number }>(`/v1/workspaces/${wid}/tables/${tid}/trash-rows`, { params: { limit, offset } }).then(r => r.data),
  /** 批量恢复软删行；row_ids 为空时恢复全部 */
  restoreRows: (wid: number | string, tid: number | string, rowIds: Array<number | string> = []) =>
    api.post<{ restored: number }>(`/v1/workspaces/${wid}/tables/${tid}/trash-rows/restore`, { row_ids: rowIds }).then(r => r.data),
  /** 硬清理超过 N 天的软删行 */
  purgeRows: (wid: number | string, tid: number | string, days = 30) =>
    api.delete<{ purged: number; older_than_days: number }>(`/v1/workspaces/${wid}/tables/${tid}/trash-rows`, { params: { days } }).then(r => r.data),
}

// ─────────────── Graph ───────────────

export const graphApi = {
  get: (wid: number | string) =>
    api.get<GraphResponse>(`/v1/workspaces/${wid}/graph`).then(r => r.data),
  dependencies: (wid: number | string) =>
    api.get<DependencyResponse>(`/v1/workspaces/${wid}/dependencies`).then(r => r.data),
}

// ─────────────── Import / Export ───────────────

export const importApi = {
  analyzeCsv: (wid: number | string, csvText: string) =>
    api.post<CsvAnalyzeResult>(`/v1/workspaces/${wid}/import-csv/analyze`, { csv_text: csvText }).then(r => r.data),
  createFromCsv: (wid: number | string, tableName: string, csvText: string) =>
    api.post<CsvImportResult>(`/v1/workspaces/${wid}/import-csv`, { table_name: tableName, csv_text: csvText }).then(r => r.data),
  /** 同步导入现有表（文件上传） */
  syncImport: (wid: number | string, tid: number | string, file: File) => {
    const fd = new FormData()
    fd.append('file', file)
    return api.post<{ imported: number; ids: number[] }>(`/v1/workspaces/${wid}/tables/${tid}/import`, fd, {
      headers: { 'Content-Type': 'multipart/form-data' },
    }).then(r => r.data)
  },
  /** 异步导入现有表（文件上传），返回 task_id */
  asyncImport: (wid: number | string, tid: number | string, file: File) => {
    const fd = new FormData()
    fd.append('file', file)
    return api.post<ImportTaskInfo>(`/v1/workspaces/${wid}/tables/${tid}/import/async`, fd, {
      headers: { 'Content-Type': 'multipart/form-data' },
    }).then(r => r.data)
  },
  /** 轮询异步导入任务状态 */
  getTask: (wid: number | string, tid: number | string, taskId: number | string) =>
    api.get<ImportTaskInfo>(`/v1/workspaces/${wid}/tables/${tid}/import/async/${taskId}`).then(r => r.data),
}

export const exportApi = {
  /** 导出为 JSON / CSV / XLSX（浏览器直接下载 blob） */
  download: (wid: number | string, tid: number | string, format: 'json' | 'csv' | 'xlsx' = 'json') =>
    api.get(`/v1/workspaces/${wid}/tables/${tid}/export`, { params: { format }, responseType: 'blob' }).then(r => r.data),
}

// ─────────────── Permissions ───────────────

export const permissionApi = {
  get: (wid: number | string, tid: number | string) =>
    api.get<TablePermission>(`/v1/workspaces/${wid}/tables/${tid}/permissions`).then(r => r.data),
  /** 创建或全量更新 */
  upsert: (wid: number | string, tid: number | string, data: TablePermission) =>
    api.put<TablePermission>(`/v1/workspaces/${wid}/tables/${tid}/permissions`, data).then(r => r.data),
  /** 部分字段更新 */
  patch: (wid: number | string, tid: number | string, data: Partial<TablePermission>) =>
    api.patch<TablePermission>(`/v1/workspaces/${wid}/tables/${tid}/permissions`, data).then(r => r.data),
}

// ─────────────── Public（全局挂载） ───────────────

export const publicApi = {
  /** 匿名只读分享 Grid */
  getShare: (slug: string, limit = 100, offset = 0) =>
    api.get<{
      view: { id: number; name: string; view_type: string; filters: unknown; sortings: unknown }
      table: { id: number; name: string; description: string | null; fields: Array<{ id: number; name: string; field_type: FieldType; config: unknown; required?: boolean; is_unique?: boolean; hidden?: boolean }> }
      rows: RowResponse[]; total: number
    }>(`/v1/public/share/${slug}`, { params: { limit, offset } }).then(r => r.data),
  /** 公开表单元数据（获取表结构渲染表单） */
  getForm: (slug: string) =>
    api.get<{
      view: { id: number; name: string; view_type: string }
      table: { id: number; name: string; description: string | null; fields: Array<{ id: number; name: string; field_type: FieldType; config: unknown; required?: boolean; is_unique?: boolean; hidden?: boolean }> }
    }>(`/v1/public/forms/${slug}`).then(r => r.data),
  /** 匿名提交公开表单行 */
  submitForm: (slug: string, values: Record<string, unknown>) =>
    api.post<{ id: number; status: string }>(`/v1/public/forms/${slug}`, values).then(r => r.data),
}

// ─────────────── Health ───────────────

export const healthApi = {
  ping: () => api.get<HealthPingResponse>('/v1/health/ping').then(r => r.data),
  ready: () => api.get<HealthReadyResponse>('/v1/health/ready').then(r => r.data),
}

// ─────────────── Reports（全局挂载 /api/v1/reports） ───────────────

export const reportApi = {
  /** 列出所有报告模板 */
  list: () => api.get<ReportTemplateSummary[]>('/v1/reports').then(r => r.data),
  /** 获取模板详情（含 template_content） */
  get: (id: number | string) => api.get<ReportTemplate>(`/v1/reports/${id}`).then(r => r.data),
  /** 创建报告模板 */
  create: (data: ReportTemplateCreate) => api.post<ReportTemplate>('/v1/reports', data).then(r => r.data),
  /** 更新报告模板 */
  update: (id: number | string, data: ReportTemplateUpdate) => api.put<ReportTemplate>(`/v1/reports/${id}`, data).then(r => r.data),
  /** 删除报告模板 */
  remove: (id: number | string) => api.delete(`/v1/reports/${id}`).then(r => r.data),
  /** 渲染报告（返回文件二进制） */
  render: (id: number | string, data: ReportRenderRequest) =>
    api.post<Blob>(`/v1/reports/${id}/render`, data, { responseType: 'blob' }).then(r => r.data),
}

// ─────────────── Workflows（挂载到 /api/v1/workspaces/{wid}/workflows） ───────────────

import type {
  WorkflowDetail, WorkflowSummary, WorkflowCreate, WorkflowUpdate,
  WorkflowNodeCreate, WorkflowNodeUpdate, WorkflowEdgeCreate, WorkflowEdgeUpdate,
} from './types'

export const workflowApi = {
  list: (wid: number | string) =>
    api.get<WorkflowSummary[]>(`/v1/workspaces/${wid}/workflows`).then(r => r.data),
  get: (wid: number | string, fwid: number | string) =>
    api.get<WorkflowDetail>(`/v1/workspaces/${wid}/workflows/${fwid}`).then(r => r.data),
  create: (wid: number | string, data: WorkflowCreate) =>
    api.post<WorkflowSummary>(`/v1/workspaces/${wid}/workflows`, data).then(r => r.data),
  update: (wid: number | string, fwid: number | string, data: WorkflowUpdate) =>
    api.patch<WorkflowSummary>(`/v1/workspaces/${wid}/workflows/${fwid}`, data).then(r => r.data),
  remove: (wid: number | string, fwid: number | string) =>
    api.delete(`/v1/workspaces/${wid}/workflows/${fwid}`).then(r => r.data),
  // Node
  addNode: (wid: number | string, fwid: number | string, data: WorkflowNodeCreate) =>
    api.post(`/v1/workspaces/${wid}/workflows/${fwid}/nodes`, data).then(r => r.data),
  updateNode: (wid: number | string, fwid: number | string, nid: number | string, data: WorkflowNodeUpdate) =>
    api.patch(`/v1/workspaces/${wid}/workflows/${fwid}/nodes/${nid}`, data).then(r => r.data),
  removeNode: (wid: number | string, fwid: number | string, nid: number | string) =>
    api.delete(`/v1/workspaces/${wid}/workflows/${fwid}/nodes/${nid}`).then(r => r.data),
  // Edge
  addEdge: (wid: number | string, fwid: number | string, data: WorkflowEdgeCreate) =>
    api.post(`/v1/workspaces/${wid}/workflows/${fwid}/edges`, data).then(r => r.data),
  updateEdge: (wid: number | string, fwid: number | string, eid: number | string, data: WorkflowEdgeUpdate) =>
    api.patch(`/v1/workspaces/${wid}/workflows/${fwid}/edges/${eid}`, data).then(r => r.data),
  removeEdge: (wid: number | string, fwid: number | string, eid: number | string) =>
    api.delete(`/v1/workspaces/${wid}/workflows/${fwid}/edges/${eid}`).then(r => r.data),
}

// ─────────────── Files / Attachments ───────────────

export const fileApi = {
  /** 上传单个附件文件 */
  upload: (wid: number | string, file: File) => {
    const fd = new FormData()
    fd.append('file', file)
    return api.post<AttachmentFile>(`/v1/workspaces/${wid}/files`, fd, {
      headers: { 'Content-Type': 'multipart/form-data' },
    }).then(r => r.data)
  },
  /** 生成附件下载/预览 URL（后端路径 + 查询参数） */
  getUrl: (wid: number | string, fileKey: string, inline = false) =>
    `/api/v1/workspaces/${wid}/files/${encodeURIComponent(fileKey)}${inline ? '?inline=true' : ''}`,
  /** 删除附件（硬清理） */
  remove: (wid: number | string, fileKey: string) =>
    api.delete(`/v1/workspaces/${wid}/files/${encodeURIComponent(fileKey)}`).then(() => true),
}
