/** 认证与用户管理 API — /api/v1/accounts/auth/* 与 /api/v1/accounts/users/* */

import api from './client'
import type {
    AdminRegisterRequest, LoginRequest, RegisterRequest,
    ProfileUpdateRequest,
    SessionInfo, TokenResponse,
    UserResponse,
    UserAdminRecord, UserAdminUpdateRequest, UserListPage, UserListQuery,
    BatchUserActionRequest, BatchUserActionResponse,
    UserAuditLogPage, UserAuditLogQuery,
    UserImportResponse,
} from './types'

export const authApi = {
    register: (data: RegisterRequest) =>
        api.post<UserResponse>('/v1/accounts/auth/register', data).then(r => r.data),
    login: (data: LoginRequest) =>
        api.post<TokenResponse>('/v1/accounts/auth/login', data).then(r => r.data),
    me: () =>
        api.get<UserResponse>('/v1/accounts/auth/me').then(r => r.data),
    /** 用刷新令牌换取新令牌对（一次性轮换，旧刷新令牌立即失效） */
    refresh: (refreshToken: string) =>
        api.post<TokenResponse>('/v1/accounts/auth/refresh', { refresh_token: refreshToken }).then(r => r.data),
    /** 登出：吊销单枚刷新令牌；all=true 时吊销全部会话（需已登录） */
    logout: (refreshToken?: string | null, all = false) =>
        api.post<{ revoked: number; scope?: string }>('/v1/accounts/auth/logout', {
            ...(refreshToken ? { refresh_token: refreshToken } : {}),
            ...(all ? { all: true } : {}),
        }).then(r => r.data),
    /** 修改自己的密码（成功后全部设备需重新登录） */
    changePassword: (data: { current_password: string; new_password: string }) =>
        api.post<{ ok: boolean; revoked_sessions: number }>('/v1/accounts/auth/password', data).then(r => r.data),
    /** 当前用户的有效会话列表 */
    listSessions: () =>
        api.get<SessionInfo[]>('/v1/accounts/auth/sessions').then(r => r.data),
    /** 下线指定会话（仅限本人） */
    revokeSession: (sessionId: number) =>
        api.delete<{ ok: boolean }>(`/v1/accounts/auth/sessions/${sessionId}`).then(r => r.data),
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
    /** 按当前筛选条件导出用户列表（CSV / XLSX，不含密码）；返回完整响应以便解析下载文件名 */
    exportUsers: (params: UserListQuery & { format: 'csv' | 'xlsx' }) =>
        api.get('/v1/accounts/users/export', { params, responseType: 'blob' }),
    /** 批量导入用户（dryRun=true 仅预演校验）；multipart 需显式声明，拦截器会补 boundary */
    importUsers: (file: File, dryRun = false) => {
        const form = new FormData()
        form.append('file', file)
        form.append('dry_run', String(dryRun))
        return api
            .post<UserImportResponse>('/v1/accounts/users/import', form, {
                headers: { 'Content-Type': 'multipart/form-data' },
            })
            .then(r => r.data)
    },
    /** 用户管理操作日志（全量，支持按动作/操作人/目标筛选） */
    listAuditLogs: (params: UserAuditLogQuery = {}) =>
        api.get<UserAuditLogPage>('/v1/accounts/users/audit-logs', { params }).then(r => r.data),
    /** 指定用户的操作日志 */
    listUserAuditLogs: (userId: number | string, params: Omit<UserAuditLogQuery, 'target_user_id' | 'actor_id' | 'action'> = {}) =>
        api.get<UserAuditLogPage>(`/v1/accounts/users/${userId}/audit-logs`, { params }).then(r => r.data),
}
