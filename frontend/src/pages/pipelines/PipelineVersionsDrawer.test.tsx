/** PipelineVersionsDrawer 测试 —— 列表 / 单版原文 / 两版 DIFF / 恢复与 viewer 只读（ADR 0114 C9）.*/

import { describe, expect, it } from 'vitest'
import { http, HttpResponse } from 'msw'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import PipelineVersionsDrawer from './PipelineVersionsDrawer'
import { renderProviders } from '@/test/render-providers'
import { mockUser, server } from '@/test/msw'
import type { PipelineVersionDiff, PipelineVersionItem, PipelineWorkflow } from '@/api'

const AUTH = { initialAuth: { user: mockUser, token: 'fake' } }

const WORKFLOW: PipelineWorkflow = {
  id: 7,
  workspace_id: 10,
  name: '空值巡检',
  content: 'name: 空值巡检\n',
  compiled: { name: '空值巡检', jobs: [] },
  enabled: true,
  created_by_id: 1,
  created_at: '2026-10-01T08:00:00Z',
  updated_at: '2026-10-01T08:00:00Z',
  last_run: null,
}

const VERSIONS: PipelineVersionItem[] = [
  {
    id: 12,
    workflow_id: 7,
    version_number: 2,
    change_type: 'manual',
    comment: '',
    created_by_id: 1,
    created_at: '2026-10-02T08:00:00Z',
  },
  {
    id: 11,
    workflow_id: 7,
    version_number: 1,
    change_type: 'manual',
    comment: '',
    created_by_id: 1,
    created_at: '2026-10-01T08:00:00Z',
  },
]

const DIFF: PipelineVersionDiff = {
  base_version: 1,
  head_version: 2,
  diff: '--- base\n+++ head\n@@ -1 +1 @@\n-name: 空值巡检\n+name: 空值巡检改\n',
  added: 1,
  removed: 1,
}

function renderDrawer(canRestore = true, onClose = () => {}) {
  return renderProviders(
    <PipelineVersionsDrawer
      wid={10}
      workflow={WORKFLOW}
      open
      canRestore={canRestore}
      onClose={onClose}
    />,
    AUTH,
  )
}

function versionHandlers() {
  server.use(
    http.get('/api/v1/workspaces/10/pipelines/7/versions', () => HttpResponse.json(VERSIONS)),
    http.get('/api/v1/workspaces/10/pipelines/7/versions/1', () => HttpResponse.json({
      ...VERSIONS[1], content: 'name: 空值巡检\n',
    })),
    http.get('/api/v1/workspaces/10/pipelines/7/versions/2', () => HttpResponse.json({
      ...VERSIONS[0], content: 'name: 空值巡检改\n',
    })),
    http.get('/api/v1/workspaces/10/pipelines/7/diff', () => HttpResponse.json(DIFF)),
  )
}

describe('PipelineVersionsDrawer', () => {
  it('列出全部版本并展示类型与时间', async () => {
    versionHandlers()
    renderDrawer()

    expect(await screen.findByTestId('pipeline-version-row-2')).toBeInTheDocument()
    expect(screen.getByTestId('pipeline-version-row-1')).toBeInTheDocument()
    expect(screen.getAllByText('主动保存')).toHaveLength(2)
  })

  it('选中版本后默认对比上一版并展示原文', async () => {
    versionHandlers()
    renderDrawer()

    fireEvent.click(await screen.findByTestId('pipeline-version-row-2'))
    expect(await screen.findByTestId('pipeline-version-content')).toHaveTextContent('name: 空值巡检改')
    expect(await screen.findByTestId('document-diff')).toBeInTheDocument()
    // 默认 base = v1 / head = v2
    expect(screen.getByTestId('pipeline-diff-base')).toHaveTextContent('v1')
    expect(screen.getByTestId('pipeline-diff-head')).toHaveTextContent('v2')
  })

  it('editor 可二次确认后恢复历史版本', async () => {
    versionHandlers()
    let restored: string | null = null
    server.use(http.post('/api/v1/workspaces/10/pipelines/7/versions/1/restore', () => {
      restored = 'v1'
      return HttpResponse.json(WORKFLOW)
    }))
    renderDrawer()

    fireEvent.click(await screen.findByTestId('pipeline-version-row-1'))
    fireEvent.click(await screen.findByTestId('pipeline-version-restore'))
    const confirm = await screen.findByRole('button', { name: /确\s*定/ })
    fireEvent.click(confirm)
    await waitFor(() => expect(restored).toBe('v1'))
  })

  it('viewer 隐藏恢复入口', async () => {
    versionHandlers()
    renderDrawer(false)

    fireEvent.click(await screen.findByTestId('pipeline-version-row-1'))
    expect(await screen.findByTestId('pipeline-version-content')).toBeInTheDocument()
    expect(screen.queryByTestId('pipeline-version-restore')).toBeNull()
  })
})
