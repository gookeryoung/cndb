/** API 客户端统一出口 — 按资源域拆分实现，此处聚合 re-export，调用方 import 不变.
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

export { authApi, userApi } from './auth'
export { workspaceApi } from './workspaces'
export { tableApi, fieldApi, auditApi, permissionApi, tableMembersApi } from './tables'
export { recordApi } from './records'
export { viewApi } from './views'
export { importApi, exportApi, fileApi } from './importExport'
export { publicApi } from './public'
export { reportApi } from './reports'
export { adminApi } from './admin'
export type { AdminSystemInfo, BackupManifest } from './admin'

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
  ReportParameter, ReportRenderRequest, ReportRenderResult, ReportTheme,
  ImportTaskStatus, ImportTaskInfo, TablePermission,
  AttachmentFile,
  PreferencesResponse,
  ApiFetchRequest, ApiAnalyzeColumn, ApiAnalyzeResult, ApiImportResult, ApiAppendResult,
  ApiConfigRequest, ApiConfigValidateResult, ApiConfigImportResult,
  TableOwnerInfo, TableMember, MemberCreate, MemberUpdate, OwnerTransferPayload,
} from './types'
