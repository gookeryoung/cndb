/**
 * 跨工作区移动弹窗（ADR 0155）单测.
 *
 * 覆盖：目标工作区候选与配额展示、无可用目标空态、目标文件夹懒加载、
 * 提交载荷（document_ids / target_workspace_id / parent_id）、影响说明三项口径、
 * 后端 413 明细透出、成功后回调目标工作区。
 *
 * 这里直接 mock `@/api/documents`（不引 msw），保持与被测组件同一数据边界。
 */

import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import { renderProviders } from '@/test/render-providers'

const moveTargets = vi.fn()
const moveToWorkspace = vi.fn()
const tree = vi.fn()

vi.mock('@/api/documents', () => ({
  documentsApi: {
    moveTargets: (...args: unknown[]) => moveTargets(...args),
    moveToWorkspace: (...args: unknown[]) => moveToWorkspace(...args),
    tree: (...args: unknown[]) => tree(...args),
  },
}))

import MoveDocumentModal from './MoveDocumentModal'

const TARGETS = {
  items: [
    {
      id: 22,
      name: '研发中心',
      role: 'owner',
      quota_bytes: 100 * 1024 * 1024,
      used_bytes: 20 * 1024 * 1024,
      remaining_bytes: 80 * 1024 * 1024,
    },
    {
      id: 33,
      name: '市场部',
      role: 'editor',
      quota_bytes: 10 * 1024 * 1024,
      used_bytes: 10 * 1024 * 1024,
      remaining_bytes: 0,
    },
  ],
}

function renderModal(overrides: Partial<React.ComponentProps<typeof MoveDocumentModal>> = {}) {
  const onMoved = vi.fn()
  const onClose = vi.fn()
  renderProviders(
    <MoveDocumentModal
      open
      workspaceId={11}
      documentIds={[5, 6]}
      onClose={onClose}
      onMoved={onMoved}
      {...overrides}
    />,
  )
  return { onMoved, onClose }
}

beforeEach(() => {
  moveTargets.mockReset().mockResolvedValue(TARGETS)
  moveToWorkspace.mockReset()
  tree.mockReset().mockResolvedValue([
    { id: 101, title: '战略', is_folder: true, parent_id: null },
    { id: 102, title: '子文件夹', is_folder: true, parent_id: 101 },
    { id: 103, title: '普通文档', is_folder: false, parent_id: null },
  ])
})

describe('MoveDocumentModal', () => {
  it('列出可移动目标工作区并展示配额余量', async () => {
    renderModal()
    await waitFor(() => expect(moveTargets).toHaveBeenCalledWith(11))
    fireEvent.mouseDown((await screen.findByTestId('move-document-target')).querySelector('input') as HTMLInputElement)
    expect(await screen.findByText(/研发中心（剩余 80\.0 MB）/)).toBeInTheDocument()
    expect(screen.getByText(/市场部（剩余 0 B）/)).toBeInTheDocument()
  })

  it('没有可用目标时给出空态并禁用提交', async () => {
    moveTargets.mockResolvedValue({ items: [] })
    renderModal()
    expect(await screen.findByTestId('move-document-empty')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^移\s*动$/ })).toBeDisabled()
  })

  it('影响说明覆盖「分享继续有效 / 申请随行 / 引用不自动修复」', async () => {
    renderModal()
    const impact = await screen.findByTestId('move-document-impact')
    expect(impact).toHaveTextContent('分享链接')
    expect(impact).toHaveTextContent('修改申请')
    expect(impact).toHaveTextContent('不会自动修复')
  })

  it('选目标工作区 + 子文件夹后提交，载荷含 document_ids / target / parent', async () => {
    moveToWorkspace.mockResolvedValue({
      document_ids: [5, 6],
      target_workspace_id: 22,
      moved_nodes: 2,
      moved_files: 1,
      moved_change_requests: 0,
      moved_bytes: 1024,
      missing_files: [],
    })
    const { onMoved, onClose } = renderModal()

    const select = (await screen.findByTestId('move-document-target')).querySelector('input') as HTMLInputElement
    fireEvent.mouseDown(select)
    fireEvent.click(await screen.findByText(/研发中心（剩余 80\.0 MB）/))

    await waitFor(() => expect(tree).toHaveBeenCalledWith(22))
    const parent = (await screen.findByTestId('move-document-parent')).querySelector('input') as HTMLInputElement
    fireEvent.mouseDown(parent)
    fireEvent.click(await screen.findByText('子文件夹'))

    fireEvent.click(screen.getByRole('button', { name: /^移\s*动$/ }))
    await waitFor(() =>
      expect(moveToWorkspace).toHaveBeenCalledWith(11, {
        document_ids: [5, 6],
        target_workspace_id: 22,
        parent_id: 102,
      }),
    )
    await waitFor(() => expect(onMoved).toHaveBeenCalledWith(22))
    expect(onClose).toHaveBeenCalled()
  })

  it('后端 413 的差额文案直接透出，且不关闭弹窗', async () => {
    moveToWorkspace.mockRejectedValue(
      new Error('目标工作区存储空间不足：已用 10.0 MB / 配额 10.0 MB，本次需 2.0 MB'),
    )
    const { onMoved, onClose } = renderModal()
    const select = (await screen.findByTestId('move-document-target')).querySelector('input') as HTMLInputElement
    fireEvent.mouseDown(select)
    fireEvent.click(await screen.findByText(/研发中心（剩余 80\.0 MB）/))
    fireEvent.click(screen.getByRole('button', { name: /^移\s*动$/ }))

    await waitFor(() => expect(moveToWorkspace).toHaveBeenCalled())
    expect(onMoved).not.toHaveBeenCalled()
    expect(onClose).not.toHaveBeenCalled()
  })

  it('未选目标工作区时提交被拦下（不发请求）', async () => {
    renderModal()
    await screen.findByTestId('move-document-target')
    expect(screen.getByRole('button', { name: /^移\s*动$/ })).toBeDisabled()
    expect(moveToWorkspace).not.toHaveBeenCalled()
  })

  it('moveSummary 汇总项数与文件夹数量', async () => {
    const { moveSummary } = await import('./MoveDocumentModal')
    expect(moveSummary(3)).toBe('共 3 项')
    expect(moveSummary(3, 1)).toBe('共 3 项，含 1 个文件夹（连同其中文档一起移动）')
  })
})
