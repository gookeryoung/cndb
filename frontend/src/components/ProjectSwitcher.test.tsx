import { describe, expect, it } from 'vitest'
import { http, HttpResponse } from 'msw'
import { screen, waitFor } from '@testing-library/react'
import { useSearchParams } from 'react-router-dom'
import ProjectSwitcher from './ProjectSwitcher'
import { renderProviders } from '@/test/render-providers'
import { server } from '@/test/msw'

/** 把当前 URL query 展示出来，便于断言自动写入的 ?project= */
function UrlProbe() {
  const [params] = useSearchParams()
  return <div data-testid="url-query">{params.toString()}</div>
}

function mockProjects(items: unknown[], projectMode: 'workspace' | 'project' = 'project') {
  server.use(
    http.get('/api/v1/workspaces/:wid/projects', () =>
      HttpResponse.json({
        project_mode: projectMode,
        root_form: 'project_application',
        link_field: '所属项目',
        title_field: '项目名称',
        items,
        total: items.length,
      }),
    ),
  )
}

function renderSwitcher(route = '/w/10/data-flow') {
  return renderProviders(
    <>
      <ProjectSwitcher wid="10" />
      <UrlProbe />
    </>,
    { route },
  )
}

const ITEM = {
  project_row_id: 7,
  title: '智能监测项目',
  stage_key: 'proposal',
  stage_name: '立项申报',
  gate_satisfied: false,
  missing_forms: [],
  missing_documents: [],
  initialized: true,
}

describe('ProjectSwitcher', () => {
  it('auto-selects the only project and hides the switcher (single-project mode)', async () => {
    mockProjects([ITEM])
    renderSwitcher()
    await waitFor(() => expect(screen.getByTestId('url-query')).toHaveTextContent('project=7'))
    expect(screen.queryByTestId('project-switcher')).not.toBeInTheDocument()
  })

  it('renders the switcher for multiple projects without rewriting the URL', async () => {
    mockProjects([
      ITEM,
      { ...ITEM, project_row_id: 8, title: '第二个项目', stage_name: '过程实施' },
    ])
    renderSwitcher('/w/10/data-flow?project=8')
    expect(await screen.findByTestId('project-switcher')).toBeInTheDocument()
    expect(screen.getByTestId('url-query')).toHaveTextContent('project=8')
  })

  it('stays hidden in workspace mode', async () => {
    mockProjects([ITEM], 'workspace')
    renderSwitcher()
    // 等接口返回后仍不渲染切换器，也不写 project 参数
    await waitFor(() => expect(screen.queryByTestId('project-switcher')).not.toBeInTheDocument())
    expect(screen.getByTestId('url-query')).toHaveTextContent('')
  })
})
