/** 发布为复用模块弹窗测试（ADR 0118 P1）：默认值 / 提交 / 成功回调 / 失败提示 */

import { describe, expect, it, vi } from 'vitest'
import { http, HttpResponse } from 'msw'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import PublishModuleModal from './PublishModuleModal'
import { renderProviders } from '@/test/render-providers'
import { server } from '@/test/msw'

const AUTH = { initialAuth: { user: null, token: 'fake' } }

function renderModal(onPublished = vi.fn()) {
  renderProviders(
    <PublishModuleModal
      open
      wid="10"
      designId={20}
      defaultName="法兰板"
      defaultDescription="标准件"
      onClose={() => {}}
      onPublished={onPublished}
    />,
    AUTH,
  )
  return onPublished
}

describe('PublishModuleModal', () => {
  it('提交可见性与版本说明，成功后回调 module_key 与新版本', async () => {
    let body: Record<string, unknown> | null = null
    server.use(http.post('/api/v1/workspaces/10/designs/20/publish', async ({ request }) => {
      body = await request.json() as Record<string, unknown>
      return HttpResponse.json({
        module_id: 7,
        module_key: 'flange',
        version_number: 1,
        visibility: 'public',
        name: '法兰板',
      })
    }))
    const onPublished = renderModal()

    expect(await screen.findByDisplayValue('法兰板')).toBeInTheDocument()
    fireEvent.click(screen.getByLabelText('公开（允许跨工作区引用）'))
    fireEvent.change(screen.getByTestId('publish-comment'), { target: { value: '首版' } })
    fireEvent.click(screen.getByRole('button', { name: /发\s*布/ }))

    await waitFor(() => expect(onPublished).toHaveBeenCalled())
    expect(onPublished.mock.calls[0]![0]).toMatchObject({ module_key: 'flange', version_number: 1 })
    expect(body).toMatchObject({ name: '法兰板', visibility: 'public', comment: '首版' })
  })

  it('后端拒绝时提示失败且不回调', async () => {
    server.use(http.post('/api/v1/workspaces/10/designs/20/publish', () =>
      HttpResponse.json({ code: 'design_publish_failed', detail: '第1行第1列：仅 part 可发布' }, { status: 400 })))
    const onPublished = renderModal()

    fireEvent.click(screen.getByRole('button', { name: /发\s*布/ }))
    expect(await screen.findByText(/仅 part 可发布/)).toBeInTheDocument()
    expect(onPublished).not.toHaveBeenCalled()
  })
})
