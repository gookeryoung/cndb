/**
 * 跨工作区引用修复弹窗（ADR 0156）单测.
 *
 * 覆盖：来源工作区候选（排除当前工作区、仅 owner/editor）、未选来源 / 无问题 / 未选策略时禁止确认、
 * 预览表格「原文 → 新文」、确认后按所选策略提交、失败透出后端 detail。
 *
 * 直接 mock `@/api/documents` 与 `@/api`（不引 msw）。
 */

import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import { renderProviders } from '@/test/render-providers'

const previewReferenceRepair = vi.fn()
const repairReferences = vi.fn()
const listWorkspaces = vi.fn()

vi.mock('@/api/documents', () => ({
  documentsApi: {
    previewReferenceRepair: (...args: unknown[]) => previewReferenceRepair(...args),
    repairReferences: (...args: unknown[]) => repairReferences(...args),
  },
}))

vi.mock('@/api', () => ({
  workspaceApi: { list: () => listWorkspaces() },
}))

import ReferenceRepairModal from './ReferenceRepairModal'

const WORKSPACES = [
  { id: 11, name: '引用源工作区', current_user_role: 'owner' },
  { id: 22, name: '文档当前工作区', current_user_role: 'owner' },
  { id: 33, name: '只读工作区', current_user_role: 'viewer' },
]

const PREVIEW = {
  strategy: 'annotate',
  issues: [
    {
      document_id: 5,
      workspace_id: 22,
      kind: 'wikilink',
      raw: '[[旧标题]]',
      reason: 'target_left_behind',
      target_workspace_id: 11,
      target_workspace_name: '引用源工作区',
      target_title: '旧标题',
      target_table_id: null,
    },
  ],
  previews: [
    {
      document_id: 5,
      raw: '[[旧标题]]',
      next: '旧标题（已移至「引用源工作区」）',
      kind: 'wikilink',
      reason: 'target_left_behind',
    },
  ],
  affected_documents: [5],
}

function renderModal(overrides: Partial<React.ComponentProps<typeof ReferenceRepairModal>> = {}) {
  const onClose = vi.fn()
  const onRepaired = vi.fn()
  renderProviders(
    <ReferenceRepairModal
      open
      workspaceId={22}
      documentIds={[5]}
      onClose={onClose}
      onRepaired={onRepaired}
      {...overrides}
    />,
  )
  return { onClose, onRepaired }
}

beforeEach(() => {
  previewReferenceRepair.mockReset().mockResolvedValue(PREVIEW)
  repairReferences.mockReset().mockResolvedValue({
    changed_documents: 1,
    changed_references: 1,
    skipped_documents: 0,
    truncated: false,
    recomputed: false,
    issues: PREVIEW.issues,
    previews: PREVIEW.previews,
  })
  listWorkspaces.mockReset().mockResolvedValue(WORKSPACES)
})

describe('ReferenceRepairModal', () => {
  it('来源工作区候选排除当前工作区与只读工作区', async () => {
    renderModal({ initialSourceWorkspaceId: 11 })
    await waitFor(() => expect(listWorkspaces).toHaveBeenCalled())
    fireEvent.mouseDown(screen.getByTestId('reference-repair-source').querySelector('input') as HTMLInputElement)
    // 下拉项 + 已选值各一处文本，取首个即可
    expect((await screen.findAllByText('引用源工作区')).length).toBeGreaterThan(0)
    expect(screen.queryByText('只读工作区')).not.toBeInTheDocument()
    // 当前文档所属工作区不作为「来源」
    expect(screen.queryByText('文档当前工作区')).not.toBeInTheDocument()
  })

  it('未选来源工作区时禁止确认，且不触发预览', async () => {
    renderModal()
    await waitFor(() => expect(listWorkspaces).toHaveBeenCalled())
    expect(screen.getByRole('button', { name: /^确\s*认\s*修\s*复$/ })).toBeDisabled()
    expect(previewReferenceRepair).not.toHaveBeenCalled()
  })

  it('预览展示「原文 → 新文」与原因', async () => {
    renderModal({ initialSourceWorkspaceId: 11 })
    await waitFor(() =>
      expect(previewReferenceRepair).toHaveBeenCalledWith(11, {
        document_ids: [5],
        target_workspace_id: 22,
        strategy: 'annotate',
      }),
    )
    expect(await screen.findByText('[[旧标题]]')).toBeInTheDocument()
    expect(screen.getByText('旧标题（已移至「引用源工作区」）')).toBeInTheDocument()
    expect(screen.getByText('目标留在原工作区')).toBeInTheDocument()
  })

  it('无失效引用时展示空态并禁止确认', async () => {
    previewReferenceRepair.mockResolvedValue({ ...PREVIEW, issues: [], previews: [], affected_documents: [] })
    renderModal({ initialSourceWorkspaceId: 11 })
    expect(await screen.findByTestId('reference-repair-empty')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^确\s*认\s*修\s*复$/ })).toBeDisabled()
  })

  it('确认后按所选策略执行修复并回调变更条数', async () => {
    const { onRepaired, onClose } = renderModal({ initialSourceWorkspaceId: 11 })
    await screen.findByText('[[旧标题]]')
    fireEvent.click(screen.getByRole('button', { name: /^确\s*认\s*修\s*复$/ }))

    await waitFor(() =>
      expect(repairReferences).toHaveBeenCalledWith(11, {
        document_ids: [5],
        target_workspace_id: 22,
        strategy: 'annotate',
      }),
    )
    expect(onRepaired).toHaveBeenCalledWith(1)
    expect(onClose).toHaveBeenCalled()
  })

  it('失败时透出后端 detail 且不关闭弹窗', async () => {
    repairReferences.mockRejectedValue(new Error('仅工作区所有者或编辑者可以执行此操作'))
    const { onRepaired, onClose } = renderModal({ initialSourceWorkspaceId: 11 })
    await screen.findByText('[[旧标题]]')
    fireEvent.click(screen.getByRole('button', { name: /^确\s*认\s*修\s*复$/ }))

    await waitFor(() => expect(repairReferences).toHaveBeenCalled())
    expect(onRepaired).not.toHaveBeenCalled()
    expect(onClose).not.toHaveBeenCalled()
  })
})
