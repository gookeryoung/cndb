import { describe, expect, it, beforeEach } from 'vitest'
import { http, HttpResponse } from 'msw'
import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import WorkspaceLifecyclePanel from './WorkspaceLifecyclePanel'
import { renderProviders } from '@/test/render-providers'
import { server } from '@/test/msw'

const LIFECYCLE = {
  template_id: 1,
  template_name: '科研项目全生命周期管理',
  template_version: 1,
  current_version: 1,
  current_stage: 'proposal',
  current_stage_index: 0,
  stage_count: 2,
  can_advance: false,
  next_stage: { key: 'execution', name: '过程实施' },
  stages: [
    {
      key: 'proposal', name: '立项申报', description: '提交申报表与立项申请书', order: 1,
      is_current: true, is_completed: false, gate_satisfied: false,
      forms: [{ key: 'apply', name: '项目申报', required: true, table_exists: true, row_count: 0, satisfied: false }],
      documents: [{ key: 'proposal', title: '立项申请书', required: true, exists: true, satisfied: true }],
    },
    {
      key: 'execution', name: '过程实施', description: '', order: 2,
      is_current: false, is_completed: false, gate_satisfied: false,
      forms: [], documents: [],
    },
  ],
  history: [
    { from: null, to: 'proposal', at: '2026-11-04T03:00:00+00:00', by: 1, reason: '创建', forced: false },
  ],
  version_mismatch: false,
}

const ADVANCED = {
  ...LIFECYCLE,
  current_stage: 'execution',
  current_stage_index: 1,
  can_advance: false,
  next_stage: null,
  stages: [
    { ...LIFECYCLE.stages[0], is_current: false, is_completed: true },
    { ...LIFECYCLE.stages[1], is_current: true, is_completed: false },
  ],
}

describe('WorkspaceLifecyclePanel', () => {
  let advanced = false
  beforeEach(() => {
    advanced = false
    server.use(
      http.get('/api/v1/workspaces/:wid/lifecycle', () => HttpResponse.json(advanced ? ADVANCED : LIFECYCLE)),
      http.post('/api/v1/workspaces/:wid/lifecycle/advance', () => {
        advanced = true
        return HttpResponse.json(ADVANCED)
      }),
      http.get('/api/v1/workspace-templates', () => HttpResponse.json([])),
    )
  })

  it('renders stage gate details and forces advance when gate fails', async () => {
    renderProviders(<WorkspaceLifecyclePanel wid="10" canAdvance canManageTemplate />)
    expect(await screen.findByTestId('workspace-lifecycle-panel')).toBeInTheDocument()
    expect(screen.getByText('项目申报：0 条记录')).toBeInTheDocument()

    await userEvent.click(screen.getByTestId('lifecycle-advance-btn'))
    await screen.findAllByText('门禁未通过，仍要推进？')
    fireEvent.click(within(document.querySelector('.ant-modal-confirm') as HTMLElement).getByRole('button', { name: '强制推进' }))
    await waitFor(() => expect(screen.getByTestId('lifecycle-advance-btn')).toHaveTextContent('已是最后阶段'))
  })

  it('shows empty state when workspace has no template', async () => {
    server.use(
      http.get('/api/v1/workspaces/:wid/lifecycle', () => HttpResponse.json({ detail: '该工作区未使用模板' }, { status: 404 })),
    )
    renderProviders(<WorkspaceLifecyclePanel wid="11" canAdvance={false} canManageTemplate={false} />)
    expect(await screen.findByText('该工作区还没有使用模板')).toBeInTheDocument()
  })
})
