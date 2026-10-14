/**
 * MSW 测试网络层 —— 组件测试统一走 service worker 拦截，
 * 与真实后端解耦；onUnhandledRequest: 'error' 确保漏配端点在测试中显式报错.
 *
 * 用法：默认 handlers 覆盖组件测试常用端点（auth / workspaces / tables /
 * fields / records / views / preferences）；单用例可 server.use() 覆盖.
 */

import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import type {
  Field, RowListResponse, TableSummary, UserResponse, View, Workspace,
} from '@/api'
import type { DocumentItem } from '@/api/documents'

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

/** 表详情 fixture：TableEmbed / 编辑器选表弹窗使用 */
export const mockTableDetail = {
  id: 100,
  workspace_id: 10,
  name: '客户表',
  fields: [mockField],
  views: mockViews.map(v => ({ id: v.id, name: v.name, view_type: v.view_type, is_default: v.is_default })),
}

/** 文档树 fixture：文件夹「产品文档」下挂「需求说明」与子文件夹「会议纪要」 */
export const mockDocuments: DocumentItem[] = [
  {
    id: 1,
    workspace_id: 10,
    parent_id: null,
    title: '产品文档',
    slug: null,
    content_type: 'folder',
    author: '',
    summary: '',
    toc_json: [],
    status: 'draft',
    is_folder: true,
    sort_order: 0,
    content_size: 0,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-02T00:00:00Z',
    created_by_id: 1,
    updated_by_id: 1,
    tag_ids: [],
    version_count: 0,
  },
  {
    id: 2,
    workspace_id: 10,
    parent_id: 1,
    title: '需求说明',
    slug: null,
    content_type: 'markdown',
    author: '',
    summary: '',
    toc_json: [],
    status: 'draft',
    is_folder: false,
    sort_order: 0,
    content_size: 128,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-02T00:00:00Z',
    created_by_id: 1,
    updated_by_id: 1,
    tag_ids: [],
    version_count: 1,
  },
  {
    id: 3,
    workspace_id: 10,
    parent_id: 1,
    title: '会议纪要',
    slug: null,
    content_type: 'folder',
    author: '',
    summary: '',
    toc_json: [],
    status: 'draft',
    is_folder: true,
    sort_order: 1,
    content_size: 0,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-02T00:00:00Z',
    created_by_id: 1,
    updated_by_id: 1,
    tag_ids: [],
    version_count: 0,
  },
]

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
  http.get('/api/v1/workspaces/:wid/tables/:tid', () =>
    HttpResponse.json(mockTableDetail)),

  // 字段
  http.get('/api/v1/workspaces/:wid/tables/:tid/fields', () =>
    HttpResponse.json([mockField])),

  // 行
  http.get('/api/v1/workspaces/:wid/tables/:tid/records', () =>
    HttpResponse.json(mockRecords)),

  // 视图行（TableEmbed 带 view 参数的引用）
  http.get('/api/v1/workspaces/:wid/tables/:tid/views/:vid/rows', () =>
    HttpResponse.json({
      rows: mockRecords.items,
      total: mockRecords.total,
      view_id: Number(200),
    })),

  // 视图
  http.get('/api/v1/workspaces/:wid/tables/:tid/views', () =>
    HttpResponse.json(mockViews)),

  // 文档（MainLayout 徽标 + 文档树 / 列表）：list 按 parent_id 过滤（后端语义：传入才过滤层级）
  http.get('/api/v1/workspaces/:wid/documents', ({ request }) => {
    const parentParam = new URL(request.url).searchParams.get('parent_id')
    const items = parentParam != null && parentParam !== ''
      ? mockDocuments.filter(d => String(d.parent_id) === parentParam)
      : mockDocuments
    return HttpResponse.json({ items, total: items.length })
  }),
  http.get('/api/v1/workspaces/:wid/documents/tree', () =>
    HttpResponse.json({ items: mockDocuments })),
  // 回收站：软删除列表（含删除时间）
  http.get('/api/v1/workspaces/:wid/documents/trash', () =>
    HttpResponse.json({
      items: [{ ...mockDocuments[1], deleted_at: '2026-02-01T10:00:00Z', deleted_by_id: 1 }],
      total: 1,
    })),
  // 出链解析：一条已解析 + 一条断链
  http.get('/api/v1/workspaces/:wid/documents/:docId/links', () =>
    HttpResponse.json({
      items: [
        { title: '需求说明', document_id: 2, exists: true, broken: false },
        { title: '不存在的文档', document_id: null, exists: false, broken: true },
      ],
      total: 2,
      broken: 1,
    })),
  // 断链修复：返回新版本信息
  http.post('/api/v1/workspaces/:wid/documents/:docId/links/repair', async ({ request }) => {
    const body = await request.json() as { repairs?: { title: string; target_document_id: number }[] }
    const repairs = body.repairs ?? []
    const target = mockDocuments.find(d => d.id === repairs[0]?.target_document_id) ?? mockDocuments[1]
    return HttpResponse.json({
      document_id: 2,
      version_number: 2,
      repaired: repairs.map(r => ({
        title: r.title,
        new_title: target.title,
        document_id: target.id,
        count: 1,
      })),
      replaced: repairs.length,
      document: mockDocuments[1],
    })
  }),
  // 回收站：恢复 / 彻底删除
  http.post('/api/v1/workspaces/:wid/documents/:docId/restore', () =>
    HttpResponse.json({ ...mockDocuments[1], restored_count: 1, reparented_to_root: false })),
  http.delete('/api/v1/workspaces/:wid/documents/:docId/purge', () =>
    HttpResponse.json({ id: 2, purged: true, purged_count: 1, files_removed: 0, detached: 0 })),
  // 全文搜索（FTS5 高亮：title_hit/summary_hit 带 <mark> 标记）
  http.get('/api/v1/workspaces/:wid/documents/search', ({ request }) => {
    const q = (new URL(request.url).searchParams.get('q') ?? '').trim()
    if (!q) return HttpResponse.json({ items: [], total: 0, query: q })
    const kw = q.toLowerCase()
    const hit = (text: string) => text.toLowerCase().includes(kw)
    const items = mockDocuments
      .filter(d => hit(d.title) || hit(d.summary))
      .map(d => ({
        id: d.id,
        title: d.title,
        title_hit: hit(d.title) ? `<mark>${d.title}</mark>` : d.title,
        summary_hit: hit(d.summary)
          ? `…<mark>${d.summary}</mark>…`
          : (d.summary || '（正文无高亮片段）'),
        workspace_id: d.workspace_id,
        status: d.status,
        updated_at: d.updated_at,
        rank: 0.0,
      }))
    return HttpResponse.json({ items, total: items.length, query: q })
  }),
  http.post('/api/v1/workspaces/:wid/documents', async ({ request }) => {
    const body = await request.json() as {
      title?: string
      is_folder?: boolean
      parent_id?: number | null
    }
    return HttpResponse.json(
      {
        ...mockDocuments[0],
        id: 99,
        title: body.title ?? '未命名',
        is_folder: !!body.is_folder,
        parent_id: body.parent_id ?? null,
      },
      { status: 201 },
    )
  }),
  // 每日笔记（幂等：固定返回今日笔记文档）
  http.post('/api/v1/workspaces/:wid/documents/daily-note', () =>
    HttpResponse.json({
      ...mockDocuments[1],
      id: 77,
      title: '2026-10-14',
      is_folder: false,
      parent_id: null,
      created: true,
    })),
  // 反向链接（谁引用了本文档标题）
  http.get('/api/v1/workspaces/:wid/documents/:docId/backlinks', () =>
    HttpResponse.json({
      items: [
        {
          id: 3,
          title: '会议纪要',
          summary: '本周会议提到了需求说明的边界',
          status: 'draft',
          updated_at: '2026-01-02T00:00:00Z',
        },
      ],
      total: 1,
    })),
  http.patch('/api/v1/workspaces/:wid/documents/:docId', () =>
    HttpResponse.json(mockDocuments[0])),
  http.delete('/api/v1/workspaces/:wid/documents/:docId', () =>
    HttpResponse.json({ id: 1, deleted: true })),
  // 文档内容（编辑器 / TableEmbed 场景）
  http.get('/api/v1/workspaces/:wid/documents/:docId/content', () =>
    HttpResponse.json({
      ...mockDocuments[1],
      content: '# 需求说明\n\n正文段落。\n',
      version_number: 1,
    })),

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
