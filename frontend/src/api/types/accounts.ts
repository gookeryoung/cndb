/** 账号 / 认证 / 用户管理 / 操作日志. */

import type { ID, UserRole } from './common'

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

/** 管理员视角用户记录（对齐后端 UserAdminResponse，含 phone/创建时间） */
export interface UserAdminRecord {
  id: ID
  username: string
  email: string | null
  phone: string | null
  nickname: string
  role: UserRole
  is_active: boolean
  is_superuser: boolean
  created_at?: string | null
}

/** 用户分页列表响应（对齐后端 UserListPage） */
export interface UserListPage { total: number; items: UserAdminRecord[] }

/** 管理员编辑用户请求体 —— 仅提交字段生效（对齐后端 UserAdminUpdateRequest） */
export interface UserAdminUpdateRequest {
  username?: string
  email?: string
  phone?: string
  nickname?: string
  role?: UserRole
  is_active?: boolean
}

/** 批量操作请求体（对齐后端 BatchUserActionRequest） */
export interface BatchUserActionRequest {
  action: 'activate' | 'deactivate' | 'set_role'
  user_ids: number[]
  role?: UserRole
}

/** 批量操作单项结果（对齐后端 BatchUserItemResult） */
export interface BatchUserItemResult {
  user_id: number
  username: string
  success: boolean
  error?: string | null
}

/** 批量操作汇总响应（对齐后端 BatchUserActionResponse） */
export interface BatchUserActionResponse {
  total: number
  succeeded: number
  failed: number
  results: BatchUserItemResult[]
}

/** 用户管理操作日志条目（对齐后端 UserAuditLogResponse） */
export interface UserAuditLogRecord {
  id: number
  action: 'update' | 'role_change' | 'activate' | 'deactivate' | 'batch' | 'import' | 'export' | string
  actor_id: number | null
  target_user_id: number | null
  detail: Record<string, unknown>
  created_at?: string | null
}

/** 操作日志分页响应（对齐后端 UserAuditLogPage） */
export interface UserAuditLogPage { total: number; items: UserAuditLogRecord[] }

/** 用户管理操作日志查询参数 */
export interface UserAuditLogQuery {
  action?: string
  actor_id?: number
  target_user_id?: number
  page?: number
  page_size?: number
}

/** 用户分页列表查询参数 */
export interface UserListQuery {
  keyword?: string
  role?: UserRole
  is_active?: boolean
  page?: number
  page_size?: number
}

/** 批量导入单项结果（对齐后端 UserImportRowResult） */
export interface UserImportRowResult {
  row_index: number
  status: 'ok' | 'skipped' | 'failed'
  message: string
  user_id: number | null
  username: string | null
  /** 自动生成的初始密码：仅创建成功时随本次响应返回一次 */
  generated_password: string | null
}

/** 批量导入汇总响应（对齐后端 UserImportResponse） */
export interface UserImportResponse {
  total: number
  created: number
  skipped: number
  failed: number
  /** true = 预演校验，未写库；此时 created 表示可导入数量 */
  dry_run: boolean
  results: UserImportRowResult[]
}

export interface LoginRequest { login: string; password: string }
/** 登录 / 刷新令牌响应 —— refresh_token 为不透明随机串（服务端只存哈希，可吊销）. */
export interface TokenResponse {
  access_token: string
  token_type: string
  refresh_token?: string | null
  expires_in?: number | null
}
/** 会话（刷新令牌）公开信息 —— 对应后端 SessionOut. */
export interface SessionInfo {
  id: number
  created_at: string
  expires_at: string
  revoked_reason?: string | null
}
/** 当前用户自助更新个人资料请求体 —— 仅提交的字段会被更新，邮箱传空串表示清空. */
export interface ProfileUpdateRequest { nickname?: string; email?: string }
/** 公开注册请求体 —— 已收窄为仅普通用户，不接受 role 参数. */
export interface RegisterRequest { username: string; email?: string | null; password: string; nickname?: string }
/** 管理员创建用户请求体 —— role 必填（三员 + user 任意）. */
export interface AdminRegisterRequest extends Omit<RegisterRequest, 'password'> { password: string; role: UserRole }
/** 当前用户偏好（对齐后端 PreferencesResponse，ADR 0021） */
export interface UserPreferences {
  /** 每张表的激活视图映射: table_id -> view_id */
  active_views: Record<string, number>
  /** 主页工作区的自定义顺序（同组内生效） */
  workspace_order: number[]
  /** 收藏视图 id，顺序即「我的视图」展示顺序 */
  favorite_view_ids: number[]
}

/** 「我的视图」面板行摘要（对齐后端 FavoriteViewSummary） */
export interface FavoriteViewSummary {
  view_id: number
  name: string
  view_type: string
  is_default: boolean
  visibility: 'table' | 'shared' | 'private' | string
  filter_count: number
  sort_count: number
  table_id: number
  table_name: string
  workspace_id: number
  workspace_name: string
  updated_at: string | null
}
