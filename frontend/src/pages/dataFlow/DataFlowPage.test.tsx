import { describe, expect, it, beforeEach } from 'vitest'
import { http, HttpResponse } from 'msw'
import { screen, waitFor } from '@testing-library/react'
import { Route, Routes } from 'react-router-dom'
import userEvent from '@testing-library/user-event'
import DataFlowPage from './DataFlowPage'
import { renderProviders } from '@/test/render-providers'
import { server } from '@/test/msw'

function renderPage(route = '/w/10/data-flow') {
  return renderProviders(
    <Routes><Route path="/w/:wid/data-flow" element={<DataFlowPage />} /></Routes>,
    { route },
  )
}

const FLOW_FORM = {
  key: 'apply',
  name: '项目申报',
  description: '一条记录对应一个科研项目',
  table_id: 101,
  table_name: '项目申报',
  flow: {
    enabled: true,
    list_fields: ['项目名称', '负责人'],
    search_fields: ['项目名称'],
    form_groups: [
      { title: '基本信息', fields: ['项目名称', '负责人'] },
    ],
    detail_groups: [{ title: '基本信息', fields: ['项目名称', '负责人'] }],
    hints: { 负责人: '填写项目负责人' },
    default_values: {},
    allow_create: true,
    allow_edit: true,
    allow_delete: true,
    default_sort: null,
    empty_text: '',
  },
  fields: [
    { name: '项目名称', field_type: 'text', required: true, config: {}, order: 0, hidden: false },
    { name: '负责人', field_type: 'text', required: false, config: {}, order: 1, hidden: false },
  ],
  record_count: 1,
  can_create: true,
  can_edit: true,
  can_delete: true,
}

const FLOW = {
  template_id: 1,
  template_name: '科研项目全生命周期管理',
  template_version: 1,
  current_version: 1,
  current_stage: 'proposal',
  current_stage_index: 0,
  can_advance: false,
  next_stage: { key: 'execution', name: '过程实施' },
  stages: [
    {
      key: 'proposal', name: '立项申报', description: '立项', order: 1,
      is_current: true, is_completed: false, gate_satisfied: false,
      forms: [FLOW_FORM],
    },
    {
      key: 'execution', name: '过程实施', description: '实施', order: 2,
      is_current: false, is_completed: false, gate_satisfied: false, forms: [],
    },
  ],
  flows: [
    {
      key: 'project_lifecycle',
      name: '科研项目全生命周期',
      description: '从立项到结题',
      stage: 'proposal',
      stage_name: '立项申报',
      step_count: 2,
      form_count: 1,
      record_count: 1,
      steps: [
        { key: 'apply', name: '提交申报', description: '填写申报表', form: FLOW_FORM, documents: [] },
        { key: 'approve', name: '人工审批', description: '管理部门审批', form: null, documents: [] },
      ],
    },
    {
      key: 'archive_flow',
      name: '成果归档',
      description: '归档登记流程',
      stage: 'execution',
      stage_name: '过程实施',
      step_count: 1,
      form_count: 0,
      record_count: 0,
      steps: [
        { key: 'archive', name: '归档确认', description: '核对原件与清单', form: null, documents: ['archive_doc'] },
      ],
    },
  ],
}

describe('DataFlowPage', () => {
  beforeEach(() => {
    server.use(
      http.get('/api/v1/workspaces/:wid/data-flow', () => HttpResponse.json(FLOW)),
      http.get('/api/v1/workspaces/:wid/tables/:tid/records', () =>
        HttpResponse.json({
          items: [{ id: 1, 项目名称: '智能监测项目', 负责人: '张伟' }],
          total: 1, offset: 0, limit: 500,
        }),
      ),
      http.post('/api/v1/workspaces/:wid/tables/:tid/records', () =>
        HttpResponse.json({ id: 2, 项目名称: '新项目' }, { status: 201 }),
      ),
    )
  })

  it('renders the left-right flow diagram and maintains data in the right pane', async () => {
    renderPage()
    expect(await screen.findByTestId('data-flow-page')).toBeInTheDocument()
    expect(screen.getByText(/科研项目全生命周期管理/)).toBeInTheDocument()
    expect(screen.getByText(/当前阶段 立项申报/)).toBeInTheDocument()
    // 右侧刷新按钮已移除
    expect(screen.queryByLabelText('刷新数据流程')).not.toBeInTheDocument()
    // 左右列表布局 + 左侧两级流程图
    expect(screen.getByTestId('data-flow-split')).toBeInTheDocument()
    expect(screen.getByTestId('data-flow-diagram')).toHaveTextContent('流程图')
    expect(screen.getByTestId('data-flow-card-project_lifecycle')).toBeInTheDocument()
    expect(screen.getByTestId('data-flow-card-archive_flow')).toBeInTheDocument()
    // 默认展开第一条流程的子过程
    expect(await screen.findByTestId('data-flow-steps-project_lifecycle')).toBeInTheDocument()
    expect(screen.getByTestId('data-flow-step-apply')).toBeInTheDocument()
    expect(screen.getByTestId('data-flow-step-approve')).toBeInTheDocument()
    // 一级 / 二级差异化：一级大图标 + 「一级」标签，二级表单 / 审批图标
    expect(screen.getAllByText('一级')).toHaveLength(2)
    expect(document.querySelector('.cn-flow-diagram-flow-icon')).toBeInTheDocument()
    expect(document.querySelector('.cn-flow-diagram-step-icon.is-form')).toBeInTheDocument()
    expect(document.querySelector('.cn-flow-diagram-step-icon.is-approval')).toBeInTheDocument()
    // 未展开的流程不渲染子过程
    expect(screen.queryByTestId('data-flow-step-archive')).not.toBeInTheDocument()
    expect(await screen.findByText('智能监测项目')).toBeInTheDocument()

    // 内容列表在右栏，不与左侧流程图混排
    const content = screen.getByTestId('data-flow-content')
    expect(content).toContainElement(screen.getByTestId('data-flow-table'))
    expect(screen.getByTestId('data-flow-diagram')).not.toContainElement(screen.getByTestId('data-flow-table'))

    await userEvent.click(screen.getByTestId('data-flow-create'))
    expect(await screen.findByTestId('data-flow-editor')).toBeInTheDocument()
    expect(screen.getByText('基本信息')).toBeInTheDocument()
    expect(screen.getByText(/填写项目负责人/)).toBeInTheDocument()

    const inputs = screen.getAllByPlaceholderText('请输入...')
    await userEvent.type(inputs[0], '新项目')
    await userEvent.click(screen.getByRole('button', { name: /保\s*存/ }))
    expect(await screen.findByText('记录已创建')).toBeInTheDocument()
  })

  it('passes project context to data-flow and record queries (ADR 0122)', async () => {
    const projectForm = {
      ...FLOW_FORM,
      scope: 'project',
      project_link_field: '所属项目',
    }
    let flowUrl = ''
    let recordsUrl = ''
    server.use(
      http.get('/api/v1/workspaces/:wid/data-flow', ({ request }) => {
        flowUrl = request.url
        return HttpResponse.json({
          ...FLOW,
          project_id: 7,
          project_mode: 'project',
          flows: [{
            ...FLOW.flows[0],
            steps: [{ ...FLOW.flows[0].steps[0], form: projectForm }],
          }],
        })
      }),
      http.get('/api/v1/workspaces/:wid/tables/:tid/records', ({ request }) => {
        recordsUrl = request.url
        return HttpResponse.json({ items: [], total: 0, offset: 0, limit: 500 })
      }),
    )

    renderPage('/w/10/data-flow?project=7')
    expect(await screen.findByTestId('data-flow-page')).toBeInTheDocument()
    await waitFor(() => expect(flowUrl).toContain('project_id=7'))
    await waitFor(() => expect(recordsUrl).toContain('filters='))
    expect(decodeURIComponent(recordsUrl)).toContain('"field_name":"所属项目"')
    expect(decodeURIComponent(recordsUrl)).toContain('"value":[7]')
  })

  it('guides to the project list when project context is required', async () => {
    server.use(
      http.get('/api/v1/workspaces/:wid/data-flow', () =>
        HttpResponse.json(
          { detail: { code: 'project_required', message: '请先选择项目' } },
          { status: 422 },
        ),
      ),
    )
    renderPage()
    expect(await screen.findByTestId('data-flow-project-required')).toBeInTheDocument()
    expect(screen.getByText('请先选择项目')).toBeInTheDocument()
  })

  it('shows multiple flows and a no-form approval step without CRUD actions', async () => {
    renderPage()
    expect(await screen.findByTestId('data-flow-card-project_lifecycle')).toBeInTheDocument()
    expect(screen.getByTestId('data-flow-card-archive_flow')).toBeInTheDocument()

    // 二级子过程默认收起
    expect(screen.queryByTestId('data-flow-step-archive')).not.toBeInTheDocument()
    await userEvent.click(screen.getByTestId('data-flow-card-archive_flow'))
    expect(await screen.findByText(/当前阶段 过程实施/)).toBeInTheDocument()
    expect(await screen.findByTestId('data-flow-step-archive')).toBeInTheDocument()
    expect(await screen.findByTestId('data-flow-step-info')).toBeInTheDocument()
    expect(screen.getByText('核对原件与清单')).toBeInTheDocument()
    expect(screen.queryByTestId('data-flow-create')).not.toBeInTheDocument()
  })

  it('uses one icon button to expand all sub-processes and collapse them back', async () => {
    renderPage()
    await screen.findByTestId('data-flow-diagram')
    expect(screen.getByTestId('data-flow-step-apply')).toBeInTheDocument()
    expect(screen.queryByTestId('data-flow-step-archive')).not.toBeInTheDocument()

    const toggle = screen.getByTestId('data-flow-toggle-all')
    expect(toggle).toHaveAttribute('aria-label', '展开全部子过程')
    await userEvent.click(toggle)
    expect(await screen.findByTestId('data-flow-step-archive')).toBeInTheDocument()
    expect(screen.getByTestId('data-flow-step-approve')).toBeInTheDocument()
    expect(screen.getByTestId('data-flow-toggle-all')).toHaveAttribute('aria-label', '收起全部子过程')

    await userEvent.click(screen.getByTestId('data-flow-toggle-all'))
    expect(screen.queryByTestId('data-flow-step-apply')).not.toBeInTheDocument()
    expect(screen.queryByTestId('data-flow-step-archive')).not.toBeInTheDocument()
    // 收起流程图不影响右侧数据维护
    expect(screen.getByTestId('data-flow-content')).toBeInTheDocument()
  })

  it('filters rows by configured search fields', async () => {
    renderPage()
    await screen.findByText('智能监测项目')
    await userEvent.type(screen.getByTestId('data-flow-search'), '不存在')
    expect(screen.queryByText('智能监测项目')).not.toBeInTheDocument()
  })

  it('does not clear fields hidden from the current role when editing a row', async () => {
    // 列表接口按角色剔除隐藏字段（响应里没有该键）。编辑时不能把「读不到」当成「用户清空」，
    // 否则保存会把隐藏字段静默写成 NULL（数据丢失）。
    const hiddenField = {
      name: '保密备注', field_type: 'text', required: false, config: {}, order: 2, hidden: false,
    }
    const form = {
      ...FLOW_FORM,
      fields: [...FLOW_FORM.fields, hiddenField],
    }
    const flow = {
      ...FLOW,
      flows: [
        {
          ...FLOW.flows[0],
          steps: [
            { ...FLOW.flows[0].steps[0], form },
            FLOW.flows[0].steps[1],
          ],
        },
        FLOW.flows[1],
      ],
    }
    const captured: { values?: Record<string, unknown> } = {}
    server.use(
      http.get('/api/v1/workspaces/:wid/data-flow', () => HttpResponse.json(flow)),
      http.get('/api/v1/workspaces/:wid/tables/:tid/records', () =>
        HttpResponse.json({
          // 保密备注被角色隐藏，响应中不含该键
          items: [{ id: 1, 项目名称: '智能监测项目', 负责人: '张伟' }],
          total: 1, offset: 0, limit: 500,
        }),
      ),
      http.patch('/api/v1/workspaces/:wid/tables/:tid/records/:rid', async ({ request }) => {
        captured.values = (await request.json() as { values: Record<string, unknown> }).values
        return HttpResponse.json({ id: 1 })
      }),
    )

    renderPage()
    await screen.findByText('智能监测项目')
    await userEvent.click(screen.getAllByText('编辑')[0])
    const inputs = await screen.findAllByPlaceholderText('请输入...')
    await userEvent.clear(inputs[1])
    await userEvent.type(inputs[1], '李伟')
    await userEvent.click(screen.getByRole('button', { name: /保\s*存/ }))

    expect(await screen.findByText('记录已更新')).toBeInTheDocument()
    expect(captured.values).toEqual({ 项目名称: '智能监测项目', 负责人: '李伟' })
    expect(captured.values).not.toHaveProperty('保密备注')
  })

  it('shows template hint when workspace has no data flow', async () => {
    server.use(
      http.get('/api/v1/workspaces/:wid/data-flow', () =>
        HttpResponse.json({ detail: '该工作区未使用模板，数据流程不可用' }, { status: 404 }),
      ),
    )
    renderPage('/w/11/data-flow')
    expect(await screen.findByText('数据流程需要工作区使用模板')).toBeInTheDocument()
  })
})
