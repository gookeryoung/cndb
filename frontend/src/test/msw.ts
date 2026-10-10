/**
 * MSW 测试网络层 —— 组件测试统一走 service worker 拦截，
 * 与真实后端解耦；onUnhandledRequest: 'error' 确保漏配端点在测试中显式报错.
 *
 * 用法：默认 handlers 覆盖组件测试常用端点（auth / workspaces / tables /
 * fields / records / views / preferences）；单用例可 server.use() 覆盖.
 */

import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import type { Field, RowListResponse, TableSummary, UserResponse, View, Workspace } from '@/api'

// ─────────────── 测试 fixtures ───────────────

export const mockUser: UserResponse = {
  id: 1,
  username: 'alice',
  email: 'alice@example.com',
  nickname: '爱丽丝',
  role: 'system_admin',
  is_active: true,
}

export const mockWorkspace: Workspace = {
  id: 10,
  name: '测试工作区',
  description: 'MSW 默认工作区',
  report_count: 0,
}

export const mockTable: TableSummary = {
  id: 100,
  name: '客户表',
  record_count: 2,
  field_count: 2,
  view_count: 1,
}

export const mockField: Field = {
  id: 1000,
  name: '姓名',
  field_type: 'text',
  order: 0,
}

export const mockViews: View[] = [
  { id: 200, name: '全部数据', view_type: 'grid', is_default: true },
]

export const mockRecords: RowListResponse = {
  items: [
    { id: 1, 姓名: '张三' },
    { id: 2, 姓名: '李四' },
  ],
  total: 2,
  offset: 0,
  limit: 50,
}

// ─────────────── 默认 handlers ───────────────

export const handlers = [
  // 认证
  http.post('/api/v1/accounts/auth/login', () =>
    HttpResponse.json({ access_token: 'fake-token', token_type: 'bearer' })),
  http.get('/api/v1/accounts/auth/me', () => HttpResponse.json(mockUser)),

  // 工作区
  http.get('/api/v1/workspaces', () => HttpResponse.json([mockWorkspace])),

  // 表
  http.get('/api/v1/workspaces/:wid/tables', () => HttpResponse.json([mockTable])),

  // 字段
  http.get('/api/v1/workspaces/:wid/tables/:tid/fields', () =>
    HttpResponse.json([mockField])),

  // 行
  http.get('/api/v1/workspaces/:wid/tables/:tid/records', () =>
    HttpResponse.json(mockRecords)),

  // 视图
  http.get('/api/v1/workspaces/:wid/tables/:tid/views', () =>
    HttpResponse.json(mockViews)),

  // 系统基本信息（登录即可，普通用户可查看）
  http.get('/api/v1/system/about', () =>
    HttpResponse.json({
      app_name: 'cndb',
      app_version: '0.3.0',
      auth_enabled: true,
      timezone: 'UTC',
      server_time: '2026-10-10T12:00:00+00:00',
    })),

  // 用户管理（AdminPanel 默认挂载 UsersPage，需提供空分页兜底）
  http.get('/api/v1/accounts/users', () =>
    HttpResponse.json({ total: 0, items: [] })),
  http.patch('/api/v1/accounts/users/:id', () =>
    HttpResponse.json({ id: 1, username: 'alice', email: null, phone: null, nickname: null, role: 'user', is_active: true, is_superuser: false, created_at: '2026-01-01T00:00:00Z' })),
  http.post('/api/v1/accounts/users/batch', () =>
    HttpResponse.json({ total: 0, succeeded: 0, failed: 0, results: [] })),
  http.get('/api/v1/accounts/users/audit-logs', () =>
    HttpResponse.json({ total: 0, items: [] })),
  http.get('/api/v1/accounts/users/:id/audit-logs', () =>
    HttpResponse.json({ total: 0, items: [] })),
]

export const server = setupServer(...handlers)
