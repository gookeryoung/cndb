import { beforeEach, describe, expect, it, vi } from 'vitest'
import { http, HttpResponse } from 'msw'
import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import TemplateEditorDrawer from './TemplateEditorDrawer'
import { renderProviders } from '@/test/render-providers'
import { server } from '@/test/msw'

const TEMPLATE = {
  id: 1,
  name: '科研项目模板',
  description: '',
  category: '科研',
  modules: ['tables'],
  spec: {
    forms: [{ key: 'apply', name: '申报表', fields: [{ name: '项目名称', type: 'text', required: true }] }],
    documents: [],
    stages: [{ key: 'stage_1', name: '申报', order: 1, forms: ['apply'], documents: [] }],
    flows: [],
  },
  version: 2,
  is_builtin: false,
  created_by_id: 1,
  updated_at: '2026-11-04T03:00:00+00:00',
  counts: { stage_count: 1, form_count: 1, field_count: 1, document_rule_count: 0, flow_count: 0, step_count: 0 },
  workspace_count: 0,
}

describe('TemplateEditorDrawer', () => {
  beforeEach(() => {
    server.use(
      http.post('/api/v1/workspace-templates/1/preview', async ({ request }) => {
        const body = await request.json() as { spec: typeof TEMPLATE.spec }
        return HttpResponse.json({ diff: {}, impact: {}, requires_force: false, spec: body.spec })
      }),
      http.put('/api/v1/workspace-templates/1', async ({ request }) => {
        const body = await request.json() as { spec: typeof TEMPLATE.spec }
        return HttpResponse.json({
          template: { ...TEMPLATE, spec: body.spec, version: 3 },
          sync: { created_tables: 0, added_fields: 1, created_documents: 0, skipped: [] },
        })
      }),
    )
  })

  it('edits fields structurally without touching raw JSON', async () => {
    renderProviders(
      <TemplateEditorDrawer open template={TEMPLATE as never} onClose={vi.fn()} />,
    )
    expect(await screen.findByTestId('template-editor-drawer')).toBeInTheDocument()

    await userEvent.click(screen.getByTestId('outline-form-apply'))
    await userEvent.click(await screen.findByRole('button', { name: /新增字段/ }))

    const modalTitle = await screen.findByText('编辑字段')
    const modal = modalTitle.closest('.ant-modal') as HTMLElement
    const nameInput = within(modal).getAllByRole('textbox')[0]
    await userEvent.clear(nameInput)
    await userEvent.type(nameInput, '预算金额')
    await userEvent.click(within(modal).getByRole('button', { name: '保存字段' }))

    expect((await screen.findAllByText('预算金额')).length).toBeGreaterThan(0)
    expect(screen.getByText('结构通过')).toBeInTheDocument()
  })

  it('keeps structured draft when JSON apply fails', async () => {
    renderProviders(
      <TemplateEditorDrawer open template={TEMPLATE as never} onClose={vi.fn()} />,
    )
    await screen.findByTestId('template-editor-drawer')
    await userEvent.click(screen.getByRole('button', { name: /JSON（高级）/ }))

    const editor = await screen.findByTestId('template-spec-text')
    await userEvent.clear(editor)
    await userEvent.type(editor, '{{')
    await userEvent.click(screen.getByRole('button', { name: '应用 JSON' }))

    expect(await screen.findByText(/JSON 解析失败|Expected property name/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /概览/ }))
    expect(await screen.findByTestId('template-name')).toHaveValue('科研项目模板')
  })
})
