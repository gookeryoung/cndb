/**
 * ExportDialog（独立导出）组件测试.
 *
 * 覆盖：open 开关 / 标题与只含导出面板 / 格式顺序 / 默认 XLSX + 记住上次选择 /
 * 按视图筛选导出成功 / 后端错误提示 / PDF 视觉快照（成功与目标缺失）。
 */

import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { http, HttpResponse } from 'msw'
import { fireEvent, screen } from '@testing-library/react'
import ExportDialog from './ExportDialog'
import { exportViewToPdf } from './ImportExportDialog/exportPdf'
import { renderProviders } from '@/test/render-providers'
import { server } from '@/test/msw'

const exportViewToPdfMock = vi.hoisted(() => vi.fn().mockResolvedValue(undefined))

vi.mock('./ImportExportDialog/exportPdf', () => ({
  exportViewToPdf: exportViewToPdfMock,
}))

const WID = '10'
const TID = '100'
const exportUrl = `/api/v1/workspaces/${WID}/tables/${TID}/export`

beforeEach(() => {
  // 导出格式偏好存在 localStorage：用例间隔离，避免上一例的选择影响下一例
  localStorage.clear()
  // jsdom 未实现 createObjectURL/revokeObjectURL
  vi.stubGlobal('URL', Object.assign(URL, {
    createObjectURL: vi.fn(() => 'blob:fake'),
    revokeObjectURL: vi.fn(),
  }))
  exportViewToPdfMock.mockClear()
  exportViewToPdfMock.mockResolvedValue(undefined)
})

afterEach(() => {
  vi.unstubAllGlobals()
})

/** 切换为指定格式 */
async function selectFormat(label: string) {
  fireEvent.mouseDown(screen.getByRole('combobox'))
  fireEvent.click(await screen.findByText(label))
}

/** 当前格式下拉的选中文案（antd 6 Select 用 .ant-select-content 承载 title） */
async function selectedFormatLabel(): Promise<string | null> {
  const combo = await screen.findByRole('combobox')
  return combo.closest('.ant-select')?.querySelector('.ant-select-content')?.getAttribute('title') ?? null
}

describe('ExportDialog 导出对话框', () => {
  it('open=false 时不渲染', () => {
    renderProviders(<ExportDialog open={false} wid={WID} tid={TID} onClose={() => { }} />)
    expect(document.querySelector('.ant-modal-title')).toBeNull()
  })

  it('open=true 标题为「导出」，只渲染导出面板（无更新 / API 抓取 Tab）', async () => {
    renderProviders(<ExportDialog open wid={WID} tid={TID} onClose={() => { }} />)

    expect(document.querySelector('.ant-modal-title')).toHaveTextContent('导出')
    expect(await screen.findByText('将表中的数据导出为所选格式（单次上限 50 万行，超限请收窄筛选后分批导出）')).toBeInTheDocument()
    expect(screen.queryByRole('tab')).not.toBeInTheDocument()
    expect(screen.queryByText('点击或拖拽文件到此处')).not.toBeInTheDocument()
  })

  it('底部动作条：关闭与下载同排，关闭回调生效', async () => {
    const onClose = vi.fn()
    renderProviders(<ExportDialog open wid={WID} tid={TID} onClose={onClose} />)
    await screen.findByText('将表中的数据导出为所选格式（单次上限 50 万行，超限请收窄筛选后分批导出）')

    const actions = document.querySelector('.cn-export-actions')
    expect(actions).not.toBeNull()
    expect(actions).toHaveTextContent(/关\s*闭/)
    expect(actions).toHaveTextContent(/下\s*载/)

    // 用面板动作条内的按钮定位（Modal 右上角关闭图标同名）
    fireEvent.click(actions!.querySelector('button') as HTMLButtonElement)
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('导出格式下拉按 XLSX / CSV / PDF / JSON 排序', async () => {
    renderProviders(<ExportDialog open wid={WID} tid={TID} onClose={() => { }} />)

    fireEvent.mouseDown(screen.getByRole('combobox'))
    await screen.findByText('PDF（当前视图画面）')

    const labels = Array.from(
      document.querySelectorAll('.ant-select-item-option-content'),
      el => el.textContent,
    )
    expect(labels).toEqual(['XLSX', 'CSV（Excel 兼容）', 'PDF（当前视图画面）', 'JSON'])
  })

  it('导出默认格式为 XLSX（未选择过偏好的首次导出）', async () => {
    let exportQuery = ''
    server.use(
      http.get(exportUrl, ({ request }) => {
        exportQuery = new URL(request.url).search
        return HttpResponse.json({ rows: [] })
      }),
    )
    renderProviders(<ExportDialog open wid={WID} tid={TID} onClose={() => { }} />)

    expect(await selectedFormatLabel()).toBe('XLSX')

    fireEvent.click(screen.getByRole('button', { name: /下\s*载$/ }))
    expect(await screen.findByText('导出完成')).toBeInTheDocument()
    expect(exportQuery).toContain('format=xlsx')
  })

  it('记住上次选择的导出格式（重新打开弹窗沿用）', async () => {
    const first = renderProviders(<ExportDialog open wid={WID} tid={TID} onClose={() => { }} />)
    await selectFormat('CSV（Excel 兼容）')
    expect(await selectedFormatLabel()).toBe('CSV（Excel 兼容）')
    first.unmount()

    renderProviders(<ExportDialog open wid={WID} tid={TID} onClose={() => { }} />)
    expect(await selectedFormatLabel()).toBe('CSV（Excel 兼容）')
  })

  it('导出成功：按视图筛选触发下载并提示完成', async () => {
    let exportQuery = ''
    server.use(
      http.get(exportUrl, ({ request }) => {
        exportQuery = new URL(request.url).search
        return HttpResponse.json({ rows: [] })
      }),
    )
    renderProviders(
      <ExportDialog open wid={WID} tid={TID} onClose={() => { }} viewId={200} viewName="全部数据" />,
    )

    expect(await screen.findByText(/按当前视图「全部数据」筛选后导出/)).toBeInTheDocument()
    await selectFormat('CSV（Excel 兼容）')
    fireEvent.click(screen.getByRole('button', { name: /下\s*载$/ }))

    expect(await screen.findByText('导出完成')).toBeInTheDocument()
    expect(URL.createObjectURL).toHaveBeenCalledTimes(1)
    expect(exportQuery).toContain('format=csv')
    expect(exportQuery).toContain('view_id=200')
  })

  it('导出失败：提示后端 detail 错误', async () => {
    server.use(
      http.get(exportUrl, () => HttpResponse.json({ detail: '导出配额已用尽' }, { status: 500 })),
    )
    renderProviders(<ExportDialog open wid={WID} tid={TID} onClose={() => { }} />)

    fireEvent.click(screen.getByRole('button', { name: /下\s*载$/ }))

    expect(await screen.findByText('导出配额已用尽')).toBeInTheDocument()
  })

  it('PDF 导出：调用 exportViewToPdf、隐藏范围开关、不请求后端导出接口', async () => {
    let exportCalled = false
    server.use(
      http.get(exportUrl, () => {
        exportCalled = true
        return HttpResponse.json({ rows: [] })
      }),
    )
    const target = document.createElement('div')
    const release = vi.fn()
    renderProviders(
      <ExportDialog open wid={WID} tid={TID} onClose={() => { }}
        viewId={200} viewName="全部数据" getPdfTarget={() => Promise.resolve(target)} releasePdfTarget={release} />,
    )

    expect(await screen.findByText(/按当前视图「全部数据」筛选后导出/)).toBeInTheDocument()
    await selectFormat('PDF（当前视图画面）')
    // PDF 为视觉快照：范围开关隐藏，展示 PDF 提示
    expect(screen.queryByText(/按当前视图/)).not.toBeInTheDocument()
    expect(screen.getByText(/导出当前视图可见内容画面/)).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /下\s*载$/ }))

    expect(await screen.findByText('导出完成')).toBeInTheDocument()
    expect(exportViewToPdf).toHaveBeenCalledTimes(1)
    expect(exportViewToPdf).toHaveBeenCalledWith(target, expect.stringMatching(/^view-全部数据-\d{8}_\d{6}\.pdf$/))
    expect(exportCalled).toBe(false)
    // 导出结束后退出导出模式（恢复虚拟滚动）
    expect(release).toHaveBeenCalledTimes(1)
  })

  it('PDF 导出：目标容器缺失时提示错误且不调用生成', async () => {
    renderProviders(
      <ExportDialog open wid={WID} tid={TID} onClose={() => { }} getPdfTarget={() => Promise.resolve(null)} />,
    )

    await selectFormat('PDF（当前视图画面）')
    fireEvent.click(screen.getByRole('button', { name: /下\s*载$/ }))

    expect(await screen.findByText('未找到可导出的视图内容')).toBeInTheDocument()
    expect(exportViewToPdf).not.toHaveBeenCalled()
  })
})
