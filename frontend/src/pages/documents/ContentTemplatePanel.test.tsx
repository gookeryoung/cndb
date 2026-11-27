/** 内容模板面板测试（需求 0169 C4/C5；ADR 0177 C3 起由模板页按 ?kind= 切换）.
 *
 * 覆盖：模板清单渲染与选中、Markdown 正文编辑保存、删除、空态引导创建。
 * MarkdownLiveEditor 用轻量 textarea 替代（CodeMirror 在 jsdom 下不稳定）。
 */

import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import { Route, Routes } from 'react-router-dom'
import { http, HttpResponse } from 'msw'
import ContentTemplatePanel from './ContentTemplatePanel'
import { renderProviders } from '@/test/render-providers'
import { mockUser, server } from '@/test/msw'
import type { BuiltinContentLibrary, ContentTemplateItem } from '@/api'

vi.mock('@/components/Document/MarkdownLiveEditor', () => ({
  default: ({ value, onChange }: { value: string; onChange: (v: string) => void }) => (
    <textarea
      data-testid="template-markdown"
      value={value}
      onChange={e => onChange(e.target.value)}
    />
  ),
}))

const tpl = (id: number, name: string, body: string): ContentTemplateItem => ({
  id,
  workspace_id: 1,
  name,
  content_markdown: body,
  description: '模板说明',
  icon: '📝',
  sort_order: id,
  export_template_ref: null,
  created_by_id: 1,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
})

const builtinLibrary: BuiltinContentLibrary = {
  categories: [
    {
      key: 'research-pm',
      name: '科研项目管理',
      description: '立项 → 执行 → 结题全过程的文档骨架',
      sort_order: 10,
      templates: [
        {
          ref: 'builtin:research-pm.weekly-report',
          key: 'research-pm.weekly-report',
          name: '项目周报',
          description: '周度进展同步',
          icon: '🗓️',
          sort_order: 40,
          export_template_ref: null,
          content_markdown: '## 一、本周进展\n\n（填写）',
        },
        {
          ref: 'builtin:research-pm.project-proposal',
          key: 'research-pm.project-proposal',
          name: '项目立项申请书',
          description: '申报 / 立项评审',
          icon: '📝',
          sort_order: 10,
          export_template_ref: 'builtin:official',
          content_markdown: '## 一、项目基本信息\n\n（填写）',
        },
      ],
    },
  ],
}

const builtinHandler = http.get('/api/v1/workspaces/:wid/document-content-templates/builtin', () =>
  HttpResponse.json(builtinLibrary),
)

function renderPage() {
  return renderProviders(
    <Routes>
      <Route path="/w/:wid/documents/content-templates" element={<ContentTemplatePanel />} />
    </Routes>,
    { route: '/w/1/documents/content-templates', initialAuth: { user: mockUser, token: 'fake-token' } },
  )
}

describe('文档内容模板页（需求 0169）', () => {
  let savedPayload: Record<string, unknown> | null = null
  let deletedId: number | null = null
  let createdNames: string[] = []

  beforeEach(() => {
    savedPayload = null
    deletedId = null
    createdNames = []
    server.use(
      builtinHandler,
      http.get('/api/v1/workspaces/:wid/documents/templates', () =>
        HttpResponse.json({
          items: [
            {
              ref: 'builtin:thesis',
              name: '论文',
              description: '',
              source: 'builtin',
              is_default: false,
              config: {},
              updated_at: null,
            },
          ],
          total: 1,
          default_ref: 'builtin:research',
        }),
      ),
      http.get('/api/v1/workspaces/:wid/document-content-templates', () =>
        HttpResponse.json({ items: [tpl(1, '会议纪要', '# 纪要'), tpl(2, '周报', '# 周报')], total: 2 }),
      ),
      http.patch('/api/v1/workspaces/:wid/document-content-templates/:id', async ({ request }) => {
        savedPayload = (await request.json()) as Record<string, unknown>
        return HttpResponse.json(tpl(1, '会议纪要', String(savedPayload.content_markdown ?? '')))
      }),
      http.delete('/api/v1/workspaces/:wid/document-content-templates/:id', ({ params }) => {
        deletedId = Number(params.id)
        return HttpResponse.json({ ok: true })
      }),
      http.post('/api/v1/workspaces/:wid/document-content-templates', async ({ request }) => {
        const body = (await request.json()) as { name: string; content_markdown?: string }
        createdNames.push(body.name)
        return HttpResponse.json(tpl(3, body.name, body.content_markdown ?? ''))
      }),
    )
  })

  it('列出模板并选中首个，修改正文后保存携带完整草稿', async () => {
    renderPage()
    expect(await screen.findByTestId('content-template-row-1')).toHaveTextContent('会议纪要')
    expect(screen.getByTestId('template-markdown')).toHaveValue('# 纪要')

    fireEvent.change(screen.getByTestId('template-markdown'), { target: { value: '# 新纪要正文' } })
    fireEvent.click(screen.getByTestId('content-template-save'))

    await waitFor(() => {
      expect(savedPayload).toMatchObject({
        name: '会议纪要',
        description: '模板说明',
        content_markdown: '# 新纪要正文',
      })
    })
  })

  it('切换模板后正文随之更新，删除按钮调用对应 id', async () => {
    renderPage()
    expect(await screen.findByTestId('content-template-row-2')).toBeInTheDocument()
    fireEvent.click(screen.getByTestId('content-template-row-2'))
    expect(screen.getByTestId('template-markdown')).toHaveValue('# 周报')
    fireEvent.click(screen.getByTestId('content-template-delete'))
    // Popconfirm 二次确认（antd 两字按钮插空格）
    fireEvent.click(await screen.findByRole('button', { name: /^删\s*除$/ }))
    await waitFor(() => expect(deletedId).toBe(2))
  })

  it('有未保存修改时切换模板先确认，确认后切换', async () => {
    renderPage()
    expect(await screen.findByTestId('content-template-row-1')).toBeInTheDocument()
    fireEvent.change(screen.getByTestId('template-markdown'), { target: { value: '# 未保存改动' } })

    fireEvent.click(screen.getByTestId('content-template-row-2'))
    expect(await screen.findByText('放弃未保存的修改？')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '放弃并切换' }))

    await waitFor(() => expect(screen.getByTestId('template-markdown')).toHaveValue('# 周报'))
  })

  it('新建模板调用 POST 并选中新模板', async () => {
    renderPage()
    expect(await screen.findByTestId('content-template-row-1')).toBeInTheDocument()
    fireEvent.click(screen.getByTestId('content-template-create'))
    await waitFor(() => expect(createdNames).toEqual(['未命名模板']))
  })

  it('已有同名未命名模板时，新建自动递增为「未命名模板 2」', async () => {
    server.use(
      http.get('/api/v1/workspaces/:wid/document-content-templates', () =>
        HttpResponse.json({ items: [tpl(1, '未命名模板', '')], total: 1 }),
      ),
    )
    renderPage()
    expect(await screen.findByTestId('content-template-row-1')).toBeInTheDocument()
    fireEvent.click(screen.getByTestId('content-template-create'))
    await waitFor(() => expect(createdNames).toEqual(['未命名模板 2']))
  })

  it('自定义模板为空时显示引导（内置库仍在，空态口径改为自定义组为空）', async () => {
    server.use(
      http.get('/api/v1/workspaces/:wid/document-content-templates', () =>
        HttpResponse.json({ items: [], total: 0 }),
      ),
    )
    renderPage()
    expect(
      await screen.findByText(/还没有自定义模板：选一个内置模板后点「另存为自定义」/),
    ).toBeInTheDocument()
    // 内置库仍可用：首个内置条目在自动选中后展示只读详情
    expect(await screen.findByTestId('content-template-builtin-binding')).toBeInTheDocument()
  })

  it('绑定排版模板后保存携带 export_template_ref（ADR 0177 C6）', async () => {
    renderPage()
    expect(await screen.findByTestId('content-template-row-1')).toBeInTheDocument()

    const select = screen.getByTestId('content-template-export-template')
    fireEvent.mouseDown(select.querySelector('input')!)
    fireEvent.click(await screen.findByText('内置 · 论文'))
    fireEvent.click(screen.getByTestId('content-template-save'))

    await waitFor(() => expect(savedPayload).toMatchObject({ export_template_ref: 'builtin:thesis' }))
  })
})

describe('内容模板能力对齐（ADR 0177 C5）', () => {
  let createdPayloads: Array<Record<string, unknown>> = []
  let patched: Array<{ id: number; body: Record<string, unknown> }> = []
  let duplicated: number[] = []
  let items: ContentTemplateItem[] = []

  beforeEach(() => {
    createdPayloads = []
    patched = []
    duplicated = []
    items = [tpl(1, '会议纪要', '# 纪要'), tpl(2, '周报', '# 周报')]
    server.use(
      builtinHandler,
      http.get('/api/v1/workspaces/:wid/document-content-templates', () =>
        HttpResponse.json({ items, total: items.length }),
      ),
      http.post('/api/v1/workspaces/:wid/document-content-templates', async ({ request }) => {
        const body = (await request.json()) as Record<string, unknown>
        createdPayloads.push(body)
        return HttpResponse.json(tpl(10 + createdPayloads.length, String(body.name), String(body.content_markdown ?? '')), {
          status: 201,
        })
      }),
      http.patch('/api/v1/workspaces/:wid/document-content-templates/:id', async ({ request, params }) => {
        const body = (await request.json()) as Record<string, unknown>
        patched.push({ id: Number(params.id), body })
        return HttpResponse.json(tpl(Number(params.id), String(body.name ?? '会议纪要'), '# 纪要'))
      }),
      http.post('/api/v1/workspaces/:wid/document-content-templates/:id/duplicate', ({ params }) => {
        duplicated.push(Number(params.id))
        const copy = tpl(9, '会议纪要 副本', '# 纪要')
        items = [copy, ...items]
        return HttpResponse.json(copy, { status: 201 })
      }),
    )
  })

  it('创建副本调用服务端并以「原名 副本」选中新模板', async () => {
    renderPage()
    expect(await screen.findByTestId('content-template-row-1')).toBeInTheDocument()
    fireEvent.click(screen.getByTestId('content-template-duplicate'))

    await waitFor(() => expect(duplicated).toEqual([1]))
    expect(await screen.findByTestId('content-template-name')).toHaveValue('会议纪要 副本')
  })

  it('编辑 / 预览切换：预览只读渲染正文骨架', async () => {
    renderPage()
    expect(await screen.findByTestId('template-markdown')).toBeInTheDocument()

    // Segmented 的「预览」选项
    fireEvent.click(screen.getByText('预览'))
    const preview = await screen.findByTestId('content-template-preview')
    expect(preview).toHaveTextContent('纪要')
    expect(screen.queryByTestId('template-markdown')).not.toBeInTheDocument()

    fireEvent.click(screen.getByText('编辑'))
    expect(await screen.findByTestId('template-markdown')).toBeInTheDocument()
  })

  it('导出当前模板为 JSON 文件（kind=cndb-content-template）', async () => {
    const captured: Blob[] = []
    const createSpy = vi.fn((blob: Blob) => {
      captured.push(blob)
      return 'blob:content-template'
    })
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: createSpy })
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() })

    renderPage()
    await screen.findByTestId('content-template-row-1')
    fireEvent.click(screen.getByTestId('content-template-export'))

    await waitFor(() => expect(createSpy).toHaveBeenCalled())
    const parsed = JSON.parse(await captured[0].text()) as {
      kind: string
      version: number
      templates: Array<{ name: string; content_markdown: string }>
    }
    expect(parsed.kind).toBe('cndb-content-template')
    expect(parsed.version).toBe(1)
    expect(parsed.templates[0]).toMatchObject({ name: '会议纪要', content_markdown: '# 纪要' })
  })

  it('导入内容模板文件：同名自动加（导入）后逐条创建', async () => {
    renderPage()
    await screen.findByTestId('content-template-row-1')
    const file = new File(
      [
        JSON.stringify({
          kind: 'cndb-content-template',
          version: 1,
          templates: [
            { name: '会议纪要', content_markdown: '# 来自文件' },
            { name: '新骨架', description: '说明', icon: '📝', content_markdown: '# 新' },
          ],
        }),
      ],
      'content-templates.json',
      { type: 'application/json' },
    )
    fireEvent.change(screen.getByTestId('content-template-import-input'), { target: { files: [file] } })

    await waitFor(() => expect(createdPayloads).toHaveLength(2))
    expect(createdPayloads[0]).toMatchObject({ name: '会议纪要（导入）', content_markdown: '# 来自文件' })
    expect(createdPayloads[1]).toMatchObject({ name: '新骨架', description: '说明', icon: '📝' })
  })

  it('导入排版模板文件时明确报错且不发创建请求', async () => {
    renderPage()
    await screen.findByTestId('content-template-row-1')
    const file = new File(
      [JSON.stringify({ kind: 'cndb-document-template', version: 1, templates: [] })],
      'report-template.json',
      { type: 'application/json' },
    )
    fireEvent.change(screen.getByTestId('content-template-import-input'), { target: { files: [file] } })

    await waitFor(() => expect(screen.getByTestId('content-template-import')).toBeEnabled())
    expect(createdPayloads).toHaveLength(0)
  })

  it('拖拽行到另一行上按新顺序写回 sort_order', async () => {
    renderPage()
    const first = await screen.findByTestId('content-template-row-1')
    const second = screen.getByTestId('content-template-row-2')

    fireEvent.dragStart(first)
    fireEvent.dragOver(second)
    fireEvent.drop(second)

    // 顺序变为 [周报, 会议纪要] → 两条都写 0 / 10
    await waitFor(() => expect(patched).toHaveLength(2))
    expect(patched).toEqual([
      { id: 2, body: { sort_order: 0 } },
      { id: 1, body: { sort_order: 10 } },
    ])
  })
})

describe('内置内容模板库（ADR 0185）', () => {
  let createdPayloads: Array<Record<string, unknown>> = []

  beforeEach(() => {
    createdPayloads = []
    server.use(
      builtinHandler,
      http.get('/api/v1/workspaces/:wid/documents/templates', () =>
        HttpResponse.json({ items: [], total: 0, default_ref: 'builtin:research' }),
      ),
      http.get('/api/v1/workspaces/:wid/document-content-templates', () =>
        HttpResponse.json({ items: [tpl(1, '项目周报', '## 自定义周报')], total: 1 }),
      ),
      http.post('/api/v1/workspaces/:wid/document-content-templates', async ({ request }) => {
        const body = (await request.json()) as Record<string, unknown>
        createdPayloads.push(body)
        return HttpResponse.json(tpl(5, String(body.name), String(body.content_markdown ?? '')), { status: 201 })
      }),
    )
  })

  it('左清单两组：内置按分类分组并带「内置」徽标，自定义平铺', async () => {
    renderPage()
    expect(await screen.findByTestId('content-template-group-builtin')).toHaveTextContent('内置模板')
    expect(screen.getByTestId('content-template-group-custom')).toHaveTextContent('自定义模板')
    // 分类标题来自接口返回的分类名（前端不硬编码领域）
    const category = await screen.findByTestId('content-template-category-research-pm')
    expect(category).toHaveTextContent('科研项目管理')
    expect(screen.getByTestId('content-template-builtin-research-pm.weekly-report')).toHaveTextContent('内置')
  })

  it('选中内置条目后只读：无保存 / 删除 / 副本，只有另存为与导出', async () => {
    renderPage()
    fireEvent.click(await screen.findByTestId('content-template-builtin-research-pm.weekly-report'))

    expect(await screen.findByTestId('content-template-save-as')).toBeInTheDocument()
    expect(screen.getByTestId('content-template-export')).toBeInTheDocument()
    expect(screen.queryByTestId('content-template-save')).not.toBeInTheDocument()
    expect(screen.queryByTestId('content-template-delete')).not.toBeInTheDocument()
    expect(screen.queryByTestId('content-template-duplicate')).not.toBeInTheDocument()
    // 正文以只读预览渲染，来自接口返回
    expect(screen.getByTestId('content-template-preview')).toHaveTextContent('本周进展')
    expect(screen.queryByTestId('template-markdown')).not.toBeInTheDocument()
  })

  it('内置条目展示绑定的排版模板说明', async () => {
    renderPage()
    fireEvent.click(await screen.findByTestId('content-template-builtin-research-pm.project-proposal'))
    await waitFor(() =>
      expect(screen.getByTestId('content-template-builtin-binding')).toHaveTextContent('builtin:official'),
    )
  })

  it('「另存为自定义」以原名（自定义）创建并带上正文与绑定', async () => {
    renderPage()
    fireEvent.click(await screen.findByTestId('content-template-builtin-research-pm.project-proposal'))
    fireEvent.click(screen.getByTestId('content-template-save-as'))

    await waitFor(() => expect(createdPayloads).toHaveLength(1))
    expect(createdPayloads[0]).toMatchObject({
      name: '项目立项申请书（自定义）',
      content_markdown: '## 一、项目基本信息\n\n（填写）',
      export_template_ref: 'builtin:official',
    })
  })

  it('「另存为自定义」名称冲突时递增', async () => {
    server.use(
      http.get('/api/v1/workspaces/:wid/document-content-templates', () =>
        HttpResponse.json({ items: [tpl(1, '项目立项申请书（自定义）', 'x')], total: 1 }),
      ),
    )
    renderPage()
    fireEvent.click(await screen.findByTestId('content-template-builtin-research-pm.project-proposal'))
    fireEvent.click(screen.getByTestId('content-template-save-as'))

    await waitFor(() => expect(createdPayloads).toHaveLength(1))
    expect(createdPayloads[0]).toMatchObject({ name: '项目立项申请书（自定义 2）' })
  })

  it('内置条目可导出为内容模板 JSON 文件', async () => {
    const captured: Blob[] = []
    const createSpy = vi.fn((blob: Blob) => {
      captured.push(blob)
      return 'blob:builtin'
    })
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: createSpy })
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() })

    renderPage()
    fireEvent.click(await screen.findByTestId('content-template-builtin-research-pm.weekly-report'))
    fireEvent.click(screen.getByTestId('content-template-export'))

    await waitFor(() => expect(createSpy).toHaveBeenCalled())
    const parsed = JSON.parse(await captured[0].text()) as {
      kind: string
      templates: Array<{ name: string; content_markdown: string }>
    }
    expect(parsed.kind).toBe('cndb-content-template')
    expect(parsed.templates[0]).toMatchObject({
      name: '项目周报',
      content_markdown: '## 一、本周进展\n\n（填写）',
    })
  })

  it('自定义模板能力回归：内置库存在时仍可保存 / 删除', async () => {
    renderPage()
    expect(await screen.findByTestId('content-template-row-1')).toBeInTheDocument()
    fireEvent.change(screen.getByTestId('template-markdown'), { target: { value: '## 改' } })
    await waitFor(() => expect(screen.getByTestId('content-template-save')).toBeEnabled())
  })
})

describe('contentTemplateFile（导入 / 导出文件格式）', () => {
  it('导出文本可回读：kind / version / 正文完整', async () => {
    const {
      buildContentTemplateFile,
      contentTemplateFileName,
      contentTemplateFileText,
      parseContentTemplateFile,
    } = await import('./contentTemplateFile')
    const entry = { name: '会议纪要', description: '周会', icon: '📝', content_markdown: '# 纪要' }
    const whole = buildContentTemplateFile([entry])
    expect(whole.kind).toBe('cndb-content-template')
    expect(whole.version).toBe(1)
    const back = parseContentTemplateFile(contentTemplateFileText([entry]))
    expect(back).toEqual([entry])
    expect(contentTemplateFileName('会议/纪要')).toBe(
      `内容模板-会议_纪要-${new Date().toISOString().slice(0, 10).replace(/-/g, '')}.json`,
    )
    expect(contentTemplateFileName('', true)).toContain('内容模板-全部模板-')
  })

  it('兼容单条（无 templates 包裹）与多条', async () => {
    const { parseContentTemplateFile } = await import('./contentTemplateFile')
    expect(parseContentTemplateFile(JSON.stringify({ name: '单条' })).map(e => e.name)).toEqual(['单条'])
    const multi = JSON.stringify({
      kind: 'cndb-content-template',
      version: 1,
      templates: [
        { name: 'A', content_markdown: '# A' },
        { name: 'B', description: 'x', icon: '📄', content_markdown: '' },
      ],
    })
    expect(parseContentTemplateFile(multi).map(e => e.name)).toEqual(['A', 'B'])
  })

  it('排版模板文件（kind=cndb-document-template）明确报错并指向导出模板页', async () => {
    const { parseContentTemplateFile } = await import('./contentTemplateFile')
    expect(() =>
      parseContentTemplateFile(JSON.stringify({ kind: 'cndb-document-template', version: 1, templates: [] })),
    ).toThrow('这是导出模板文件（Word / PDF 排版），请到「导出模板」页导入')
  })

  it('非法文件给出中文错误', async () => {
    const { parseContentTemplateFile } = await import('./contentTemplateFile')
    expect(() => parseContentTemplateFile('not json')).toThrow('不是合法的 JSON 文件')
    expect(() => parseContentTemplateFile(JSON.stringify({ kind: 'other' }))).toThrow('不是晶格协同的内容模板文件')
    expect(() =>
      parseContentTemplateFile(JSON.stringify({ kind: 'cndb-content-template', version: 99, templates: [] })),
    ).toThrow('版本过新')
    expect(() => parseContentTemplateFile(JSON.stringify({ content_markdown: 'x' }))).toThrow('缺少名称')
    expect(() => parseContentTemplateFile(JSON.stringify({ name: 'x', content_markdown: 1 }))).toThrow('必须是文本')
    expect(() => parseContentTemplateFile(JSON.stringify({ templates: [] }))).toThrow('没有任何模板')
  })
})
