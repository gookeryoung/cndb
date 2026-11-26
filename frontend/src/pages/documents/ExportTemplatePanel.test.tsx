/**
 * 导出模板面板测试（ADR 0152 / 0177；已从个人设置迁入文档区）.
 *
 * 覆盖：内置 / 自定义分组与默认标记、修改配置后保存（PUT config）、
 * 内置模板只能另存为、设为默认、删除、示例预览按当前配置请求、
 * viewer 只读、未进入工作区空态；以及选项口径（字号中文号名映射、预览样式）。
 */

import { describe, expect, it, vi } from 'vitest'
import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { Route, Routes } from 'react-router-dom'
import ExportTemplatePanel from './ExportTemplatePanel'
import { renderProviders } from '@/test/render-providers'
import { server } from '@/test/msw'
import { NUMBERING_OPTIONS, fontPtLabel, numberingPrefix, pageNumberText, previewStyles } from './templateOptions'
import type { ExportTemplateConfig, ExportTemplateItem } from '@/api'

/** 一份最小可用配置（结构与后端 ExportTemplateConfig 一致） */
function makeConfig(patch: Partial<ExportTemplateConfig['body']> = {}): ExportTemplateConfig {
  return {
    page: { paper: 'A4', margin_top: 2.54, margin_bottom: 2.54, margin_left: 2.54, margin_right: 2.54 },
    header_footer: { header_text: '', page_number: 'none', first_page_different: false, font_size: 8 },
    body: {
      latin_font: 'Calibri',
      east_asia_font: 'Calibri',
      size: 10.5,
      bold: false,
      align: 'left',
      color: '#000000',
      line_spacing_rule: 'multiple',
      line_spacing: 1.08,
      line_spacing_pt: 15,
      space_before: 0,
      space_after: 8,
      first_line_indent_chars: 0,
      char_spacing: 0,
      widow_control: true,
      keep_with_next: false,
      ...patch,
    },
    headings: Array.from({ length: 6 }, (_, index) => ({
      latin_font: 'Calibri',
      east_asia_font: 'Calibri',
      size: [18, 15, 13, 12, 11, 10.5][index],
      bold: true,
      color: '#000000',
      align: 'left',
      space_before: 12,
      space_after: 6,
      first_line_indent_chars: 0,
      keep_with_next: true,
    })),
    numbering: { heading: 'none' },
    table: {
      style: 'single',
      header_bg: '#E6EEF5',
      header_color: '#1A5276',
      header_bold: true,
      latin_font: 'Calibri',
      east_asia_font: 'Calibri',
      size: 10.5,
      border_color: '#000000',
      header_repeat: true,
      zebra: false,
      cell_valign: 'top',
    },
    captions: {
      figure: { enabled: false, position: 'below', numbering: 'n', size: 9, align: 'center' },
      table: { enabled: false, position: 'above', numbering: 'n', size: 9, align: 'center' },
    },
    lists: { indent_pt: 16, hanging_pt: 14, space_after: 2, marker: 'bullet' },
    code: {
      latin_font: 'Courier New',
      east_asia_font: 'Courier New',
      size: 9,
      bg: '#F6F8FA',
      border: '#E5E7EB',
      left_bar: false,
    },
  }
}

const BUILTIN_RESEARCH: ExportTemplateItem = {
  ref: 'builtin:research',
  name: '研究报告',
  description: '企业通用规范',
  source: 'builtin',
  is_default: false,
  config: makeConfig({ east_asia_font: '宋体', size: 12, first_line_indent_chars: 2 }),
  updated_at: null,
}

const BUILTIN_THESIS: ExportTemplateItem = {
  ref: 'builtin:thesis',
  name: '论文',
  description: '宋体 12pt',
  source: 'builtin',
  is_default: false,
  config: makeConfig({ east_asia_font: '宋体', size: 12, first_line_indent_chars: 2 }),
  updated_at: null,
}

const CUSTOM_DEFAULT: ExportTemplateItem = {
  ref: '7',
  name: '公司报告',
  description: '内部规范',
  source: 'custom',
  is_default: true,
  config: makeConfig({ east_asia_font: '仿宋', size: 14 }),
  updated_at: '2026-11-25T10:00:00Z',
}

interface Calls {
  put: Array<{ id: string; body: Record<string, unknown> }>
  post: Array<Record<string, unknown>>
  del: string[]
  preview: Array<{ format: string; body: Record<string, unknown> }>
}

function setupHandlers(options: { role?: string; items?: ExportTemplateItem[]; defaultRef?: string } = {}): Calls {
  const calls: Calls = { put: [], post: [], del: [], preview: [] }
  const items = options.items ?? [BUILTIN_RESEARCH, BUILTIN_THESIS, CUSTOM_DEFAULT]
  const defaultRef = options.defaultRef ?? CUSTOM_DEFAULT.ref
  server.use(
    http.get('/api/v1/workspaces', () =>
      HttpResponse.json([
        {
          id: 1,
          name: '测试工作区',
          modules: ['documents'],
          current_user_role: options.role ?? 'owner',
        },
      ]),
    ),
    http.get('/api/v1/workspaces/:wid/documents/templates', () =>
      HttpResponse.json({ items, total: items.length, default_ref: defaultRef }),
    ),
    http.put('/api/v1/workspaces/:wid/documents/templates/:id', async ({ request, params }) => {
      const body = (await request.json()) as Record<string, unknown>
      calls.put.push({ id: String(params.id), body })
      const target = items.find(item => item.ref === String(params.id))
      return HttpResponse.json({ ...(target ?? CUSTOM_DEFAULT), ...body })
    }),
    http.post('/api/v1/workspaces/:wid/documents/templates', async ({ request }) => {
      const body = (await request.json()) as Record<string, unknown>
      calls.post.push(body)
      return HttpResponse.json(
        { ...CUSTOM_DEFAULT, ref: '9', name: String(body.name), config: body.config ?? CUSTOM_DEFAULT.config },
        { status: 201 },
      )
    }),
    http.delete('/api/v1/workspaces/:wid/documents/templates/:id', ({ params }) => {
      calls.del.push(String(params.id))
      return HttpResponse.json({ deleted: true, default_ref: 'builtin:research', was_default: true })
    }),
    http.post('/api/v1/workspaces/:wid/documents/templates/preview', async ({ request }) => {
      const url = new URL(request.url)
      calls.preview.push({
        format: url.searchParams.get('format') ?? '',
        body: (await request.json()) as Record<string, unknown>,
      })
      return new HttpResponse(new Blob(['PK']), { status: 200 })
    }),
  )
  return calls
}

/** antd 会把 data-testid 透传到原生 input / 或落在容器上，两种都兼容 */
function inputOf(testId: string): HTMLInputElement {
  const element = screen.getByTestId(testId)
  return (element.tagName === 'INPUT' ? element : element.querySelector('input')) as HTMLInputElement
}

function renderPanel(route = '/w/1/documents') {
  // useParams 需要真实路由结构；无匹配的路径同时给一个兜底路由（模拟「无工作区」场景）
  return renderProviders(
    <Routes>
      <Route path="/w/:wid/*" element={<ExportTemplatePanel />} />
      <Route path="*" element={<ExportTemplatePanel />} />
    </Routes>,
    { route },
  )
}

describe('ExportTemplatePanel', () => {
  it('未进入工作区时提示先进入工作区', async () => {
    renderPanel('/settings')
    expect(await screen.findByText('模板属于工作区')).toBeInTheDocument()
    expect(screen.queryByTestId('template-list')).not.toBeInTheDocument()
  })

  it('渲染内置与自定义分组，并标记默认模板', async () => {
    setupHandlers()
    renderPanel()
    expect(await screen.findByTestId('template-list')).toBeInTheDocument()
    expect(screen.getByText('内置模板')).toBeInTheDocument()
    expect(screen.getByText('自定义模板')).toBeInTheDocument()
    expect(screen.getByTestId('template-item-builtin:thesis')).toHaveTextContent('论文')
    expect(screen.getByTestId('template-item-7')).toHaveTextContent('公司报告')
    // 默认模板自动选中并在列表里打「默认」标记
    expect(screen.getByTestId('template-item-7')).toHaveTextContent('默认')
  })

  it('修改正文字号后保存：PUT 携带完整 config', async () => {
    const calls = setupHandlers()
    renderPanel()
    await screen.findByTestId('template-section-body')
    fireEvent.change(inputOf('template-body-size'), { target: { value: '13.5' } })
    fireEvent.click(screen.getByTestId('template-save-btn'))
    await waitFor(() => expect(calls.put).toHaveLength(1))
    const body = calls.put[0].body as { config: ExportTemplateConfig }
    expect(calls.put[0].id).toBe('7')
    expect(body.config.body.size).toBeCloseTo(13.5, 1)
  })

  it('内置模板只读：不提供保存，另存为会用当前配置新建', async () => {
    const calls = setupHandlers()
    renderPanel()
    fireEvent.click(await screen.findByTestId('template-item-builtin:thesis'))
    // 内置模板不再有「只读」提示条：只读能力由「无保存按钮 + 只读摘要」表达
    expect(screen.getByText('内置模板')).toBeInTheDocument()
    expect(screen.queryByTestId('template-save-btn')).not.toBeInTheDocument()

    fireEvent.click(screen.getByTestId('template-save-as-btn'))
    const nameInput = await screen.findByTestId('template-save-as-name')
    fireEvent.change(nameInput, { target: { value: '论文（自定义）' } })
    fireEvent.click(within(await screen.findByRole('dialog')).getByRole('button', { name: /^另\s*存\s*为$/ }))
    await waitFor(() => expect(calls.post).toHaveLength(1))
    expect(calls.post[0].name).toBe('论文（自定义）')
    expect((calls.post[0].config as ExportTemplateConfig).body.east_asia_font).toBe('宋体')
  })

  it('设为默认走 PUT is_default', async () => {
    const calls = setupHandlers({ items: [BUILTIN_RESEARCH, { ...CUSTOM_DEFAULT, is_default: false }] })
    renderPanel()
    fireEvent.click(await screen.findByTestId('template-item-7'))
    fireEvent.click(await screen.findByTestId('template-default-btn'))
    await waitFor(() => expect(calls.put).toHaveLength(1))
    expect(calls.put[0].body).toEqual({ is_default: true })
  })

  it('删除自定义模板并回落到默认引用', async () => {
    const calls = setupHandlers()
    renderPanel()
    fireEvent.click(await screen.findByTestId('template-item-7'))
    fireEvent.click(await screen.findByTestId('template-delete-btn'))
    // 二次确认弹窗的确认按钮（antd 会给两个汉字的按钮自动插空格 → 用正则匹配并限定在弹窗内）
    const dialog = await screen.findByRole('dialog')
    fireEvent.click(within(dialog).getByRole('button', { name: /^删\s*除$/ }))
    await waitFor(() => expect(calls.del).toEqual(['7']))
  })

  it('示例预览按当前（未保存）配置请求 docx / pdf', async () => {
    const calls = setupHandlers()
    renderPanel()
    await screen.findByTestId('template-section-body')
    fireEvent.change(inputOf('template-body-size'), { target: { value: '14' } })
    fireEvent.click(screen.getByTestId('template-preview-btn'))
    await waitFor(() => expect(calls.preview).toHaveLength(1))
    expect(calls.preview[0].format).toBe('docx')
    expect((calls.preview[0].body.config as ExportTemplateConfig).body.size).toBeCloseTo(14, 1)

    fireEvent.click(screen.getByTestId('template-preview-pdf-btn'))
    await waitFor(() => expect(calls.preview).toHaveLength(2))
    expect(calls.preview[1].format).toBe('pdf')
  })

  it('viewer 只读：提示无写权限且不显示保存按钮', async () => {
    setupHandlers({ role: 'viewer' })
    renderPanel()
    fireEvent.click(await screen.findByTestId('template-item-7'))
    expect((await screen.findAllByText(/只读浏览/)).length).toBeGreaterThan(0)
    expect(screen.queryByTestId('template-save-btn')).not.toBeInTheDocument()
    expect(screen.queryByTestId('template-delete-btn')).not.toBeInTheDocument()
  })

  it('预览覆盖模板控制的全部要素（标题 / 正文 / 列表 / 表格 / 代码 / 引用）', async () => {
    setupHandlers()
    renderPanel()
    const preview = await screen.findByTestId('template-preview')
    expect(preview).toHaveTextContent('概述')
    expect(preview).toHaveTextContent('背景与方法')
    expect(preview).toHaveTextContent('列表项一')
    expect(preview).toHaveTextContent('覆盖率')
    expect(screen.getByTestId('preview-code')).toHaveTextContent('hello template')
    expect(preview).toHaveTextContent('引用块')
    // 默认模板未启用页眉 / 页码 / 题注：对应要素不渲染
    expect(screen.queryByTestId('preview-footer')).not.toBeInTheDocument()
    expect(screen.queryByTestId('preview-table-caption')).not.toBeInTheDocument()
  })

  it('预览按模板显示标题编号 / 页眉页码 / 图表题注', async () => {
    const thesis = makeConfig({ east_asia_font: '宋体', size: 12, first_line_indent_chars: 2 })
    setupHandlers({
      items: [
        BUILTIN_RESEARCH,
        {
          ...BUILTIN_THESIS,
          config: {
            ...thesis,
            header_footer: { ...thesis.header_footer, header_text: '某某公司', page_number: 'page_of_total' },
            numbering: { heading: 'chapter_chinese' },
            captions: {
              figure: { enabled: true, position: 'below', numbering: 'n', size: 9, align: 'center' },
              table: { enabled: true, position: 'above', numbering: 'n', size: 9, align: 'center' },
            },
          },
        },
      ],
      defaultRef: 'builtin:thesis',
    })
    renderPanel()
    expect(await screen.findByText('第一章 概述')).toBeInTheDocument()
    expect(screen.getByTestId('preview-header')).toHaveTextContent('某某公司')
    expect(screen.getByTestId('preview-footer')).toHaveTextContent('第 1 页 共 3 页')
    expect(screen.getByTestId('preview-table-caption')).toHaveTextContent('表 1')
    expect(screen.getByTestId('preview-figure-caption')).toHaveTextContent('图 1')
  })
})

describe('templateOptions', () => {
  it('中文字号映射：有号数显示号名，无匹配只显示磅值', () => {
    expect(fontPtLabel(12)).toBe('小四 12pt')
    expect(fontPtLabel(16)).toBe('三号 16pt')
    expect(fontPtLabel(13.5)).toBe('13.5pt')
  })

  it('标题编号方案按文体规范生成（公文层次序数四级）并在下拉里标注推荐文体', () => {
    expect(numberingPrefix('none', 1, [1, 0, 0, 0, 0, 0])).toBe('')
    expect(numberingPrefix('arabic_multilevel', 2, [1, 2, 0, 0, 0, 0])).toBe('1.2')
    expect(numberingPrefix('chapter_chinese', 1, [3, 0, 0, 0, 0, 0])).toBe('第三章')
    expect(numberingPrefix('cn_ordinal', 1, [2, 5, 3, 4, 0, 0])).toBe('二、')
    expect(numberingPrefix('cn_ordinal', 2, [2, 5, 3, 4, 0, 0])).toBe('（五）')
    expect(numberingPrefix('cn_ordinal', 3, [2, 5, 3, 4, 0, 0])).toBe('3.')
    expect(numberingPrefix('cn_ordinal', 4, [2, 5, 3, 4, 0, 0])).toBe('（4）')
    expect(NUMBERING_OPTIONS.find(o => o.value === 'cn_ordinal')?.label).toContain('GB/T 9704')
    expect(NUMBERING_OPTIONS.find(o => o.value === 'chapter_chinese')?.label).toContain('论文')
    expect(NUMBERING_OPTIONS.find(o => o.value === 'arabic_multilevel')?.label).toContain('研究报告')
  })

  it('页脚页码文案与导出侧一致', () => {
    expect(pageNumberText('none')).toBe('')
    expect(pageNumberText('plain')).toBe('1')
    expect(pageNumberText('page')).toBe('第 1 页')
    expect(pageNumberText('page_of_total')).toBe('第 1 页 共 3 页')
  })

  it('previewStyles 把配置折成内联样式', () => {
    const styles = previewStyles(makeConfig({ east_asia_font: '宋体', size: 12, first_line_indent_chars: 2 }))
    expect(styles.body.fontFamily).toContain('宋体')
    expect(styles.body.fontSize).toBe(12)
    expect(styles.body.textIndent).toBe('2em')
    expect(styles.headings(1).fontSize).toBe(18)
  })
})

describe('DocumentTemplatesPage（文档区入口）', () => {
  it('页面容器内渲染模板面板与说明（入口在文档区而非个人设置）', async () => {
    setupHandlers()
    const { default: DocumentTemplatesPage } = await import('@/pages/documents/DocumentTemplatesPage')
    renderProviders(
      <Routes>
        <Route path="/w/:wid/documents/templates" element={<DocumentTemplatesPage />} />
      </Routes>,
      { route: '/w/1/documents/templates' },
    )
    expect(await screen.findByTestId('document-templates-page')).toBeInTheDocument()
    expect(screen.getByText('导出模板', { exact: true })).toBeInTheDocument()
    expect(await screen.findByTestId('template-list')).toBeInTheDocument()
  })
})

describe('ExportTemplatePanel 布局交互（分组折叠 / 新建 / 预览收起）', () => {
  it('自定义分组在上、内置分组在下，两组可分别展开收起', async () => {
    setupHandlers()
    renderPanel()
    const group = await screen.findByTestId('template-group-builtin')
    expect(screen.getByTestId('template-item-builtin:research')).toBeInTheDocument()
    expect(group).toHaveAttribute('aria-expanded', 'true')
    // 分组顺序：自定义在上，内置在下（需求方口径）
    const groups = screen.getAllByTestId(/^template-group-/)
    expect(groups.map(node => node.getAttribute('data-testid'))).toEqual([
      'template-group-custom',
      'template-group-builtin',
    ])

    fireEvent.click(group)
    expect(group).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByTestId('template-item-builtin:research')).not.toBeInTheDocument()
    // 自定义分组不受影响（各自独立）
    expect(screen.getByTestId('template-group-custom')).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByTestId('template-item-7')).toBeInTheDocument()

    fireEvent.click(group)
    expect(screen.getByTestId('template-item-builtin:research')).toBeInTheDocument()
  })

  it('页头「新建模板」按内置预设创建并选中新模板', async () => {
    const calls = setupHandlers()
    renderPanel()
    await waitFor(() => expect(screen.getByTestId('template-create-btn')).toBeEnabled())
    fireEvent.click(screen.getByTestId('template-create-btn'))

    const dialog = await screen.findByRole('dialog')
    fireEvent.change(within(dialog).getByTestId('template-create-name'), { target: { value: '新规范' } })
    fireEvent.click(within(dialog).getByRole('button', { name: /^创\s*建$/ }))

    await waitFor(() => expect(calls.post).toHaveLength(1))
    expect(calls.post[0]).toMatchObject({ name: '新规范', preset_key: 'research' })
  })

  it('预览可收起 / 展开（默认展开，收起后不渲染预览内容）', async () => {
    setupHandlers()
    renderPanel()
    expect(await screen.findByTestId('template-preview')).toBeInTheDocument()

    fireEvent.click(screen.getByTestId('template-preview-toggle'))
    await waitFor(() => expect(screen.queryByTestId('template-preview')).not.toBeInTheDocument())
    expect(screen.getByTestId('template-preview-toggle')).toHaveAttribute('aria-expanded', 'false')

    fireEvent.click(screen.getByTestId('template-preview-toggle'))
    expect(await screen.findByTestId('template-preview')).toBeInTheDocument()
  })

  it('动作键带文字：另存为 / 保存 / 设为默认 / 示例 Word / 示例 PDF', async () => {
    setupHandlers()
    renderPanel()
    fireEvent.click(await screen.findByTestId('template-item-7'))
    expect(await screen.findByTestId('template-save-as-btn')).toHaveTextContent('另存为')
    expect(screen.getByTestId('template-save-btn')).toHaveTextContent('保存')
    expect(screen.getByTestId('template-preview-btn')).toHaveTextContent('示例 Word')
    expect(screen.getByTestId('template-preview-pdf-btn')).toHaveTextContent('示例 PDF')
  })
})

describe('templateFile（导入 / 导出文件格式）', () => {
  it('导出文本可回读：kind / version / 配置完整', async () => {
    const { buildTemplateFile, parseTemplateFile, templateFileText, templateFileName } = await import('./templateFile')
    const entry = { name: '公司规范', description: '说明', config: makeConfig({ east_asia_font: '宋体' }) }
    const parsedWhole = buildTemplateFile([entry])
    expect(parsedWhole.kind).toBe('cndb-document-template')
    expect(parsedWhole.version).toBe(1)
    const back = parseTemplateFile(templateFileText([entry]))
    expect(back).toHaveLength(1)
    expect(back[0].name).toBe('公司规范')
    expect(back[0].config.body.east_asia_font).toBe('宋体')
    expect(templateFileName('报告/规范')).toBe(`文档模板-报告_规范-${new Date().toISOString().slice(0, 10).replace(/-/g, '')}.json`)
  })

  it('兼容单条（无 templates 包裹）与多条', async () => {
    const { parseTemplateFile } = await import('./templateFile')
    const single = JSON.stringify({ name: '单条', config: makeConfig() })
    expect(parseTemplateFile(single).map(e => e.name)).toEqual(['单条'])
    const multi = JSON.stringify({
      kind: 'cndb-document-template',
      version: 1,
      templates: [
        { name: 'A', config: makeConfig() },
        { name: 'B', description: 'x', config: makeConfig() },
      ],
    })
    expect(parseTemplateFile(multi).map(e => e.name)).toEqual(['A', 'B'])
  })

  it('非法文件给出中文错误', async () => {
    const { parseTemplateFile } = await import('./templateFile')
    expect(() => parseTemplateFile('not json')).toThrow('不是合法的 JSON 文件')
    expect(() => parseTemplateFile(JSON.stringify({ kind: 'other' }))).toThrow('不是晶格协同的文档模板文件')
    expect(() => parseTemplateFile(JSON.stringify({ kind: 'cndb-document-template', version: 99, templates: [] }))).toThrow(
      '版本过新',
    )
    expect(() => parseTemplateFile(JSON.stringify({ config: makeConfig() }))).toThrow('缺少名称')
    expect(() => parseTemplateFile(JSON.stringify({ name: 'x' }))).toThrow('缺少配置')
    expect(() => parseTemplateFile(JSON.stringify({ templates: [] }))).toThrow('没有任何模板')
  })

  it('导入名称去重：同名加「（导入）」「（导入 2）」', async () => {
    const { suggestImportName } = await import('./templateFile')
    const existing = new Set(['模板', '模板（导入）'])
    expect(suggestImportName('新模板', existing)).toBe('新模板')
    expect(suggestImportName('模板', existing)).toBe('模板（导入 2）')
  })
})

describe('ExportTemplatePanel 导入 / 导出', () => {
  it('导出当前模板为 JSON 文件（blob 内容含配置）', async () => {
    setupHandlers()
    const captured: Blob[] = []
    const createSpy = vi.fn((blob: Blob) => {
      captured.push(blob)
      return 'blob:template'
    })
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: createSpy })
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() })

    renderPanel()
    fireEvent.click(await screen.findByTestId('template-item-7'))
    fireEvent.click(await screen.findByTestId('template-export-btn'))

    await waitFor(() => expect(createSpy).toHaveBeenCalled())
    const text = await captured[0].text()
    const parsed = JSON.parse(text) as { kind: string; templates: Array<{ name: string }> }
    expect(parsed.kind).toBe('cndb-document-template')
    expect(parsed.templates[0].name).toBe('公司报告')
  })

  it('导入模板文件：逐条创建并跳过重名失败项', async () => {
    const calls = setupHandlers()
    renderPanel()
    await waitFor(() => expect(screen.getByTestId('template-import-btn')).toBeEnabled())

    const file = new File(
      [
        JSON.stringify({
          kind: 'cndb-document-template',
          version: 1,
          templates: [
            { name: '公司报告', config: makeConfig() },
            { name: '新导入模板', description: '来自文件', config: makeConfig({ size: 14 }) },
          ],
        }),
      ],
      'templates.json',
      { type: 'application/json' },
    )
    const input = screen.getByTestId('template-import-input') as HTMLInputElement
    fireEvent.change(input, { target: { files: [file] } })

    await waitFor(() => expect(calls.post.length).toBeGreaterThanOrEqual(2))
    // 第一条与已有自定义模板同名 → 自动改名「公司报告（导入）」
    expect(calls.post[0]).toMatchObject({ name: '公司报告（导入）', description: '' })
    expect(calls.post[1]).toMatchObject({ name: '新导入模板', description: '来自文件' })
    expect((calls.post[1].config as ExportTemplateConfig).body.size).toBeCloseTo(14, 1)
  })

  it('导入非法文件时不发请求并提示', async () => {
    const calls = setupHandlers()
    renderPanel()
    await waitFor(() => expect(screen.getByTestId('template-import-btn')).toBeEnabled())
    const file = new File(['not-json'], 'bad.json', { type: 'application/json' })
    const input = screen.getByTestId('template-import-input') as HTMLInputElement
    fireEvent.change(input, { target: { files: [file] } })
    await waitFor(() => expect(calls.post).toHaveLength(0))
  })
})
