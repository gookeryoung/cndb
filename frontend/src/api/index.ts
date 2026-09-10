import api from './client'

// ============================================================
// 类型定义（与后端 Pydantic Schema 一一对应）
// ============================================================

/** 框架健康检查响应（GET /api/health） */
export interface HealthResponse {
  status: string
  version: string
  app: string
}

/** 插件元信息（来自 /api/plugins） */
export interface PluginInfo {
  name: string
  version: string
  description: string
  icon: string
}

/** 侧边栏导航项（后端 NavItem DTO） */
export interface NavItem {
  key: string
  label: string
  icon: string
  path: string
  children?: NavItem[]
}

/** APP 功能模块入口（应用中心 / Header 应用下拉共用） */
export interface AppItem {
  key: string
  label: string
  description: string
  icon: string
  path: string
  /** 分类：tool=实用工具 / analysis=分析工具 / integration=集成对接 */
  category: string
}

/** 健康检查插件 ping 响应（GET /api/v1/health/ping） */
export interface HealthPingResponse {
  status: string
  timestamp: string
  python: string
  platform: string
}

/** CRUD Demo 用户实体 */
export interface User {
  id: number
  username: string
  email: string
  role: string
  created_at: string
  updated_at: string
}

/** 用户列表分页响应 */
export interface UserListResponse {
  items: User[]
  total: number
  offset: number
  limit: number
}

/** 创建用户请求体 */
export interface UserCreatePayload {
  username: string
  email: string
  role?: string
}

/** 更新用户请求体（所有字段可选） */
export interface UserUpdatePayload {
  username?: string
  email?: string
  role?: string
}

// ============================================================
// 系统级 API（框架元路由）
// ============================================================

export const systemApi = {
  /** 框架健康检查 */
  health: () => api.get<HealthResponse>('/health'),
  /** 已加载插件列表 */
  plugins: () => api.get<{ plugins: PluginInfo[] }>('/plugins'),
  /** 汇总所有插件注册的侧边栏导航项 */
  navigation: () => api.get<{ navigation: NavItem[] }>('/navigation'),
  /** 汇总所有插件注册的 APP 功能模块入口（应用中心 + Header 应用下拉共用） */
  apps: () => api.get<AppItem[]>('/apps'),
  /** 内置 demo 端点清单 */
  demos: () => api.get('/demos'),
}

// ============================================================
// Health 插件 API（/api/v1/health）
// ============================================================

export const healthApi = {
  /** 存活探针（带运行环境信息） */
  ping: () => api.get<HealthPingResponse>('/v1/health/ping'),
  /** 就绪探针 */
  ready: () => api.get<{ status: string }>('/v1/health/ready'),
}

// ============================================================
// CRUD Demo 插件 API（/api/v1/crud-demo）
// ============================================================

export const crudApi = {
  /** 分页查询用户列表 */
  listUsers: (params?: { offset?: number; limit?: number }) =>
    api.get<UserListResponse>('/v1/crud-demo/users', { params }),

  /** 按 ID 查询单个用户 */
  getUser: (id: number) => api.get<User>(`/v1/crud-demo/users/${id}`),

  /** 创建用户 */
  createUser: (data: UserCreatePayload) =>
    api.post<User>('/v1/crud-demo/users', data),

  /** 更新用户 */
  updateUser: (id: number, data: UserUpdatePayload) =>
    api.put<User>(`/v1/crud-demo/users/${id}`, data),

  /** 删除用户 */
  deleteUser: (id: number) => api.delete(`/v1/crud-demo/users/${id}`),
}
