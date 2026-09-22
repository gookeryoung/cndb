/** 认证与用户偏好 API — /api/v1/accounts/auth/* 与 /api/v1/accounts/preferences */

import api from './client'
import type {
    AdminRegisterRequest, LoginRequest, RegisterRequest,
    UserResponse,
    PreferencesResponse,
} from './types'

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

export const userApi = {
    /** 获取当前用户全部偏好 */
    getPreferences: () =>
        api.get<PreferencesResponse>('/v1/accounts/preferences').then(r => r.data),
}
