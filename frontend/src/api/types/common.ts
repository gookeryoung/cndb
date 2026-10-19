/** 跨域共享的基础类型（主键、可见性、全局用户角色）. */

export type ID = number | string

export type WorkspaceVisibility = 'public' | 'member' | 'private'

/** 工作区类型 —— 决定工作区提供哪些功能模块（data_doc 为默认） */
export type WorkspaceType = 'data_doc' | 'data' | 'doc'

/** 用户角色 —— 三员 + 普通用户（参考 GB/T 22239 等级保护模型） */
export type UserRole = 'system_admin' | 'security_admin' | 'audit_admin' | 'user'
