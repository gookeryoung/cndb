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
 * - /api/v1/workspaces/{wid}/tables/{tid}/audit       → 审计
 * - /api/v1/workspaces/{wid}/tables/{tid}/export|import|import/async  → 导入导出
 * - /api/v1/workspaces/{wid}/import-csv/*             → CSV 自动建表
 * - /api/v1/public/*               → 公开分享（全局挂载）
 * - reports 插件单独挂载（见 reports plugin route_prefix）
 */

import api from './client'
import type {
  AdminRegisterRequest, LoginRequest, RegisterRequest,
  UserResponse,
  WorkspaceCreate, WorkspaceUpdate, Workspace, WorkspaceDetail, WorkspaceMember,
  WorkspaceExportData,
  TableCreate, TableUpdate, TableSummary, TableDetail,
  RowCreate, RowUpdate, RowResponse, RowListResponse, RecordListParams,
  FieldCreate, FieldUpdate, FieldImportRequest, FieldImportResponse, Field, FieldType,
  ViewCreate, View, ViewUpdate,
  CsvAnalyzeResult, CsvImportResult,
  FileAnalyzeResult, FileImportResult,
  AuditLog, Reference,
  ImportTaskInfo, TablePermission,
  ReportTemplate, ReportTemplateSummary, ReportTemplateCreate, ReportTemplateUpdate,
  ReportRenderRequest,
  AttachmentFile,
  PreferencesResponse,
  ApiFetchRequest, ApiAnalyzeResult, ApiImportResult, ApiAppendResult,
  ApiConfigValidateResult, ApiConfigImportResult,
  TableMember, MemberCreate, MemberUpdate, OwnerTransferPayload,
} from './types'

export type {
  ID, UserResponse, AdminRegisterRequest, LoginRequest, RegisterRequest,
  Workspace, WorkspaceDetail, WorkspaceCreate, WorkspaceUpdate, WorkspaceRole, WorkspaceMember, MemberUserBrief,
  WorkspaceVisibility, WorkspaceExportData,
  TableSummary, TableDetail, TableCreate, TableUpdate, ViewBrief,
  FieldImportRequest, FieldImportResponse, FieldImportSuggestion, FieldImportGapAnalysis, FieldType, Field, FieldCreate, FieldUpdate,
  RowValues, RowResponse, RowDetail, RowCreate, RowUpdate, RowListResponse, RecordListParams,
  View, ViewDetail, ViewCreate, ViewUpdate,
  AuditLog, Reference,
  CsvAnalyzeResult, CsvImportResult,
  FileAnalyzeResult, FileImportResult,
  PublicForm, SharedGrid,
  ReportTemplate, ReportTemplateSummary, ReportTemplateCreate, ReportTemplateUpdate,
  ReportParameter, ReportRenderRequest, ReportRenderResult,
  ImportTaskStatus, ImportTaskInfo, TablePermission,
  AttachmentFile,
  PreferencesResponse,
  ApiFetchRequest, ApiAnalyzeColumn, ApiAnalyzeResult, ApiImportResult, ApiAppendResult,
  ApiConfigRequest, ApiConfigValidateResult, ApiConfigImportResult,
  TableOwnerInfo, TableMember, MemberCreate, MemberUpdate, OwnerTransferPayload,
} from './types'

// ─────────────── Auth ───────────────

export const authApi = {
  register: (data: RegisterRequest) =>
    api.post<UserResponse>('/v1/accounts/auth/register', data).then(r => r.data),
  login: (data: LoginRequest) =>
    api.post<{ access_token: string; token_type: string }>('/v1/accounts/auth/login', data).then(r => r.data),
  me: () =>
    api.get<UserResponse>('/v1/accounts/auth/me').then(r => r.data),
  /** 管理员创建用户（需超级管理员 token） */
  adminRegister: (data: AdminRegisterRequest) =>
    api.post<UserResponse>('/v1/accounts/auth/admin-register', data).then(r => r.data),
  /** 列出所有用户（需超级管理员） */
  listUsers: (roleFilter?: string) =>
    api.get<UserResponse[]>('/v1/accounts/auth/users', { params: roleFilter ? { role_filter: roleFilter } : undefined }).then(r => r.data),
  /** 更新指定用户角色（需超级管理员） */
  updateUserRole: (userId: number | string, newRole: string) =>
    api.patch<UserResponse>(`/v1/accounts/auth/users/${userId}/role`, null, { params: { new_role: newRole } }).then(r => r.data),
}

// ─────────────── User Preferences ───────────────

export const userApi = {
  /** 获取当前用户全部偏好 */
  getPreferences: () =>
    api.get<PreferencesResponse>('/v1/accounts/preferences').then(r => r.data),
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
    api.delete(`/v1/workspaces/${wid}/members/${memberId}`).then(() => true),
  /** 转让工作区所有权（仅 owner 可执行） */
  transferOwner: (wid: number | string, userId: number) =>
    api.post<WorkspaceMember>(`/v1/workspaces/${wid}/owner`, { user_id: userId }).then(r => r.data),
  /** 导出整个工作区为 JSON（结构+数据+视图） */
  exportWorkspace: (wid: number | string) =>
    api.get<WorkspaceExportData>(`/v1/workspaces/${wid}/export`).then(r => r.data),
  /** 从 JSON 数据导入工作区（创建新表、字段、数据、视图） */
  importWorkspace: (wid: number | string, jsonData: Record<string, unknown>) =>
    api.post<{ imported_tables: number; imported_rows: number; imported_views: number }>(
      `/v1/workspaces/${wid}/import`,
      { json_data: jsonData },
    ).then(r => r.data),
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
  /** 复制表 — 支持三种模式:
   * - mode='structure'（默认）: 仅复制表结构
   * - mode='all': 复制结构 + 全部数据
   * - mode='view': 复制结构 + 指定视图过滤后的数据（需传 viewId）
   */
  copy: (wid: number | string, tid: number | string, opts?: { mode?: 'structure' | 'all' | 'view'; viewId?: number | string }) => {
    const mode = opts?.mode ?? 'structure'
    const params: Record<string, unknown> = { mode }
    if (opts?.viewId != null) params.view_id = opts.viewId
    return api.post<TableDetail>(`/v1/workspaces/${wid}/tables/${tid}/copy`, null, { params }).then(r => r.data)
  },
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
  /** 从其他表引入字段 schema 到当前表 */
  importFields: (wid: number | string, tid: number | string, data: FieldImportRequest) =>
    api.post<FieldImportResponse>(`/v1/workspaces/${wid}/tables/${tid}/fields/import`, data).then(r => r.data),
  /** 批量调整字段顺序（按传入顺序赋值 order 字段） */
  reorder: (wid: number | string, tid: number | string, fieldIds: Array<number | string>) =>
    api.post<Field[]>(`/v1/workspaces/${wid}/tables/${tid}/fields/reorder`, { field_ids: fieldIds }).then(r => r.data),
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
  /** 批量导出视图（返回 ViewCreate 兼容数组，无内部元数据；不传 ids 导出全部） */
  exportViews: (wid: number | string, tid: number | string, ids?: Array<number | string>) => {
    const params = ids && ids.length ? { ids } : undefined
    return api.get<ViewCreate[]>(`/v1/workspaces/${wid}/tables/${tid}/views/export`, { params }).then(r => r.data)
  },
  update: (wid: number | string, tid: number | string, vid: number | string, data: ViewUpdate) =>
    api.patch<View>(`/v1/workspaces/${wid}/tables/${tid}/views/${vid}`, data).then(r => r.data),
  remove: (wid: number | string, tid: number | string, vid: number | string) =>
    api.delete(`/v1/workspaces/${wid}/tables/${tid}/views/${vid}`).then(r => r.data),
  /** 批量调整视图顺序（按传入顺序赋值 order 字段） */
  reorder: (wid: number | string, tid: number | string, viewIds: Array<number | string>) =>
    api.post<View[]>(`/v1/workspaces/${wid}/tables/${tid}/views/reorder`, viewIds).then(r => r.data),
  /** 按视图的 filters/sorts 查行 */
  rows: (wid: number | string, tid: number | string, vid: number | string, limit = 100, offset = 0) =>
    api.get<{ rows: RowResponse[]; total: number; view_id: number }>(`/v1/workspaces/${wid}/tables/${tid}/views/${vid}/rows`, { params: { limit, offset } }).then(r => r.data),
  /** 看板视图（按 view_options.group_field 分组） */
  kanban: (wid: number | string, tid: number | string, vid: number | string, limit = 500) =>
    api.get<{ columns: Record<string, RowResponse[]>; total: number; group_field: string }>(`/v1/workspaces/${wid}/tables/${tid}/views/${vid}/kanban`, { params: { limit } }).then(r => r.data),
  /** 日历视图 */
  calendar: (wid: number | string, tid: number | string, vid: number | string, start?: string, end?: string, limit = 500) =>
    api.get<{ rows: RowResponse[]; total: number; start_field: string }>(`/v1/workspaces/${wid}/tables/${tid}/views/${vid}/calendar`, { params: { start, end, limit } }).then(r => r.data),
}

// ─────────────── Audit ───────────────

export const auditApi = {
  list: (wid: number | string, tid: number | string, action?: string, limit = 100, rowId?: number | string) =>
    api.get<AuditLog[]>(`/v1/workspaces/${wid}/tables/${tid}/audit`, { params: { action, limit, row_id: rowId } }).then(r => r.data),
}

// ─────────────── Permissions ───────────────

export const importApi = {
  analyzeCsv: (wid: number | string, csvText: string) =>
    api.post<CsvAnalyzeResult>(`/v1/workspaces/${wid}/import-csv/analyze`, { csv_text: csvText }).then(r => r.data),
  createFromCsv: (wid: number | string, tableName: string, csvText: string) =>
    api.post<CsvImportResult>(`/v1/workspaces/${wid}/import-csv`, { table_name: tableName, csv_text: csvText }).then(r => r.data),

  // ── 通用文件导入建表（支持 csv / tsv / json / xlsx） ──
  /** 上传文件 + 分析列类型（不写库） */
  analyzeFile: (wid: number | string, file: File) => {
    const fd = new FormData()
    fd.append('file', file)
    return api.post<FileAnalyzeResult>(`/v1/workspaces/${wid}/import-file/analyze`, fd, {
      headers: { 'Content-Type': 'multipart/form-data' },
    }).then(r => r.data)
  },
  /** 上传文件 + 自动建表 + 导入数据（tableName 留空则用文件名推断；columnOverrides 为可选字段类型覆盖） */
  createFromFile: (wid: number | string, file: File, tableName?: string, columnOverrides?: Record<string, { field_type: string; options?: string[] }>) => {
    const fd = new FormData()
    fd.append('file', file)
    if (tableName) fd.append('table_name', tableName)
    if (columnOverrides) fd.append('column_overrides', JSON.stringify(columnOverrides))
    return api.post<FileImportResult>(`/v1/workspaces/${wid}/import-file`, fd, {
      headers: { 'Content-Type': 'multipart/form-data' },
    }).then(r => r.data)
  },
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

  // ── 预览式导入（两阶段：analyze → confirm） ──
  /** 上传文件仅做解析+校验，返回 task_id（不写库） */
  previewAnalyze: (
    wid: number | string,
    tid: number | string,
    file: File,
    matchKeys?: string[],
    unknownColsStrategy?: 'drop' | 'add_text_field',
    droppedColumns?: string[],
  ) => {
    const fd = new FormData()
    fd.append('file', file)
    if (matchKeys && matchKeys.length > 0) {
      fd.append('match_keys', JSON.stringify(matchKeys))
    }
    if (unknownColsStrategy) {
      fd.append('unknown_cols_strategy', unknownColsStrategy)
    }
    if (droppedColumns && droppedColumns.length > 0) {
      fd.append('dropped_columns', JSON.stringify(droppedColumns))
    }
    return api.post<ImportTaskInfo>(`/v1/workspaces/${wid}/tables/${tid}/import/analyze`, fd, {
      headers: { 'Content-Type': 'multipart/form-data' },
    }).then(r => r.data)
  },
  /** 确认导入：把 pending_confirm 任务推进到 running → done */
  confirmImport: (
    wid: number | string,
    tid: number | string,
    taskId: number | string,
    matchKeys?: string[],
    unknownColsStrategy?: 'drop' | 'add_text_field',
    droppedColumns?: string[],
    cleaningActions?: Array<{ column?: string | null; action: string; strategy?: string; on_fail?: string }>,
  ) =>
    api.post<{ task_id: number; status: string; message: string }>(
      `/v1/workspaces/${wid}/tables/${tid}/import/${taskId}/confirm`,
      // 后端 Body 参数：cleaning_actions 走 JSON body；match_keys / unknown_cols_strategy / dropped_columns 仍走 query params
      cleaningActions && cleaningActions.length > 0 ? { cleaning_actions: cleaningActions } : {},
      {
        params: {
          ...(matchKeys && matchKeys.length > 0 ? { match_keys: JSON.stringify(matchKeys) } : {}),
          ...(unknownColsStrategy ? { unknown_cols_strategy: unknownColsStrategy } : {}),
          ...(droppedColumns && droppedColumns.length > 0 ? { dropped_columns: JSON.stringify(droppedColumns) } : {}),
        },
      }
    ).then(r => r.data),
  /** 重新 analyze — 用户在 preview 阶段改参考列后重算 diff，返回新的 task 状态 */
  reanalyzeImport: (
    wid: number | string,
    tid: number | string,
    taskId: number | string,
    matchKeys?: string[],
    unknownColsStrategy?: 'drop' | 'add_text_field',
  ) =>
    api.post<ImportTaskInfo>(
      `/v1/workspaces/${wid}/tables/${tid}/import/${taskId}/reanalyze`,
      null,
      {
        params: {
          ...(matchKeys && matchKeys.length > 0 ? { match_keys: JSON.stringify(matchKeys) } : {}),
          ...(unknownColsStrategy && unknownColsStrategy !== 'drop' ? { unknown_cols_strategy: unknownColsStrategy } : {}),
        },
      }
    ).then(r => r.data),
  /** 下载失败行文件 */
  downloadFailedRows: async (
    wid: number | string,
    tid: number | string,
    taskId: number | string,
    format: 'csv' | 'xlsx' | 'json' = 'csv',
  ): Promise<Blob> => {
    const resp = await api.get(
      `/v1/workspaces/${wid}/tables/${tid}/import/${taskId}/failed-rows`,
      { params: { format }, responseType: 'blob' }
    )
    return resp.data as unknown as Blob
  },

  // ── API 抓取（import-api 路由） ──
  /** 抓 API + 分析列类型（不写库） */
  fetchAnalyze: (wid: number | string, payload: ApiFetchRequest) =>
    api.post<ApiAnalyzeResult>(`/v1/workspaces/${wid}/import-api/analyze`, payload).then(r => r.data),
  /** 抓 API + 自动建表 + 导入数据 */
  fetchCreateTable: (wid: number | string, tableName: string, payload: ApiFetchRequest) =>
    api.post<ApiImportResult>(`/v1/workspaces/${wid}/import-api`, { ...payload, table_name: tableName }).then(r => r.data),
  /** 抓 API + 追加数据到已有表 */
  fetchAppend: (wid: number | string, tid: number | string, payload: ApiFetchRequest) =>
    api.post<ApiAppendResult>(`/v1/workspaces/${wid}/tables/${tid}/import-api`, payload).then(r => r.data),

  // ── JSON 配置文件批量建表 ──
  /** 校验 JSON 配置文件（不建表） */
  configValidate: (wid: number | string, configJson: string) =>
    api.post<ApiConfigValidateResult>(`/v1/workspaces/${wid}/import-api/config/validate`, { config_json: configJson }).then(r => r.data),
  /** 从 JSON 配置文件批量建表 */
  configImport: (wid: number | string, configJson: string, stopOnError = true) =>
    api.post<ApiConfigImportResult>(`/v1/workspaces/${wid}/import-api/config`, {
      config_json: configJson,
      stop_on_error: stopOnError,
    }).then(r => r.data),
}

export const exportApi = {
  /** 导出为 JSON / CSV / XLSX（浏览器直接下载 blob）
   *  @param wid 工作区 ID
   *  @param tid 表 ID
   *  @param format 导出格式
   *  @param viewId 可选的视图 ID，传入后按该视图的筛选条件导出子集
   */
  download: (wid: number | string, tid: number | string, format: 'json' | 'csv' | 'xlsx' = 'json', viewId?: number | string) => {
    const params: Record<string, unknown> = { format }
    if (viewId != null) params.view_id = viewId
    return api.get(`/v1/workspaces/${wid}/tables/${tid}/export`, { params, responseType: 'blob' }).then(r => r.data)
  },
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

// ─────────────── Table Members & Owner ───────────────

export const tableMembersApi = {
  list: (wid: number | string, tid: number | string) =>
    api.get<TableMember[]>(`/v1/workspaces/${wid}/tables/${tid}/members`).then(r => r.data),
  add: (wid: number | string, tid: number | string, data: MemberCreate) =>
    api.post<TableMember>(`/v1/workspaces/${wid}/tables/${tid}/members`, data).then(r => r.data),
  update: (wid: number | string, tid: number | string, userId: number, data: MemberUpdate) =>
    api.patch<TableMember>(`/v1/workspaces/${wid}/tables/${tid}/members/${userId}`, data).then(r => r.data),
  remove: (wid: number | string, tid: number | string, userId: number) =>
    api.delete(`/v1/workspaces/${wid}/tables/${tid}/members/${userId}`),
  transferOwner: (wid: number | string, tid: number | string, data: OwnerTransferPayload) =>
    api.post(`/v1/workspaces/${wid}/tables/${tid}/owner`, data),
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

// ─────────────── System Admin（系统管理级） ───────────────

export interface AdminSystemInfo {
  app_name: string
  app_version: string
  database_url: string
  upload_dir: string
  data_dir: string
  auth_enabled: boolean
  timezone: string
}

export interface BackupManifest {
  version: string
  app_version: string
  created_at: string
  database: {
    path: string
    db_type: string
    backup_mode: string
    tables: string[]
    row_counts: Record<string, number>
    /** 备份时的 alembic schema 版本（旧版备份可能缺失） */
    schema_version?: string
    /** 内嵌兜底导出的恢复模式（native 备份内嵌 dump.json 时为 "sqlalchemy"） */
    fallback_mode?: string
  }
  uploads: {
    included: boolean
    file_count: number
    total_size: number
  }
  /** inspect 附加判定：备份 schema 版本在本地迁移链上（旧版备份无版本记录时为 true） */
  schema_known?: boolean
  /** inspect 附加判定：备份 schema 新于当前程序，native 恢复将失败 */
  backup_ahead?: boolean
}

export const adminApi = {
  /** 获取系统级信息（版本/数据库路径/数据目录等） */
  info: () => api.get<AdminSystemInfo>('/v1/admin/info').then(r => r.data),

  /** 触发系统级备份，返回可下载的 tar.gz 文件流 */
  backup: (options?: { include_uploads?: boolean; mode?: string }) => {
    return api.post('/v1/admin/backup', {
      format: 'archive',
      include_uploads: options?.include_uploads ?? true,
      mode: options?.mode ?? 'auto',
    }, { responseType: 'blob' }).then(r => r.data as Blob)
  },

  /** dry-run 检查备份文件（上传 tar.gz），返回 manifest 元信息 */
  restoreInspect: (file: File) => {
    const fd = new FormData()
    fd.append('file', file)
    return api.post<BackupManifest>('/v1/admin/restore/inspect', fd, {
      headers: { 'Content-Type': 'multipart/form-data' },
    }).then(r => r.data)
  },

  /** 执行系统级恢复（破坏性操作）。mode 覆盖恢复模式：备份 schema 新于当前程序时可传 "sqlalchemy" 降级恢复 */
  restore: (file: File, force = true, mode?: string) => {
    const fd = new FormData()
    fd.append('file', file)
    fd.append('force', String(force))
    if (mode) fd.append('mode', mode)
    return api.post<{ status: string; message: string; loss_report: { summary: string; skipped_tables: string[]; dropped_columns: Record<string, string[]> } | null }>(
      '/v1/admin/restore',
      fd,
      { headers: { 'Content-Type': 'multipart/form-data' } },
    ).then(r => r.data)
  },
}
