/** 工作区链接测试夹具与默认 handlers（ADR 0154 P2）.
 *
 * 单独成文件而不是塞进 `msw.ts`：链接功能的用例集中在两个测试文件里，
 * 默认 handler 只在这些用例中通过 `server.use(...linkHandlers)` 注册，
 * 避免全局默认表被无关用例频繁改动（该表由多人并行维护）。
 */

import { http, HttpResponse } from 'msw'
import type { SetupServer } from 'msw/node'

/** 生效中的跨工作区只读引用 */
export const mockWorkspaceLink = {
  id: 800,
  workspace_id: 10,
  source_workspace_id: 11,
  source_workspace_name: '源工作区',
  target_type: 'table' as const,
  target_table_id: 100,
  target_table_name: '销售明细',
  target_view_id: null,
  alias: '销售明细',
  status: 'active' as const,
  ttl_days: 30,
  expires_at: '2026-12-25T00:00:00Z',
  created_by_id: 1,
  approved_by_name: '张三',
  approved_at: '2026-11-25T00:00:00Z',
  note: '汇总用',
  readable: true,
  created_at: '2026-11-25T00:00:00Z',
  updated_at: '2026-11-25T00:00:00Z',
}

/** 链接相关默认 handlers（list 空 / inbox 空 / fields / rows / export 可用） */
export const linkHandlers = [
  http.get('/api/v1/workspaces/:wid/links', () => HttpResponse.json([])),
  http.get('/api/v1/workspaces/:wid/links/inbox', () => HttpResponse.json([])),
  http.post('/api/v1/workspaces/:wid/links', async ({ request }) => {
    const body = (await request.json()) as Record<string, unknown>
    return HttpResponse.json(
      {
        ...mockWorkspaceLink,
        source_workspace_id: Number(body.source_workspace_id),
        target_table_id: Number(body.target_table_id),
        alias: (body.alias as string) || mockWorkspaceLink.alias,
      },
      { status: 201 },
    )
  }),
  http.get('/api/v1/workspaces/:wid/links/:lid/fields', ({ params }) =>
    HttpResponse.json({
      link_id: Number(params.lid),
      table_id: mockWorkspaceLink.target_table_id,
      table_name: mockWorkspaceLink.target_table_name,
      target_type: 'table',
      fields: [
        { id: 1, name: '名称', field_type: 'text', order: 0 },
        { id: 2, name: '金额', field_type: 'number', order: 1 },
      ],
    }),
  ),
  http.get('/api/v1/workspaces/:wid/links/:lid/rows', ({ params }) =>
    HttpResponse.json({
      link_id: Number(params.lid),
      target_type: 'table',
      total: 1,
      limit: 50,
      offset: 0,
      rows: [{ id: 1, 名称: '甲', 金额: 12 }],
    }),
  ),
  http.get('/api/v1/workspaces/:wid/links/:lid/export', () => {
    const nl = String.fromCharCode(10)
    return new HttpResponse(['名称,金额', '甲,12', ''].join(nl), {
      status: 200,
      headers: { 'Content-Type': 'text/csv; charset=utf-8' },
    })
  }),
]

/** 注册链接默认 handlers（测试内 `beforeEach` 调用） */
export function installLinkHandlers(server: SetupServer): void {
  server.use(...linkHandlers)
}
