/** ChartDesignerModal 组件测试 — 新建 / 编辑 / 实时预览 / 保存回插 / 模板下线只读（ADR 0048 C4 / D5 / 边界 3）. */

import { describe, expect, it, vi } from 'vitest'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { renderProviders } from '@/test/render-providers'
import { mockChartInstance, mockChartSvg, server } from '@/test/msw'
import ChartDesignerModal, { type ChartDesignTarget } from './ChartDesignerModal'

/** 捕获 render-preview / 保存请求体 */
function useBodyCapture(url: RegExp) {
  const bodies: unknown[] = []
  server.use(
    http.post(url, async ({ request }) => {
      bodies.push(await request.json())
      return url.source.includes('render-preview')
        ? new HttpResponse(mockChartSvg, {
            status: 200,
            headers: { 'Content-Type': 'image/svg+xml; charset=utf-8' },
          })
        : HttpResponse.json({ ...mockChartInstance, id: 301 }, { status: 201 })
    }),
  )
  return bodies
}

function renderDesigner(target: ChartDesignTarget | null, overrides: Partial<Parameters<typeof ChartDesignerModal>[0]> = {}) {
  const props = {
    open: true,
    workspaceId: 10,
    target,
    onCancel: vi.fn(),
    onSaved: vi.fn(),
    ...overrides,
  }
  renderProviders(<ChartDesignerModal {...props} />)
  return props
}

describe('ChartDesignerModal', () => {
  it('新建：按模板 default_config 初始化标题与数据行，预览就绪', async () => {
    renderDesigner({ kind: 'create', templateKey: 'bar-line-dual-axis' })

    const title = (await screen.findByTestId('chart-designer-title')) as HTMLInputElement
    await waitFor(() => expect(title.value).toBe('柱线组合图（双轴）'))

    // 双轴模板默认 3 行数据（fixture）
    expect(screen.getByTestId('chart-designer-row-label-0')).toHaveValue('2020')
    expect(screen.getByTestId('chart-designer-row-value-0')).toHaveValue('132')
    expect(screen.getByTestId('chart-designer-row-growth-0')).toHaveValue('')
    // actualCount 分界输入
    expect(screen.getByTestId('chart-designer-actual-count')).toBeInTheDocument()

    // 防抖后预览渲染（300ms + 请求，默认 1s 等待窗口足够）
    expect(await screen.findByTestId('chart-designer-preview-svg')).toBeInTheDocument()
  }, 15_000)

  it('系列模板（堆叠）：渲染系列名称编辑与每行系列值输入', async () => {
    renderDesigner({ kind: 'create', templateKey: 'stacked-bar-horizontal' })

    expect(await screen.findByTestId('chart-designer-series-name-0')).toHaveValue('整车')
    expect(screen.getByTestId('chart-designer-series-name-1')).toHaveValue('零部件')
    expect(screen.getByTestId('chart-designer-row-value-0-0')).toBeInTheDocument()
    // 双轴专属的分界输入不出现
    expect(screen.queryByTestId('chart-designer-actual-count')).toBeNull()
  })

  it('实时预览：编辑图题后 render-preview 收到新 config（D5：与正式渲染同源）', async () => {
    const bodies = useBodyCapture(/\/charts\/render-preview/)
    renderDesigner({ kind: 'create', templateKey: 'bar-line-dual-axis' })

    await screen.findByTestId('chart-designer-preview-svg')

    fireEvent.change(screen.getByTestId('chart-designer-caption-title'), {
      target: { value: '全新图题' },
    })
    await waitFor(() => {
      expect(bodies.length).toBeGreaterThanOrEqual(2)
    })
    const last = bodies[bodies.length - 1] as { config?: { caption?: { title?: string } } }
    expect(last.config?.caption?.title).toBe('全新图题')
  }, 15_000)

  it('新建保存：POST 实例，onSaved 收到新实例（页面回插引用）', async () => {
    const createBodies: unknown[] = []
    server.use(
      http.post('/api/v1/workspaces/10/charts', async ({ request }) => {
        createBodies.push(await request.json())
        return HttpResponse.json({ ...mockChartInstance, id: 301 }, { status: 201 })
      }),
    )
    const props = renderDesigner({ kind: 'create', templateKey: 'bar-line-dual-axis' })

    // save 在草稿初始化完成前是禁用的（disabled={!template || !config}），须先等初始化
    const title = (await screen.findByTestId('chart-designer-title')) as HTMLInputElement
    await waitFor(() => expect(title.value).toBe('柱线组合图（双轴）'))
    fireEvent.click(screen.getByTestId('chart-designer-save'))

    await waitFor(() => expect(props.onSaved).toHaveBeenCalledTimes(1))
    expect(vi.mocked(props.onSaved).mock.calls[0]![0].id).toBe(301)
    expect(createBodies[0]).toMatchObject({ title: '柱线组合图（双轴）', template_key: 'bar-line-dual-axis' })
  })

  it('编辑：载入实例 config，保存走 PUT 全量覆盖', async () => {
    const putBodies: unknown[] = []
    server.use(
      http.put('/api/v1/workspaces/10/charts/300', async ({ request }) => {
        putBodies.push(await request.json())
        return HttpResponse.json({ ...mockChartInstance, title: '改名后' })
      }),
    )
    const props = renderDesigner({ kind: 'edit', chart: mockChartInstance })

    const title = (await screen.findByTestId('chart-designer-title')) as HTMLInputElement
    await waitFor(() => expect(title.value).toBe('产业营业收入与增速'))

    fireEvent.change(title, { target: { value: '改名后' } })
    fireEvent.click(screen.getByTestId('chart-designer-save'))

    await waitFor(() => expect(props.onSaved).toHaveBeenCalledTimes(1))
    expect(vi.mocked(props.onSaved).mock.calls[0]![0].id).toBe(300)
    expect(putBodies[0]).toMatchObject({ title: '改名后', template_key: 'bar-line-dual-axis' })
  }, 15_000)

  it('保存 400：后端校验错误逐条回显且不关闭弹窗', async () => {
    server.use(
      http.post('/api/v1/workspaces/10/charts', () =>
        HttpResponse.json(
          { detail: '第 1 行主值必须是数字', code: 'chart_config_invalid' },
          { status: 400 },
        )),
    )
    const props = renderDesigner({ kind: 'create', templateKey: 'bar-line-dual-axis' })

    // 等草稿初始化（save 按钮解除禁用）后再点击
    const title = (await screen.findByTestId('chart-designer-title')) as HTMLInputElement
    await waitFor(() => expect(title.value).toBe('柱线组合图（双轴）'))
    fireEvent.click(screen.getByTestId('chart-designer-save'))

    expect(await screen.findByTestId('chart-designer-save-error')).toBeInTheDocument()
    expect(screen.getByTestId('chart-designer-save-error').textContent).toContain('主值必须是数字')
    expect(props.onSaved).not.toHaveBeenCalled()
    expect(props.onCancel).not.toHaveBeenCalled()
  }, 15_000)

  it('模板下线的实例：只读提示，无表单且不可保存（边界 3）', async () => {
    const props = renderDesigner({
      kind: 'edit',
      chart: { ...mockChartInstance, template_key: 'legacy-tpl' },
    })

    expect(await screen.findByTestId('chart-designer-template-missing')).toBeInTheDocument()
    expect(screen.queryByTestId('chart-designer-title')).toBeNull()
    expect(screen.getByTestId('chart-designer-save')).toBeDisabled()
    expect(props.onSaved).not.toHaveBeenCalled()
  })
})
