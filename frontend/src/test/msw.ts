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

  // 用户偏好（激活视图）
  http.get('/api/v1/accounts/preferences/tables/:tid/active-view', () =>
    HttpResponse.json({ table_id: mockTable.id, active_view_id: null })),
]

export const server = setupServer(...handlers)
