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
 */

export { authApi } from './auth'
export { workspaceApi } from './workspaces'
export { preferencesApi } from './preferences'
export { tableApi, fieldApi, auditApi, permissionApi, tableMembersApi, rowPermissionApi } from './tables'
export { recordApi } from './records'
export { viewApi } from './views'
export { importApi, exportApi, fileApi } from './importExport'
export { issuesApi } from './issues'
export { changeRequestsApi } from './changeRequests'
export { adminApi } from './admin'
export type {
  AdminSystemInfo,
  BackupManifest,
  CoreEventActionStat,
  CoreEventItem,
  CoreEventPage,
  CoreEventQuery,
  WorkspaceStorageItem,
  WorkspaceStorageOverview,
} from './admin'
export { systemApi } from './system'
export type { SystemAbout } from './system'
export { helpApi } from './help'
export type { HelpExample, HelpExampleList, HelpExampleTable } from './help'
export { datasourceApi } from './datasource'
export type {
  DatasourceProviderInfo,
  DatasourceSession,
  DatasourceSessionPayload,
  DomainTemplate,
  ProviderField,
  SyncCursorConfig,
  SyncCursorStrategy,
  SyncFieldMapping,
  SyncJob,
  SyncJobPayload,
  SyncLlmConfig,
  SyncPreviewResult,
  SyncPromptConfig,
  SyncRequestSpec,
  SyncRun,
  SyncRunStatus,
  SyncScheduleConfig,
  SyncScheduleMode,
} from './datasource'
export { llmApi } from './llm'
export type {
  LlmAction,
  LlmConfig,
  LlmConfigPayload,
  LlmConnectionTestPayload,
  LlmConnectionTestResult,
  LlmRun,
  LlmRunPage,
  LlmRunQuery,
} from './llm'
export { governanceApi } from './governance'
export type { DetectReport, MergeReport, CleanReport, GovernanceReport } from './governance'
export { searchApi } from './search'
export type {
  WorkspaceSearchParams,
  WorkspaceSearchResult,
  SearchScope,
  SearchDocumentHit,
  SearchTableHit,
  SearchRowHit,
  SearchViewScope,
} from './search'

// 领域类型统一从 types/ 聚合转发（types/index.ts 按资源域拆分并 re-export）；
// 原先是逐个具名列出的 90 个类型清单，新增类型时容易漏改。
export type * from './types'

// 类型守卫为运行时函数，须以值形式 re-export（export type * 会在编译期擦除）
export { isChangeRequestResponse } from './types'
