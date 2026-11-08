import { describe, expect, it } from 'vitest'
import { http, HttpResponse } from 'msw'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes, useLocation } from 'react-router-dom'
import ProjectsPage from './ProjectsPage'
import { renderProviders } from '@/test/render-providers'
import { server } from '@/test/msw'

/** 导航落点探针：展示 pathname + query，断言点击项目后进入的项目上下文 */
function TablesProbe() {
  const location = useLocation()
  return <div data-testid="tables-route">{location.pathname + location.search}</div>
}

function renderPage(route = '/w/10/projects') {
  return renderProviders(
    <Routes>
      <Route path="/w/:wid/projects" element={<ProjectsPage />} />
      <Route path="/w/:wid/tables" element={<TablesProbe />} />
    </Routes>,
    { route },
  )
}

const ITEM = {
  project_row_id: 7,
  title: '智能监测项目',
  stage_key: 'proposal',
  stage_name: '立项申报',
  gate_satisfied: false,
  missing_forms: ['实施方案'],
  missing_documents: ['立项批复'],
  initialized: true,
}

describe('ProjectsPage', () => {
  it('lists projects with stage, gate and missing items', async () => {
    server.use(
      http.get('/api/v1/workspaces/:wid/projects', () =>
        HttpResponse.json({
          project_mode: 'project',
          root_form: 'project_application',
          link_field: '所属项目',
          title_field: '项目名称',
          items: [ITEM],
          total: 1,
        }),
      ),
    )
    renderPage()
    expect(await screen.findByText('智能监测项目')).toBeInTheDocument()
    expect(screen.getByText('项目清单（1）')).toBeInTheDocument()
    expect(screen.getByText('立项申报')).toBeInTheDocument()
    expect(screen.getByText('待补齐')).toBeInTheDocument()
    expect(screen.getByText('实施方案')).toBeInTheDocument()
    expect(screen.getByText('立项批复')).toBeInTheDocument()
  })

  it('fills documents for every project missing items in one click', async () => {
    const filled: number[] = []
    server.use(
      http.get('/api/v1/workspaces/:wid/projects', () =>
        HttpResponse.json({
          project_mode: 'project',
          root_form: 'project_application',
          link_field: '所属项目',
          title_field: '项目名称',
          items: [ITEM, { ...ITEM, project_row_id: 8, title: '第二个项目' }],
          total: 2,
        }),
      ),
      http.post('/api/v1/workspaces/:wid/projects/:row/documents', ({ params }) => {
        filled.push(Number(params.row))
        return HttpResponse.json({ created: 1, documents: [] })
      }),
    )
    renderPage()
    await screen.findByText('智能监测项目')
    await userEvent.click(screen.getByRole('button', { name: /全部补文档/ }))
    expect(await screen.findByText(/已为 2 个项目补建 2 份文档/)).toBeInTheDocument()
    expect(filled).toEqual([7, 8])
  })

  it('enters the project context from a project row', async () => {
    server.use(
      http.get('/api/v1/workspaces/:wid/projects', () =>
        HttpResponse.json({
          project_mode: 'project',
          root_form: 'project_application',
          link_field: '所属项目',
          title_field: '项目名称',
          items: [ITEM],
          total: 1,
        }),
      ),
    )
    renderPage()
    await userEvent.click(await screen.findByRole('button', { name: '智能监测项目' }))
    expect(await screen.findByTestId('tables-route')).toHaveTextContent('/w/10/tables?project=7')
  })

  it('offers to enable project mode for workspace-mode workspaces', async () => {
    let enabled = false
    server.use(
      http.get('/api/v1/workspaces/:wid/projects', () =>
        HttpResponse.json({
          project_mode: 'workspace',
          root_form: null,
          link_field: null,
          title_field: null,
          items: [],
          total: 0,
        }),
      ),
      http.post('/api/v1/workspaces/:wid/project-mode/enable', () => {
        enabled = true
        return HttpResponse.json({ project_mode: 'project', projects: 1, initialized: 1, documents_created: 2 })
      }),
    )
    renderPage()
    expect(await screen.findByText('当前工作区按工作区级管理')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /启用项目级管理/ }))
    expect(await screen.findByText(/项目级管理已启用/)).toBeInTheDocument()
    expect(enabled).toBe(true)
  })
})
