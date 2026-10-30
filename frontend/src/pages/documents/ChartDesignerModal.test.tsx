/** ChartDesignerModal 组件测试 — 新建 / 编辑正文块 / 实时预览 / 保存回传 / 模板下线只读（ADR 0048 C4 / D5，ADR 0052 D9）. */

import { describe, expect, it, vi } from 'vitest'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { renderProviders } from '@/test/render-providers'
import { mockChartInstance, mockChartSvg, server } from '@/test/msw'
import type { ChartBlockSpec } from '@/components/Document/chartBlock'
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
    await waitFor(() => expect(title.value).toBe('双轴柱线组合图'))

    // 双轴模板默认 3 行数据（fixture）
    expect(screen.getByTestId('chart-designer-row-label-0')).toHaveValue('2020')
    expect(screen.getByTestId('chart-designer-row-value-0')).toHaveValue('132')
    expect(screen.getByTestId('chart-designer-row-growth-0')).toHaveValue('')
    // 默认次值直接显示为联动状态：按主值推算 +「(计算)」（ADR 0059 C2）
    expect(screen.getByTestId('chart-designer-row-growth-1')).toHaveValue('19.7(计算)')
    expect(screen.getByTestId('chart-designer-row-growth-1')).toHaveAttribute('data-linked')
    expect(screen.getByTestId('chart-designer-row-growth-2')).toHaveValue('17.7(计算)')
    // 首行次值禁填（ADR 0056 C2）
    expect(screen.getByTestId('chart-designer-row-growth-0')).toBeDisabled()
    expect(screen.getByTestId('chart-designer-row-growth-1')).toBeEnabled()
    // actualCount 分界输入
    expect(screen.getByTestId('chart-designer-actual-count')).toBeInTheDocument()

    // 防抖后预览渲染（300ms + 请求，默认 1s 等待窗口足够）
    expect(await screen.findByTestId('chart-designer-preview-svg')).toBeInTheDocument()
  }, 15_000)

  it('次值联动（ADR 0056 C3/C4 + 0059 C1/C3/C4）：点击联动态进编辑填次值 → 主值联动(计算)；改主值 → 次值反向重算(计算)', async () => {
    renderDesigner({ kind: 'create', templateKey: 'bar-line-dual-axis' })

    await screen.findByTestId('chart-designer-preview-svg')

    // 点击联动态次值（19.7(计算)）进入编辑：仅显示纯数值 19.7（ADR 0059 C3）
    fireEvent.click(screen.getByTestId('chart-designer-row-growth-1'))
    const growth1 = screen.getByTestId('chart-designer-row-growth-1') as HTMLInputElement
    expect(growth1).toHaveValue('19.7')
    expect(growth1).not.toHaveAttribute('data-linked')

    // 改为 20 失焦提交 → 主值 = 132 × 1.2 = 158.4，进入联动态显示「158.4(计算)」
    fireEvent.change(growth1, { target: { value: '20' } })
    fireEvent.blur(growth1)
    const value1 = screen.getByTestId('chart-designer-row-value-1') as HTMLInputElement
    await waitFor(() => expect(value1).toHaveValue('158.4(计算)'))
    expect(value1).toHaveAttribute('data-linked')

    // 点击主值进入编辑显示纯数值 158.4，改 200 → 次值反向重算 51.5(计算)
    fireEvent.click(value1)
    const value1Edit = screen.getByTestId('chart-designer-row-value-1') as HTMLInputElement
    expect(value1Edit).toHaveValue('158.4')
    fireEvent.change(value1Edit, { target: { value: '200' } })
    fireEvent.blur(value1Edit)
    const growth1After = screen.getByTestId('chart-designer-row-growth-1') as HTMLInputElement
    await waitFor(() => expect(growth1After).toHaveValue('51.5(计算)'))
    expect(growth1After).toHaveAttribute('data-linked')

    // 再手动编辑次值为 25：次值转显式值（无 data-linked），主值 = 132 × 1.25 = 165(计算)
    fireEvent.click(growth1After)
    const growth1Edit = screen.getByTestId('chart-designer-row-growth-1') as HTMLInputElement
    expect(growth1Edit).toHaveValue('51.5')
    fireEvent.change(growth1Edit, { target: { value: '25' } })
    fireEvent.blur(growth1Edit)
    await waitFor(() => {
      const value1Final = screen.getByTestId('chart-designer-row-value-1') as HTMLInputElement
      expect(value1Final).toHaveValue('165(计算)')
    })
    expect(screen.getByTestId('chart-designer-row-growth-1')).toHaveValue('25')
    expect(screen.getByTestId('chart-designer-row-growth-1')).not.toHaveAttribute('data-linked')
  }, 15_000)

  it('联动单元格未改动失焦保持联动态、清空次值恢复联动显示（ADR 0059 Q1 / C4）', async () => {
    renderDesigner({ kind: 'create', templateKey: 'bar-line-dual-axis' })

    await screen.findByTestId('chart-designer-preview-svg')

    // 点击联动态次值进入编辑后未改动即失焦：保持联动态（仍显示 19.7(计算)）
    fireEvent.click(screen.getByTestId('chart-designer-row-growth-1'))
    const growth1 = screen.getByTestId('chart-designer-row-growth-1') as HTMLInputElement
    fireEvent.blur(growth1)
    expect(screen.getByTestId('chart-designer-row-growth-1')).toHaveValue('19.7(计算)')
    expect(screen.getByTestId('chart-designer-row-growth-1')).toHaveAttribute('data-linked')

    // 显式填 30 → 主值联动 171.6(计算)；再清空次值 → 恢复按主值推算的联动态 30(计算)
    fireEvent.click(screen.getByTestId('chart-designer-row-growth-1'))
    fireEvent.change(screen.getByTestId('chart-designer-row-growth-1'), { target: { value: '30' } })
    fireEvent.blur(screen.getByTestId('chart-designer-row-growth-1'))
    const value1 = screen.getByTestId('chart-designer-row-value-1') as HTMLInputElement
    await waitFor(() => expect(value1).toHaveValue('171.6(计算)'))
    fireEvent.change(screen.getByTestId('chart-designer-row-growth-1'), { target: { value: '' } })
    await waitFor(() => expect(screen.getByTestId('chart-designer-row-growth-1')).toHaveValue('30(计算)'))
  }, 15_000)

  it('次值联动不越界（ADR 0056 I1）：上年主值缺失时不联动', async () => {
    renderDesigner({ kind: 'create', templateKey: 'bar-line-dual-axis' })

    await screen.findByTestId('chart-designer-preview-svg')

    // 清空第 1 行主值后，第 2 行填次值不联动主值（基数缺失）
    fireEvent.change(screen.getByTestId('chart-designer-row-value-0'), { target: { value: '' } })
    fireEvent.change(screen.getByTestId('chart-designer-row-growth-1'), { target: { value: '20' } })
    const value1 = screen.getByTestId('chart-designer-row-value-1') as HTMLInputElement
    expect(value1).toHaveValue('158')
    expect(value1).not.toHaveAttribute('data-affected')
  }, 15_000)

  it('预览列占比 ≥ 55%：弹窗加宽、预览列 56%，窄屏堆叠（ADR 0051 C1）', async () => {
    renderDesigner({ kind: 'create', templateKey: 'bar-line-dual-axis' })

    const preview = await screen.findByTestId('chart-designer-preview')
    expect(preview.style.flex).toContain('56%')
    const modal = document.querySelector('.ant-modal') as HTMLElement | null
    expect(modal).not.toBeNull()
    expect(parseFloat(modal!.style.width)).toBeGreaterThanOrEqual(1200)
  })

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

  it('新建保存：POST 素材库，onSaved 返回实例（页面插入定义副本）', async () => {
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
    await waitFor(() => expect(title.value).toBe('双轴柱线组合图'))
    fireEvent.click(screen.getByTestId('chart-designer-save'))

    await waitFor(() => expect(props.onSaved).toHaveBeenCalledTimes(1))
    const saved = vi.mocked(props.onSaved).mock.calls[0]![0]
    expect(saved.kind).toBe('chart')
    expect(saved.kind === 'chart' && saved.chart.id).toBe(301)
    expect(createBodies[0]).toMatchObject({ title: '双轴柱线组合图', template_key: 'bar-line-dual-axis' })
    // 提交 payload 无联动标记字段，留空次值仍存 null（ADR 0059 C5）
    const savedConfig = (createBodies[0] as { config?: { data?: { rows?: { growth: number | null }[] } } }).config
    expect(savedConfig?.data?.rows?.map(r => r.growth)).toEqual([null, null, null])
  })

  it('编辑正文块：载入块内定义，保存只回传新定义、不写素材库', async () => {
    let writes = 0
    server.use(
      http.post('/api/v1/workspaces/10/charts', () => {
        writes += 1
        return HttpResponse.json(mockChartInstance, { status: 201 })
      }),
      http.put('/api/v1/workspaces/10/charts/:cid', () => {
        writes += 1
        return HttpResponse.json(mockChartInstance)
      }),
    )
    const spec: ChartBlockSpec = {
      version: 1,
      templateKey: mockChartInstance.template_key,
      title: mockChartInstance.title,
      width: 60,
      config: mockChartInstance.config,
    }
    const props = renderDesigner({ kind: 'editBlock', spec, occurrence: 2 })

    const title = (await screen.findByTestId('chart-designer-title')) as HTMLInputElement
    await waitFor(() => expect(title.value).toBe('产业营业收入与增速'))

    fireEvent.change(title, { target: { value: '改名后' } })
    fireEvent.click(screen.getByTestId('chart-designer-save'))

    await waitFor(() => expect(props.onSaved).toHaveBeenCalledTimes(1))
    const saved = vi.mocked(props.onSaved).mock.calls[0]![0]
    expect(saved.kind).toBe('block')
    expect(saved.kind === 'block' && saved.spec.title).toBe('改名后')
    expect(saved.kind === 'block' && saved.spec.width).toBe(60)
    expect(writes).toBe(0)
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
    await waitFor(() => expect(title.value).toBe('双轴柱线组合图'))
    fireEvent.click(screen.getByTestId('chart-designer-save'))

    expect(await screen.findByTestId('chart-designer-save-error')).toBeInTheDocument()
    expect(screen.getByTestId('chart-designer-save-error').textContent).toContain('主值必须是数字')
    expect(props.onSaved).not.toHaveBeenCalled()
    expect(props.onCancel).not.toHaveBeenCalled()
  }, 15_000)

  it('模板下线的正文块：只读提示，无表单且不可保存（边界 3）', async () => {
    const props = renderDesigner({
      kind: 'editBlock',
      spec: {
        version: 1,
        templateKey: 'legacy-tpl',
        title: '旧图',
        width: 75,
        config: {},
      },
      occurrence: 0,
    })

    expect(await screen.findByTestId('chart-designer-template-missing')).toBeInTheDocument()
    expect(screen.queryByTestId('chart-designer-title')).toBeNull()
    expect(screen.getByTestId('chart-designer-save')).toBeDisabled()
    expect(props.onSaved).not.toHaveBeenCalled()
  })
})

describe('ChartDesignerModal 标准类型（需求卡片 0070）', () => {
  it('折线模板：系列名 / 样式开关 / 数值标签实时预览（C3）', async () => {
    const bodies = useBodyCapture(/\/charts\/render-preview/)
    renderDesigner({ kind: 'create', templateKey: 'line-vivid' })

    // 系列名编辑 + 纵轴单位（label_fields 声明）
    expect(await screen.findByTestId('chart-designer-series-name-0')).toHaveValue('纯电动')
    expect(screen.getByTestId('chart-designer-label-unitY')).toBeInTheDocument()
    // 旧系列的横轴单位输入不出现（新类型无 unitX 声明）
    expect(screen.queryByTestId('chart-designer-unit-x')).toBeNull()

    // 样式开关：默认开，关闭后预览 config.style 随之变化
    const valuesToggle = screen.getByTestId('chart-designer-style-showValues')
    expect(valuesToggle).toBeChecked()
    await screen.findByTestId('chart-designer-preview-svg')
    fireEvent.click(valuesToggle)
    await waitFor(() => {
      const last = bodies[bodies.length - 1] as { config?: { style?: Record<string, boolean> } }
      expect(last.config?.style?.showValues).toBe(false)
    })
  }, 15_000)

  it('数据一键导入（C3）：粘贴 TSV 含表头整表替换并识别系列名', async () => {
    renderDesigner({ kind: 'create', templateKey: 'line-vivid' })
    await screen.findByTestId('chart-designer-preview-svg')

    fireEvent.change(screen.getByTestId('chart-designer-import-text'), {
      target: { value: '季度\t线上\t线下\nQ1\t100\t200\nQ2\t120\t260\nQ3\t150\t300' },
    })
    fireEvent.click(screen.getByTestId('chart-designer-import-apply'))

    // 表头识别为系列名，数据行整表替换
    await waitFor(() => expect(screen.getByTestId('chart-designer-series-name-0')).toHaveValue('线上'))
    expect(screen.getByTestId('chart-designer-series-name-1')).toHaveValue('线下')
    expect(screen.getByTestId('chart-designer-row-label-0')).toHaveValue('Q1')
    expect(screen.getByTestId('chart-designer-row-value-0-0')).toHaveValue('100')
    expect(screen.getByTestId('chart-designer-row-value-2-1')).toHaveValue('300')
    // 旧示例行被替换（2023 不再出现）
    expect(screen.queryByTestId('chart-designer-row-label-3')).toBeNull()
  }, 15_000)

  it('数据一键导入（C3）：无可识别数据行时提示错误', async () => {
    renderDesigner({ kind: 'create', templateKey: 'pie-business' })
    await screen.findByTestId('chart-designer-preview-svg')

    fireEvent.change(screen.getByTestId('chart-designer-import-text'), { target: { value: '' } })
    expect(screen.getByTestId('chart-designer-import-apply')).toBeDisabled()
    fireEvent.change(screen.getByTestId('chart-designer-import-text'), { target: { value: '名称 数值' } })
    fireEvent.click(screen.getByTestId('chart-designer-import-apply'))
    expect(await screen.findByTestId('chart-designer-import-error')).toBeInTheDocument()
  }, 15_000)

  it('饼图（value 行结构）：名称 / 数值编辑 + 环形样式开关', async () => {
    renderDesigner({ kind: 'create', templateKey: 'pie-donut' })

    expect(await screen.findByTestId('chart-designer-row-label-0')).toHaveValue('整车制造')
    expect(screen.getByTestId('chart-designer-row-value-0')).toHaveValue('1250')
    // 无系列维度：系列名编辑不出现
    expect(screen.queryByTestId('chart-designer-series-name-0')).toBeNull()
    // 环形样式默认开
    expect(screen.getByTestId('chart-designer-style-donut')).toBeChecked()
  }, 15_000)

  it('散点图（xy 行结构）：横纵轴数值编辑 + 保存按 x/y 序列化', async () => {
    const createBodies: unknown[] = []
    server.use(
      http.post('/api/v1/workspaces/10/charts', async ({ request }) => {
        createBodies.push(await request.json())
        return HttpResponse.json({ ...mockChartInstance, id: 302, template_key: 'scatter-trend' }, { status: 201 })
      }),
    )
    const props = renderDesigner({ kind: 'create', templateKey: 'scatter-trend' })

    expect(await screen.findByTestId('chart-designer-row-x-0')).toHaveValue('120')
    expect(screen.getByTestId('chart-designer-row-y-0')).toHaveValue('380')
    fireEvent.change(screen.getByTestId('chart-designer-row-x-0'), { target: { value: '130' } })

    fireEvent.click(screen.getByTestId('chart-designer-save'))
    await waitFor(() => expect(props.onSaved).toHaveBeenCalledTimes(1))
    const cfg = (createBodies[0] as { config?: { data?: { rows?: Record<string, unknown>[] } } }).config
    expect(cfg?.data?.rows?.[0]).toEqual({ x: 130, y: 380 })
  }, 15_000)

  it('主题选择（0073）：规范模板在配色上方提供主题选择，切换整组替换 palette + paper', async () => {
    const bodies = useBodyCapture(/\/charts\/render-preview/)
    renderDesigner({ kind: 'create', templateKey: 'pie' })

    await screen.findByTestId('chart-designer-preview-svg')
    // 主题选择位于配色区上方，默认明快数据（vivid）
    const themeSelect = screen.getByTestId('chart-designer-theme')
    expect(themeSelect.closest('div')).not.toBeNull()
    const paletteSection = screen.getByTestId('chart-designer-palette-0')
    expect(themeSelect.compareDocumentPosition(paletteSection) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()

    // 切换商务蓝：预览请求 theme 变为商务蓝 palette + 纸底
    fireEvent.mouseDown(themeSelect.querySelector('.ant-select-selector') as HTMLElement)
    fireEvent.click(await screen.findByTitle('商务蓝'))
    await waitFor(() => {
      const last = bodies[bodies.length - 1] as { config?: { theme?: { palette?: string[]; paper?: string } } }
      expect(last.config?.theme?.palette?.[0]).toBe('#1E3D57')
      expect(last.config?.theme?.paper).toBe('#F6F8FA')
    })
  }, 15_000)

  it('主题选择（0073）：变体模板（存量实例）无主题选择', async () => {
    renderDesigner({ kind: 'create', templateKey: 'pie-business' })

    expect(await screen.findByTestId('chart-designer-preview-svg')).toBeInTheDocument()
    expect(screen.queryByTestId('chart-designer-theme')).toBeNull()
  }, 15_000)

  it('保存 value 行结构：剔除 growth 字段（与模板 schema 同形）', async () => {
    const createBodies: unknown[] = []
    server.use(
      http.post('/api/v1/workspaces/10/charts', async ({ request }) => {
        createBodies.push(await request.json())
        return HttpResponse.json({ ...mockChartInstance, id: 303, template_key: 'pie-business' }, { status: 201 })
      }),
    )
    const props = renderDesigner({ kind: 'create', templateKey: 'pie-business' })

    await screen.findByTestId('chart-designer-row-label-0')
    fireEvent.click(screen.getByTestId('chart-designer-save'))
    await waitFor(() => expect(props.onSaved).toHaveBeenCalledTimes(1))
    const cfg = (createBodies[0] as { config?: { data?: { rows?: Record<string, unknown>[] } } }).config
    expect(cfg?.data?.rows?.[0]).toEqual({ label: '整车制造', value: 1250 })
  }, 15_000)

  it('样式开关实时入预览：环形开关切换后 config.style.donut 变化（C3）', async () => {
    const bodies = useBodyCapture(/\/charts\/render-preview/)
    renderDesigner({ kind: 'create', templateKey: 'pie-business' })

    await screen.findByTestId('chart-designer-preview-svg')
    const donut = screen.getByTestId('chart-designer-style-donut')
    expect(donut).not.toBeChecked() // 商务预设默认扇形
    fireEvent.click(donut)
    await waitFor(() => {
      const last = bodies[bodies.length - 1] as { config?: { style?: Record<string, boolean> } }
      expect(last.config?.style?.donut).toBe(true)
    })
  }, 15_000)
})
