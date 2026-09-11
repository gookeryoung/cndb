import api from './client'
import type {
  LoginRequest, RegisterRequest,
  UserResponse, ApiTokenCreate, ApiToken,
  WorkspaceCreate, WorkspaceUpdate, Workspace, WorkspaceDetail, WorkspaceMember, WorkspaceInvite,
  TableCreate, TableUpdate, TableSummary, TableDetail,
  RowCreate, RowUpdate, RowResponse, RowListResponse, RecordListParams,
  FieldCreate, FieldUpdate, Field,
  ViewCreate, View,
  WorkspaceTrashResponse, TrashedRow,
  GraphResponse, DependencyResponse,
  CsvAnalyzeResult, CsvImportResult,
  PublicForm, SharedGrid,
  HealthPingResponse, HealthReadyResponse,
  AuditLog, Comment, Reference,
} from './types'

export type {
  ID, UserResponse, LoginRequest, RegisterRequest,
  ApiToken, ApiTokenCreate,
  Workspace, WorkspaceDetail, WorkspaceCreate, WorkspaceUpdate, WorkspaceRole, WorkspaceMember, WorkspaceInvite,
  TableSummary, TableDetail, TableCreate, TableUpdate,
  FieldType, Field, FieldCreate, FieldUpdate,
  RowValues, RowResponse, RowDetail, RowCreate, RowUpdate, RowListResponse, RecordListParams,
  View, ViewDetail, ViewCreate,
  AuditLog, Comment, Reference,
  TrashedRow, WorkspaceTrashResponse,
  GraphNode, GraphEdge, GraphResponse, DependencyResponse,
  CsvAnalyzeResult, CsvImportResult,
  PublicForm, SharedGrid,
  HealthPingResponse, HealthReadyResponse,
  ReportInfo,
} from './types'

export const authApi = {
  register: (data: RegisterRequest) =>
    api.post<UserResponse>('/v1/accounts/auth/register', data).then(r => r.data),
  login: (data: LoginRequest) =>
    api.post<{ access_token: string; token_type: string }>('/v1/accounts/auth/login', data).then(r => r.data),
  me: () =>
    api.get<UserResponse>('/v1/accounts/auth/me').then(r => r.data),
}

export const tokenApi = {
  list: () => api.get<ApiToken[]>('/v1/accounts/tokens').then(r => r.data),
  create: (data: ApiTokenCreate) =>
    api.post<ApiToken>('/v1/accounts/tokens', data).then(r => r.data),
  remove: (tid: number | string) =>
    api.delete(`/v1/accounts/tokens/${tid}`).then(r => r.data),
}

export const workspaceApi = {
  list: () => api.get<Workspace[]>('/v1/workspaces').then(r => r.data),
  create: (data: WorkspaceCreate) =>
    api.post<Workspace>('/v1/workspaces', data).then(r => r.data),
  get: (wid: number | string) =>
    api.get<WorkspaceDetail>(`/v1/workspaces/${wid}`).then(r => r.data),
  update: (wid: number | string, data: WorkspaceUpdate) =>
    api.put<Workspace>(`/v1/workspaces/${wid}`, data).then(r => r.data),
  remove: (wid: number | string) =>
    api.delete(`/v1/workspaces/${wid}`).then(r => r.data),
  pin: (wid: number | string) => api.post(`/v1/workspaces/${wid}/pin`).then(r => r.data),
  unpin: (wid: number | string) => api.post(`/v1/workspaces/${wid}/unpin`).then(r => r.data),
  members: (wid: number | string) =>
    api.get<WorkspaceMember[]>(`/v1/workspaces/${wid}/members`).then(r => r.data),
  invite: (wid: number | string, data: WorkspaceInvite) =>
    api.post(`/v1/workspaces/${wid}/invite`, data).then(r => r.data),
  setRole: (wid: number | string, uid: number | string, role: string) =>
    api.put(`/v1/workspaces/${wid}/members/${uid}/role`, { role }).then(r => r.data),
  kick: (wid: number | string, uid: number | string) =>
    api.delete(`/v1/workspaces/${wid}/members/${uid}`).then(r => r.data),
}

export const tableApi = {
  list: (wid: number | string) =>
    api.get<TableSummary[]>(`/v1/workspaces/${wid}/tables`).then(r => r.data),
  create: (wid: number | string, data: TableCreate) =>
    api.post<TableDetail>(`/v1/workspaces/${wid}/tables`, data).then(r => r.data),
  get: (wid: number | string, tid: number | string) =>
    api.get<TableDetail>(`/v1/workspaces/${wid}/tables/${tid}`).then(r => r.data),
  update: (wid: number | string, tid: number | string, data: TableUpdate) =>
    api.put<TableDetail>(`/v1/workspaces/${wid}/tables/${tid}`, data).then(r => r.data),
  remove: (wid: number | string, tid: number | string) =>
    api.delete(`/v1/workspaces/${wid}/tables/${tid}`).then(r => r.data),
  copy: (wid: number | string, tid: number | string) =>
    api.post<TableDetail>(`/v1/workspaces/${wid}/tables/${tid}/copy`).then(r => r.data),
}

export const recordApi = {
  list: (wid: number | string, tid: number | string, params?: RecordListParams) =>
    api.get<RowListResponse>(`/v1/workspaces/${wid}/tables/${tid}/records`, { params }).then(r => r.data),
  create: (wid: number | string, tid: number | string, data: RowCreate) =>
    api.post<RowResponse>(`/v1/workspaces/${wid}/tables/${tid}/records`, data).then(r => r.data),
  get: (wid: number | string, tid: number | string, rid: number | string) =>
    api.get<RowResponse>(`/v1/workspaces/${wid}/tables/${tid}/records/${rid}`).then(r => r.data),
  update: (wid: number | string, tid: number | string, rid: number | string, data: RowUpdate) =>
    api.put<RowResponse>(`/v1/workspaces/${wid}/tables/${tid}/records/${rid}`, data).then(r => r.data),
  remove: (wid: number | string, tid: number | string, rid: number | string) =>
    api.delete(`/v1/workspaces/${wid}/tables/${tid}/records/${rid}`).then(r => r.data),
  bulkCreate: (wid: number | string, tid: number | string, rows: RowCreate[]) =>
    api.post<Array<number | string>>(`/v1/workspaces/${wid}/tables/${tid}/bulk/create`, { rows }).then(r => r.data),
  bulkUpdate: (wid: number | string, tid: number | string, ids: Array<number | string>, values: Record<string, unknown>) =>
    api.post(`/v1/workspaces/${wid}/tables/${tid}/bulk/update`, { ids, values }).then(r => r.data),
  bulkDelete: (wid: number | string, tid: number | string, ids: Array<number | string>) =>
    api.post(`/v1/workspaces/${wid}/tables/${tid}/bulk/delete`, { ids }).then(r => r.data),
  audit: (wid: number | string, tid: number | string, params?: { offset?: number; limit?: number }) =>
    api.get<AuditLog[]>(`/v1/workspaces/${wid}/tables/${tid}/audit`, { params }).then(r => r.data),
  comments: (wid: number | string, tid: number | string) =>
    api.get<Comment[]>(`/v1/workspaces/${wid}/tables/${tid}/comments`).then(r => r.data),
  addComment: (wid: number | string, tid: number | string, content: string) =>
    api.post<Comment>(`/v1/workspaces/${wid}/tables/${tid}/comments`, { content }).then(r => r.data),
  references: (wid: number | string, tid: number | string, rowId: number | string) =>
    api.get<Reference[]>(`/v1/workspaces/${wid}/tables/${tid}/references`, { params: { row_id: rowId } }).then(r => r.data),
}

export const fieldApi = {
  list: (wid: number | string, tid: number | string) =>
    api.get<Field[]>(`/v1/workspaces/${wid}/tables/${tid}/fields`).then(r => r.data),
  create: (wid: number | string, tid: number | string, data: FieldCreate) =>
    api.post<Field>(`/v1/workspaces/${wid}/tables/${tid}/fields`, data).then(r => r.data),
  update: (wid: number | string, tid: number | string, fid: number | string, data: FieldUpdate) =>
    api.put<Field>(`/v1/workspaces/${wid}/tables/${tid}/fields/${fid}`, data).then(r => r.data),
  remove: (wid: number | string, tid: number | string, fid: number | string) =>
    api.delete(`/v1/workspaces/${wid}/tables/${tid}/fields/${fid}`).then(r => r.data),
}

export const viewApi = {
  list: (wid: number | string, tid: number | string) =>
    api.get<View[]>(`/v1/workspaces/${wid}/tables/${tid}/views`).then(r => r.data),
  create: (wid: number | string, tid: number | string, data: ViewCreate) =>
    api.post<View>(`/v1/workspaces/${wid}/tables/${tid}/views`, data).then(r => r.data),
  get: (wid: number | string, tid: number | string, vid: number | string) =>
    api.get<View>(`/v1/workspaces/${wid}/tables/${tid}/views/${vid}`).then(r => r.data),
}

export const trashApi = {
  list: (wid: number | string) =>
    api.get<WorkspaceTrashResponse>(`/v1/workspaces/${wid}/tables/trash`).then(r => r.data),
  restoreTable: (wid: number | string, tid: number | string) =>
    api.post(`/v1/workspaces/${wid}/tables/trash/tables/${tid}/restore`).then(r => r.data),
  restoreField: (wid: number | string, fid: number | string) =>
    api.post(`/v1/workspaces/${wid}/tables/trash/fields/${fid}/restore`).then(r => r.data),
  trashRows: (wid: number | string, tid: number | string) =>
    api.get<TrashedRow[]>(`/v1/workspaces/${wid}/tables/${tid}/trash-rows`).then(r => r.data),
  restoreRow: (wid: number | string, tid: number | string, rid: number | string) =>
    api.post(`/v1/workspaces/${wid}/tables/${tid}/trash-rows/${rid}/restore`).then(r => r.data),
  purge: (wid: number | string, tid: number | string, days?: number) =>
    api.post(`/v1/workspaces/${wid}/tables/${tid}/trash-rows/purge`, null, { params: { days } }).then(r => r.data),
}

export const graphApi = {
  get: (wid: number | string) =>
    api.get<GraphResponse>(`/v1/workspaces/${wid}/graph`).then(r => r.data),
  dependencies: (wid: number | string) =>
    api.get<DependencyResponse>(`/v1/workspaces/${wid}/dependencies`).then(r => r.data),
}

export const importApi = {
  analyze: (wid: number | string, csvText: string) =>
    api.post<CsvAnalyzeResult>(`/v1/workspaces/${wid}/tables/import-csv/analyze`, { csv_text: csvText }).then(r => r.data),
  create: (wid: number | string, tableName: string, csvText: string) =>
    api.post<CsvImportResult>(`/v1/workspaces/${wid}/tables/import-csv`, { table_name: tableName, csv_text: csvText }).then(r => r.data),
}

export const publicApi = {
  getForm: (slug: string) =>
    api.get<PublicForm>(`/v1/public/form/${slug}`).then(r => r.data),
  submitForm: (slug: string, values: Record<string, unknown>) =>
    api.post(`/v1/public/form/${slug}`, { values }).then(r => r.data),
  getShare: (slug: string) =>
    api.get<SharedGrid>(`/v1/public/share/${slug}`).then(r => r.data),
}

export const healthApi = {
  ping: () => api.get<HealthPingResponse>('/v1/health/ping').then(r => r.data),
  ready: () => api.get<HealthReadyResponse>('/v1/health/ready').then(r => r.data),
}
