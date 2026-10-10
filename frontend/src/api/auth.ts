/** 认证与用户管理 API — /api/v1/accounts/auth/* 与 /api/v1/accounts/users/* */

import api from './client'
import type {
    AdminRegisterRequest, LoginRequest, RegisterRequest,
    ProfileUpdateRequest,
    UserResponse,
    UserAdminRecord, UserAdminUpdateRequest, UserListPage, UserListQuery,
    BatchUserActionRequest, BatchUserActionResponse,
    UserAuditLogPage, UserAuditLogQuery,
} from './types'

export const authApi = {
    register: (data: RegisterRequest) =>
        api.post<UserResponse>('/v1/accounts/auth/register', data).then(r => r.data),
    login: (data: LoginRequest) =>
        api.post<{ access_token: string; token_type: string }>('/v1/accounts/auth/login', data).then(r => r.data),
    me: () =>
        api.get<UserResponse>('/v1/accounts/auth/me').then(r => r.data),
    /** 当前用户自助更新个人资料（昵称/邮箱） */
    updateProfile: (data: ProfileUpdateRequest) =>
        api.patch<UserResponse>('/v1/accounts/auth/me', data).then(r => r.data),
    /** 管理员创建用户（需超级管理员 token） */
    adminRegister: (data: AdminRegisterRequest) =>
        api.post<UserResponse>('/v1/accounts/auth/admin-register', data).then(r => r.data),
    // ── 用户管理（/v1/accounts/users/*，需超级管理员；日志查询审计管理员亦可） ──
    /** 用户分页列表（关键词/角色/状态筛选） */
    listUsers: (params: UserListQuery = {}) =>
        api.get<UserListPage>('/v1/accounts/users', { params }).then(r => r.data),
    /** 编辑用户（用户名/邮箱/电话/昵称/角色/状态），变更记录操作日志 */
    editUser: (userId: number | string, data: UserAdminUpdateRequest) =>
        api.patch<UserAdminRecord>(`/v1/accounts/users/${userId}`, data).then(r => r.data),
    /** 批量启用/禁用/设置角色，返回逐项结果 */
    batchUsers: (data: BatchUserActionRequest) =>
        api.post<BatchUserActionResponse>('/v1/accounts/users/batch', data).then(r => r.data),
    /** 用户管理操作日志（全量，支持按动作/操作人/目标筛选） */
    listAuditLogs: (params: UserAuditLogQuery = {}) =>
        api.get<UserAuditLogPage>('/v1/accounts/users/audit-logs', { params }).then(r => r.data),
    /** 指定用户的操作日志 */
    listUserAuditLogs: (userId: number | string, params: Omit<UserAuditLogQuery, 'target_user_id' | 'actor_id' | 'action'> = {}) =>
        api.get<UserAuditLogPage>(`/v1/accounts/users/${userId}/audit-logs`, { params }).then(r => r.data),
}

