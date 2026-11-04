import type { ComponentProps } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import DataFlowMatrix from './DataFlowMatrix'
import type { DataFlowFlow, DataFlowForm } from '@/api'

const FLOWS: DataFlowFlow[] = [
  {
    key: 'apply_flow',
    name: '项目申报',
    description: '从填报到审批',
    step_count: 2,
    form_count: 1,
    record_count: 3,
    steps: [
      { key: 'fill', name: '填写申报', description: '', form: { name: '申报表' } as unknown as DataFlowForm, documents: [] },
      { key: 'review', name: '人工审批', description: '', form: null, documents: [] },
    ],
  },
  {
    key: 'archive_flow',
    name: '成果归档',
    description: '归档确认',
    step_count: 1,
    form_count: 0,
    record_count: 0,
    steps: [{ key: 'archive', name: '归档确认', description: '', form: null, documents: [] }],
  },
]

function setup(overrides: Partial<ComponentProps<typeof DataFlowMatrix>> = {}) {
  const props = {
    flows: FLOWS,
    activeFlowKey: 'apply_flow',
    activeStepKey: 'fill',
    expandedKeys: [] as string[],
    onToggleFlow: vi.fn(),
    onSelectStep: vi.fn(),
    onExpandAll: vi.fn(),
    onCollapseAll: vi.fn(),
    ...overrides,
  }
  render(<DataFlowMatrix {...props} />)
  return props
}

describe('DataFlowMatrix', () => {
  it('renders level-1 processes only when nothing is expanded', () => {
    setup()
    expect(screen.getByTestId('data-flow-card-apply_flow')).toBeInTheDocument()
    expect(screen.getByTestId('data-flow-card-archive_flow')).toBeInTheDocument()
    expect(screen.getByText('2 步子过程 · 1 个表单 · 3 条记录')).toBeInTheDocument()
    expect(screen.queryByTestId('data-flow-steps-apply_flow')).not.toBeInTheDocument()
    expect(screen.queryByTestId('data-flow-step-fill')).not.toBeInTheDocument()
    expect(screen.getByTestId('data-flow-card-apply_flow')).toHaveAttribute('aria-expanded', 'false')
  })

  it('renders sub-process rows only for expanded flows', () => {
    setup({ expandedKeys: ['apply_flow', 'archive_flow'] })
    expect(screen.getByTestId('data-flow-steps-apply_flow')).toBeInTheDocument()
    expect(screen.getByTestId('data-flow-steps-archive_flow')).toBeInTheDocument()
    expect(screen.getByTestId('data-flow-card-apply_flow')).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByTestId('data-flow-step-fill')).toBeInTheDocument()
    expect(screen.getByTestId('data-flow-step-review')).toBeInTheDocument()
    expect(screen.getByTestId('data-flow-step-archive')).toBeInTheDocument()
  })

  it('notifies toggles, step selection and expand-all / collapse-all', async () => {
    const props = setup({ expandedKeys: ['apply_flow'] })

    await userEvent.click(screen.getByTestId('data-flow-card-apply_flow'))
    expect(props.onToggleFlow).toHaveBeenCalledWith('apply_flow')

    await userEvent.click(screen.getByTestId('data-flow-step-review'))
    expect(props.onSelectStep).toHaveBeenCalledWith('apply_flow', 'review')

    await userEvent.click(screen.getByTestId('data-flow-expand-all'))
    expect(props.onExpandAll).toHaveBeenCalledTimes(1)

    await userEvent.click(screen.getByTestId('data-flow-collapse-all'))
    expect(props.onCollapseAll).toHaveBeenCalledTimes(1)
  })

  it('marks the active flow and step without nesting the content list', () => {
    setup({ expandedKeys: ['apply_flow'], activeStepKey: 'review' })
    expect(screen.getByTestId('data-flow-card-apply_flow')).toHaveClass('is-active')
    expect(screen.getByTestId('data-flow-step-review')).toHaveClass('is-active')
    expect(screen.getByTestId('data-flow-step-review')).toHaveAttribute('aria-current', 'step')
    expect(screen.queryByTestId('data-flow-table')).not.toBeInTheDocument()
  })
})
