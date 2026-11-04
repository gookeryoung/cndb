import { describe, expect, it, beforeEach } from 'vitest'
import { http, HttpResponse } from 'msw'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import TemplatesPage from './TemplatesPage'
import { renderProviders } from '@/test/render-providers'
import { server } from '@/test/msw'

const TEMPLATE = {
  id: 1,
  name: '科研项目全生命周期管理',
  description: '三阶段科研模板',
  category: '科研管理',
  modules: ['tables', 'documents'],
  spec: {
    forms: [{ key: 'apply', name: '项目申报', fields: [{ name: '项目名称', type: 'text', required: true }] }],
    documents: [{ key: 'proposal', title: '立项申请书', required: true }],
    stages: [{ key: 'proposal', name: '立项申报', order: 1, forms: ['apply'], documents: ['proposal'] }],
  },
  version: 3,
  is_builtin: true,
  created_by_id: 1,
  updated_at: '2026-11-04T03:00:00+00:00',
  counts: { stage_count: 1, form_count: 1, field_count: 1, document_rule_count: 1 },
  workspace_count: 2,
}

describe('TemplatesPage', () => {
  beforeEach(() => {
    server.use(
      http.get('/api/v1/workspace-templates', () => HttpResponse.json([TEMPLATE])),
      http.post('/api/v1/workspace-templates', async ({ request }) => {
        const body = await request.json() as Record<string, unknown>
        return HttpResponse.json({ ...TEMPLATE, id: 2, name: body.name, is_builtin: false, version: 1 })
      }),
    )
  })

  it('renders template details and opens the spec editor', async () => {
    renderProviders(<TemplatesPage />)
    expect(await screen.findByText('科研项目全生命周期管理')).toBeInTheDocument()
    expect(screen.getByText(/2 个工作区使用/)).toBeInTheDocument()

    await userEvent.click(screen.getByText('科研项目全生命周期管理'))
    expect(await screen.findByText(/阶段 1 · 立项申报/)).toBeInTheDocument()

    await userEvent.click(screen.getByTestId('create-template-btn'))
    expect(await screen.findByTestId('template-editor-modal')).toBeInTheDocument()
    await userEvent.type(screen.getByTestId('template-name'), '我的科研模板')
    await userEvent.click(screen.getByRole('button', { name: '创建模板' }))
    expect(await screen.findByText('模板已创建')).toBeInTheDocument()
  })
})
