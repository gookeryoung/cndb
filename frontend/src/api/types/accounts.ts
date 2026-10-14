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
  action: 'update' | 'role_change' | 'activate' | 'deactivate' | 'batch' | string
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

export interface LoginRequest { login: string; password: string }
/** 当前用户自助更新个人资料请求体 —— 仅提交的字段会被更新，邮箱传空串表示清空. */
export interface ProfileUpdateRequest { nickname?: string; email?: string }
/** 公开注册请求体 —— 已收窄为仅普通用户，不接受 role 参数. */
export interface RegisterRequest { username: string; email?: string | null; password: string; nickname?: string }
/** 管理员创建用户请求体 —— role 必填（三员 + user 任意）. */
export interface AdminRegisterRequest extends Omit<RegisterRequest, 'password'> { password: string; role: UserRole }
