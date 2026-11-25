/**
 * 个人设置「模板」页签测试（ADR 0152）.
 *
 * 覆盖：内置 / 自定义分组与默认标记、修改配置后保存（PUT config）、
 * 内置模板只能另存为、设为默认、删除、示例预览按当前配置请求、
 * viewer 只读、未进入工作区空态；以及选项口径（字号中文号名映射、预览样式）。
 */

import { describe, expect, it } from 'vitest'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { Route, Routes } from 'react-router-dom'
import TemplatePanel from './TemplatePanel'
import { renderProviders } from '@/test/render-providers'
import { server } from '@/test/msw'
import { fontPtLabel, previewStyles } from './templateOptions'
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

const BUILTIN_STANDARD: ExportTemplateItem = {
  ref: 'builtin:standard',
  name: '标准',
  description: '系统历史默认视觉',
  source: 'builtin',
  is_default: false,
  config: makeConfig(),
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
  const items = options.items ?? [BUILTIN_STANDARD, BUILTIN_THESIS, CUSTOM_DEFAULT]
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
      HttpResponse.json({ items, default_ref: defaultRef }),
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
      return HttpResponse.json({ deleted: true, default_ref: 'builtin:standard', was_default: true })
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
      <Route path="/w/:wid/*" element={<TemplatePanel />} />
      <Route path="*" element={<TemplatePanel />} />
    </Routes>,
    { route },
  )
}

describe('TemplatePanel', () => {
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
    expect(await screen.findByText('内置模板只读')).toBeInTheDocument()
    expect(screen.queryByTestId('template-save-btn')).not.toBeInTheDocument()

    fireEvent.click(screen.getByTestId('template-save-as-btn'))
    const nameInput = await screen.findByTestId('template-save-as-name')
    fireEvent.change(nameInput, { target: { value: '论文（自定义）' } })
    fireEvent.click(screen.getByRole('button', { name: '另存为' }))
    await waitFor(() => expect(calls.post).toHaveLength(1))
    expect(calls.post[0].name).toBe('论文（自定义）')
    expect((calls.post[0].config as ExportTemplateConfig).body.east_asia_font).toBe('宋体')
  })

  it('设为默认走 PUT is_default', async () => {
    const calls = setupHandlers({ items: [BUILTIN_STANDARD, { ...CUSTOM_DEFAULT, is_default: false }] })
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
    // 二次确认弹窗的确认按钮（antd 会给两个汉字的按钮自动插空格 → 用正则匹配）
    fireEvent.click(await screen.findByRole('button', { name: /^删\s*除$/ }))
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
    expect(await screen.findByText('只读浏览')).toBeInTheDocument()
    expect(screen.queryByTestId('template-save-btn')).not.toBeInTheDocument()
    expect(screen.queryByTestId('template-delete-btn')).not.toBeInTheDocument()
  })

  it('CSS 预览随配置变化（正文字号与标题字号）', async () => {
    setupHandlers()
    renderPanel()
    const preview = await screen.findByTestId('template-preview')
    expect(preview).toHaveTextContent('第一章 概述')
    expect(preview).toHaveTextContent('覆盖率')
  })
})

describe('templateOptions', () => {
  it('中文字号映射：有号数显示号名，无匹配只显示磅值', () => {
    expect(fontPtLabel(12)).toBe('小四 12pt')
    expect(fontPtLabel(16)).toBe('三号 16pt')
    expect(fontPtLabel(13.5)).toBe('13.5pt')
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
    expect(screen.getByText('文档模板', { exact: true })).toBeInTheDocument()
    expect(await screen.findByTestId('template-list')).toBeInTheDocument()
  })
})
