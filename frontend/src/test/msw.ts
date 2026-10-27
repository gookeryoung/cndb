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
import type { ChartInstance, ChartTemplatesPayload } from '@/api/charts'
import type { DocumentItem } from '@/api/documents'
import type { HelpExampleList, HelpFigureList } from '@/api/help'

// 1x1 透明 PNG —— 附件端点默认响应体（内容不断言，只需是合法二进制）
const _PNG_1PX = Uint8Array.from(
  atob('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=='),
  (c) => c.charCodeAt(0),
)

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
    pinned: false,
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
    pinned: false,
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
    pinned: false,
  },
]

/** 帮助文档典型示例清单 fixture（ADR 0029 P1）：结构与后端接口一致 */
export const mockHelpExamples: HelpExampleList = {
  items: [
    {
      key: 'sales',
      name: '某企业销售管理',
      summary: '从销售明细、客户流失到营销活动与日常待办的完整销售运营示例。',
      tables: [
        { file: '电商销售.csv', title: '电商销售', description: '订单级销售明细', rows: 500 },
        { file: '客户流失.csv', title: '客户流失', description: '客户维度的流失状态', rows: 500 },
      ],
      highlights: ['图表视图看月度销售额', '看板视图跟踪客户流失回访状态'],
      steps: ['下载 CSV', '新建数据表并导入', '按字段类型核对后创建视图'],
    },
    {
      key: 'research',
      name: '科研项目管理',
      summary: '围绕课题立项、任务分解、经费与资源排期组织数据。',
      tables: [
        { file: '科研项目.csv', title: '科研项目', description: '课题主数据', rows: 40 },
      ],
      highlights: ['工作分解视图组织层级'],
      steps: ['下载 CSV', '导入为数据表'],
    },
    {
      key: 'datasource',
      name: '数据源示例',
      summary: '把外部数据按计划写入数据表。',
      tables: [
        { file: '天气每日.csv', title: '天气每日', description: '天气观测', rows: 276 },
      ],
      highlights: ['画廊视图阅读政策与情报简报'],
      steps: ['下载示例 CSV', '配置数据源同步'],
    },
  ],
}

/** 帮助图示清单 fixture（ADR 0030）：覆盖帮助正文里引用的全部 key */
const HELP_FIGURE_KEYS = [
  'quick-start-flow',
  'workspace-structure',
  'field-types',
  'permission-model',
  'import-flow',
  'datasource-sync',
  ...['sales', 'research', 'datasource'].flatMap((scenario) =>
    [1, 2, 3, 4].map((index) => `example-${scenario}-table-${index}`)),
]

export const mockHelpFigures: HelpFigureList = {
  items: HELP_FIGURE_KEYS.map((key) => ({
    key,
    title: `图示 ${key}`,
    caption: `图示说明 ${key}`,
    section: 'quick-start',
    fingerprint: 'f1e2d3c4b5a69788',
    generatedAt: 1761300000,
  })),
  generatedAt: 1761300000,
}

// ─────────────── 图表 fixtures（ADR 0048） ───────────────

/** 图表渲染端点的样例 SVG（render / render-preview 共用，内容不断言具体图元） */
export const mockChartSvg =
  '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 720 480" data-chart-sample="1"><title>样例图表</title><rect width="720" height="480" fill="#FBFAF5"/></svg>'

/** 两级模板清单：与后端 templates_payload() 同构（3 类别 × 3 模板，默认配置取精简样例） */
export const mockChartTemplates: ChartTemplatesPayload = {
  categories: [
    { key: 'trend', name: '趋势分析', description: '时间序列的总量走势与增速' },
    { key: 'composition', name: '结构构成', description: '整体中各部分的构成与变化' },
    { key: 'comparison', name: '目标对比', description: '现状与规划目标的逐项对比' },
  ],
  templates: [
    {
      key: 'bar-line-dual-axis',
      category: 'trend',
      name: '柱线组合图（双轴）',
      description: '柱（左轴主值，实际 / 测算两色）+ 折线（右轴次值），含规划期分界带与图注增速联动',
      row_min: 2,
      row_max: 24,
      row_columns: [
        { key: 'label', type: 'text', label: '年份' },
        { key: 'value', type: 'number', label: '主值（左轴）', required: true },
        { key: 'growth', type: 'number', label: '次值（右轴，留空按主值推算）' },
      ],
      series_min: 0,
      series_max: 0,
      label_fields: [
        { key: 'legendActual', label: '图例 · 主值（实际）' },
        { key: 'legendProjected', label: '图例 · 主值（测算）' },
        { key: 'legendGrowth', label: '图例 · 次值' },
        { key: 'bandLabel', label: '图内标注 · 规划期' },
        { key: 'capActual', label: '轴下说明 · 实际区间' },
        { key: 'capProjected', label: '轴下说明 · 测算区间' },
        { key: 'unitLeft', label: '左轴单位' },
        { key: 'unitRight', label: '右轴单位' },
      ],
      default_config: {
        caption: {
          no: '图 2-1',
          context: '',
          title: '产业营业收入与增速（2020—2030年）',
          subtitle: '单位：亿元、%',
          note: '注：2026—2030年年均增速{cagr}。\n数据来源：市统计局。',
        },
        labels: {
          legendActual: '营业收入（实际值）',
          legendProjected: '营业收入（测算值）',
          legendGrowth: '同比增速',
          bandLabel: '规划期（测算值）',
          capActual: '实际值（统计口径）',
          capProjected: '规划测算值',
          unitLeft: '亿元',
          unitRight: '%',
        },
        theme: { palette: ['#8E2318', '#5C7283', '#5F6B4E'], paper: '#FBFAF5' },
        data: {
          actualCount: 2,
          rows: [
            { label: '2020', value: 132, growth: null },
            { label: '2021', value: 158, growth: 19.7 },
            { label: '2022', value: 186, growth: null },
          ],
        },
      },
    },
    {
      key: 'stacked-bar-horizontal',
      category: 'composition',
      name: '水平堆叠条形图',
      description: '行 × 系列堆叠的水平条形，宽段内置白字、窄段外置标签，行尾自动合计',
      row_min: 1,
      row_max: 12,
      row_columns: [
        { key: 'label', type: 'text', label: '行' },
        { key: 'values', type: 'number[]', label: '系列值', required: true },
      ],
      series_min: 1,
      series_max: 6,
      label_fields: [],
      default_config: {
        caption: { no: '图 3-1', context: '', title: '产业结构变化', subtitle: '单位：亿元', note: '' },
        labels: { series: ['整车', '零部件', '服务'], unitX: '亿元' },
        theme: { palette: ['#8E2318', '#1E3D57', '#5F6B4E'], paper: '#FBFAF5' },
        data: {
          rows: [
            { label: '2025年', values: [1250, 480, 120] },
            { label: '2030年', values: [2040, 800, 360] },
          ],
        },
      },
    },
    {
      key: 'grouped-bar-horizontal',
      category: 'comparison',
      name: '水平分组条形图',
      description: '类别 × 两系列（现状 / 目标）成组水平条，组内双条数值标签，横轴上限自动扩展',
      row_min: 1,
      row_max: 14,
      row_columns: [
        { key: 'label', type: 'text', label: '类别' },
        { key: 'values', type: 'number[]', label: '系列值', required: true },
      ],
      series_min: 2,
      series_max: 2,
      label_fields: [],
      default_config: {
        caption: { no: '图 4-1', context: '', title: '本地配套率现状与目标', subtitle: '单位：%', note: '' },
        labels: { series: ['2025年现状', '2030年目标'], unitX: '%' },
        theme: { palette: ['#E9E4D6', '#8E2318'], paper: '#FBFAF5' },
        data: {
          rows: [
            { label: '隔膜', values: [0, 35] },
            { label: '车规芯片', values: [8, 25] },
          ],
        },
      },
    },
  ],
}

/** 图表实例 fixture：ChartEmbed / 插入弹窗 / 设计器编辑模式使用 */
export const mockChartInstance: ChartInstance = {
  id: 300,
  workspace_id: 10,
  title: '产业营业收入与增速',
  template_key: 'bar-line-dual-axis',
  category: 'trend',
  config: mockChartTemplates.templates[0].default_config,
  created_by_id: 1,
  updated_by_id: 1,
  created_at: '2026-02-01T00:00:00Z',
  updated_at: '2026-02-02T00:00:00Z',
}

// ─────────────── 默认 handlers ───────────────

export const handlers = [
  // 认证
  http.post('/api/v1/accounts/auth/login', () =>
    HttpResponse.json({ access_token: 'fake-token', token_type: 'bearer' })),
  http.get('/api/v1/accounts/auth/me', () => HttpResponse.json(mockUser)),

  // 帮助文档示例清单 / CSV 下载（ADR 0029 P1）
  http.get('/api/v1/help/examples', () => HttpResponse.json(mockHelpExamples)),
  http.get('/api/v1/help/examples/:scenario/files/:filename', () =>
    new HttpResponse('订单号,销售额\nA-1,100\n', {
      status: 200,
      headers: { 'Content-Type': 'text/csv; charset=utf-8' },
    })),

  // 帮助文档图示清单 / SVG（ADR 0030）
  http.get('/api/v1/help/figures', () => HttpResponse.json(mockHelpFigures)),
  http.get('/api/v1/help/figures/:key', ({ params }) =>
    new HttpResponse(
      `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10" data-help-figure="1"><title>${String(params.key)}</title></svg>`,
      { status: 200, headers: { 'Content-Type': 'image/svg+xml; charset=utf-8' } },
    )),

  // 用户偏好（ADR 0021：主页自定义顺序 / 收藏视图）——默认空，单用例 server.use 覆盖
  http.get('/api/v1/accounts/preferences', () =>
    HttpResponse.json({ active_views: {}, workspace_order: [], favorite_view_ids: [] })),
  http.get('/api/v1/accounts/preferences/favorite-views', () => HttpResponse.json([])),
  http.put('/api/v1/accounts/preferences/favorite-views', async ({ request }) => {
    const body = await request.json() as { view_ids?: number[] }
    return HttpResponse.json({ view_ids: body.view_ids ?? [] })
  }),
  http.put('/api/v1/accounts/preferences/workspace-order', async ({ request }) => {
    const body = await request.json() as { workspace_ids?: number[] }
    return HttpResponse.json({ workspace_ids: body.workspace_ids ?? [] })
  }),

  // 工作区
  http.get('/api/v1/workspaces', () => HttpResponse.json([mockWorkspace])),
  // 工作区详情（文档编辑器 / 修改申请页读取当前用户角色）
  http.get('/api/v1/workspaces/:wid', ({ params }) =>
    HttpResponse.json({ ...mockWorkspace, id: Number(params.wid), current_user_role: 'owner' })),
  // 文档修改申请列表（默认空；单用例 server.use 覆盖）
  http.get('/api/v1/workspaces/:wid/document-change-requests', () =>
    HttpResponse.json({ items: [], total: 0 })),
  // 文档问题清单列表（默认空；单用例 server.use 覆盖）
  http.get('/api/v1/workspaces/:wid/document-issues', () =>
    HttpResponse.json({ items: [], total: 0 })),

  // 附件（useFileObjectUrl 经 axios 取 blob；1x1 PNG 字节即可）
  http.post('/api/v1/workspaces/:wid/files', () =>
    HttpResponse.json({ file_key: 'mock-upload.png', filename: 'mock-upload.png', size: 4, mime_type: 'image/png' }, { status: 201 })),
  http.get('/api/v1/workspaces/:wid/files/:fileKey', () =>
    new HttpResponse(_PNG_1PX, { status: 200, headers: { 'Content-Type': 'image/png' } })),
  http.delete('/api/v1/workspaces/:wid/files/:fileKey', () => new HttpResponse(null, { status: 204 })),

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

  // 图表（ADR 0048）：字面段（templates / render-preview）先于 :id 段注册
  http.get('/api/v1/workspaces/:wid/charts/templates', () =>
    HttpResponse.json(mockChartTemplates)),
  http.post('/api/v1/workspaces/:wid/charts/render-preview', () =>
    new HttpResponse(mockChartSvg, {
      status: 200,
      headers: { 'Content-Type': 'image/svg+xml; charset=utf-8' },
    })),
  http.get('/api/v1/workspaces/:wid/charts', () =>
    HttpResponse.json({ items: [mockChartInstance] })),
  http.post('/api/v1/workspaces/:wid/charts', async ({ request }) => {
    const body = await request.json() as {
      title?: string; template_key?: string; config?: Record<string, unknown>
    }
    return HttpResponse.json(
      {
        ...mockChartInstance,
        id: mockChartInstance.id + 1,
        title: body.title ?? '',
        template_key: body.template_key ?? mockChartInstance.template_key,
        config: body.config ?? mockChartInstance.config,
        updated_at: '2026-02-03T00:00:00Z',
      },
      { status: 201 },
    )
  }),
  http.get('/api/v1/workspaces/:wid/charts/:cid', ({ params }) =>
    HttpResponse.json({ ...mockChartInstance, id: Number(params.cid) })),
  http.put('/api/v1/workspaces/:wid/charts/:cid', async ({ request, params }) => {
    const body = await request.json() as {
      title?: string; template_key?: string; config?: Record<string, unknown>
    }
    return HttpResponse.json({
      ...mockChartInstance,
      id: Number(params.cid),
      title: body.title ?? mockChartInstance.title,
      template_key: body.template_key ?? mockChartInstance.template_key,
      config: body.config ?? mockChartInstance.config,
      updated_at: '2026-02-04T00:00:00Z',
    })
  }),
  http.delete('/api/v1/workspaces/:wid/charts/:cid', ({ params }) =>
    HttpResponse.json({ id: Number(params.cid), deleted: true })),
  http.get('/api/v1/workspaces/:wid/charts/:cid/render', ({ request }) => {
    const etag = '"mock-chart-etag-v1"'
    if (request.headers.get('If-None-Match') === etag) {
      return new HttpResponse(null, { status: 304, headers: { ETag: etag } })
    }
    return new HttpResponse(mockChartSvg, {
      status: 200,
      headers: { 'Content-Type': 'image/svg+xml; charset=utf-8', ETag: etag },
    })
  }),

  // 站内通知：默认无通知（铃铛在 MainLayout 中常驻，必须给默认处理）
  http.get('/api/v1/accounts/notifications', () =>
    HttpResponse.json({ items: [], unread_count: 0 })),
  http.post('/api/v1/accounts/notifications/read-all', () => HttpResponse.json({ updated: 0 })),
  http.post('/api/v1/accounts/notifications/:id/read', () => new HttpResponse(null, { status: 204 })),

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
  // 工作区统一检索（顶栏搜索框）：文档按标题/摘要命中；数据表按表名 + 表内行值命中。
  // scope 只影响对应分组；仅「数据表」范围带 view_id 时回显 view 说明（ADR 0015）。
  http.get('/api/v1/workspaces/:wid/search', ({ request }) => {
    const url = new URL(request.url)
    const q = (url.searchParams.get('q') ?? '').trim()
    const scope = url.searchParams.get('scope') ?? 'all'
    const viewId = url.searchParams.get('view_id')
    const tableId = url.searchParams.get('table_id')
    if (!q) return HttpResponse.json({ query: '', documents: [], tables: [], rows: [], view: null })
    const kw = q.toLowerCase()
    const hit = (text: string) => text.toLowerCase().includes(kw)
    const documents = scope === 'tables'
      ? []
      : mockDocuments
        .filter(d => !d.is_folder && (hit(d.title) || hit(d.summary)))
        .map(d => ({
          id: d.id,
          title: d.title,
          title_hit: hit(d.title) ? `<mark>${d.title}</mark>` : d.title,
          summary_hit: hit(d.summary) ? `…<mark>${d.summary}</mark>…` : d.summary,
          status: d.status,
          updated_at: d.updated_at,
        }))
    const tables = scope === 'documents' || !hit(mockTable.name)
      ? []
      : [{ id: mockTable.id, name: mockTable.name, description: '客户主数据' }]
    const rows = scope === 'documents'
      ? []
      : mockRecords.items
        .filter(r => Object.values(r).some(v => typeof v === 'string' && hit(v)))
        .map(r => ({
          table_id: mockTable.id,
          table_name: mockTable.name,
          row_id: r.id,
          title: String(r.姓名 ?? ''),
          snippet: String(r.姓名 ?? ''),
        }))
    const view = tableId && scope === 'tables'
      ? {
        id: viewId ? Number(viewId) : null,
        name: viewId ? (mockViews.find(v => v.id === Number(viewId))?.name ?? '') : '',
        table_id: Number(tableId),
        table_name: mockTable.name,
      }
      : null
    return HttpResponse.json({ query: q, documents, tables, rows, view })
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
      draft: null,
      write_mode: 'direct',
    })),
  // 个人草稿：保存只写草稿，不生成版本
  http.get('/api/v1/workspaces/:wid/documents/:docId/draft', () =>
    HttpResponse.json({ draft: null })),
  http.put('/api/v1/workspaces/:wid/documents/:docId/draft', async ({ request }) => {
    const body = await request.json() as { content?: string; base_version_number?: number }
    const content = body.content ?? ''
    return HttpResponse.json({
      draft: {
        content,
        content_size: content.length,
        base_version_number: body.base_version_number ?? 1,
        current_version_number: 1,
        stale: false,
        updated_at: '2026-01-02T00:00:00Z',
      },
    })
  }),
  http.delete('/api/v1/workspaces/:wid/documents/:docId/draft', () =>
    new HttpResponse(null, { status: 204 })),
  // 显式提交：默认直编落库并生成新版本
  http.post('/api/v1/workspaces/:wid/documents/:docId/submit', async ({ request }) => {
    const body = await request.json() as { content?: string }
    const content = body.content ?? ''
    return HttpResponse.json({
      mode: 'direct',
      message: '已提交并生成 v2',
      content,
      version_number: 2,
    })
  }),

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
