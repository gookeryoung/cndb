/** 跨域共享的基础类型（主键、可见性、全局用户角色）. */

export type ID = number | string

export type WorkspaceVisibility = 'public' | 'member' | 'private'

/** 用户角色 —— 三员 + 普通用户（参考 GB/T 22239 等级保护模型） */
export type UserRole = 'system_admin' | 'security_admin' | 'audit_admin' | 'user'
