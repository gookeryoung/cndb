/**
 * ImportExportDialog 组件测试 —— 导入/导出对话框.
 *
 * 覆盖：open 开关 / Tab 结构 / 非法扩展名拒绝 / 上传分析→预览 /
 * 确认导入成功与失败 / 导出下载（含 createObjectURL mock）成功与失败。
 */

import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { http, HttpResponse } from 'msw'
import { fireEvent, screen } from '@testing-library/react'
import ImportExportDialog from './ImportExportDialog'
import { renderProviders } from '@/test/render-providers'
import { server } from '@/test/msw'
import { makeField } from '@/test/fixtures'
import { importApi } from '@/api'
import type { ImportTaskInfo } from '@/api'

const WID = '10'
const TID = '100'

const taskUrl = `/api/v1/workspaces/${WID}/tables/${TID}/import/async/9`
const confirmUrl = `/api/v1/workspaces/${WID}/tables/${TID}/import/9/confirm`
const exportUrl = `/api/v1/workspaces/${WID}/tables/${TID}/export`

const fields = [
  makeField({ id: 1, name: '姓名', field_type: 'text' }),
  makeField({ id: 2, name: '邮箱', field_type: 'email' }),
]

/** pending_confirm 任务（analyze/轮询共用） */
const validationReport = {
  total: 3,
  valid_count: 2,
  warning_count: 0,
  error_count: 0,
  new_count: 2,
  update_count: 1,
  update_changed_count: 1,
  multi_key_conflicts: 0,
  skipped_columns: [],
  missing_required: [],
  planned_columns: [],
  new_preview: [
    { row_number: 1, match_key_values: {}, field_sample: { 姓名: '张三' } },
    { row_number: 2, match_key_values: {}, field_sample: { 姓名: '李四' } },
  ],
  update_preview: [
    {
      row_number: 3,
      match_key_values: { 姓名: '王五' },
      existing_row_id: 7,
      field_sample: { 姓名: '王五' },
      field_diffs: { 邮箱: { old: 'old@x.com', new: 'new@x.com', changed: true } },
    },
  ],
  warnings: [],
  errors: [],
}

const pendingTask = {
  task_id: 9,
  status: 'pending_confirm',
  progress: 100,
  filename: 'data.csv',
  format: 'csv',
  total_rows: 3,
  imported_rows: null,
  error_message: null,
  validation_report: validationReport,
}

const doneTask = {
  ...pendingTask,
  status: 'done',
  imported_rows: 3,
  validation_report: { ...validationReport, actually_imported: 3 },
}

/** 通过 Dragger 的隐藏 input 上传文件 */
function uploadFile(name = 'data.csv') {
  const input = document.querySelector('input[type="file"]') as HTMLInputElement
  const file = new File(['姓名,邮箱\n张三,a@x.com'], name, { type: 'text/csv' })
  Object.defineProperty(input, 'files', { value: [file] })
  fireEvent.change(input)
}

/**
 * 上传后轮询进入预览阶段。
 * multipart 上传分析（previewAnalyze）因 msw 拦截器无法处理 jsdom FormData 而在
 * api 层 mock（JSON 端点轮询/确认仍走 MSW）；confirm 处理器用 confirmed 标记
 * 切换轮询返回值，避免轮询与断言竞态。
 */
async function openPreview() {
  const analyzeSpy = vi.spyOn(importApi, 'previewAnalyze').mockResolvedValue(pendingTask as unknown as ImportTaskInfo)
  let confirmed = false
  server.use(
    http.post(confirmUrl, () => {
      confirmed = true
      return HttpResponse.json({ task_id: 9, status: 'running', message: 'ok' })
    }),
    http.get(taskUrl, () => HttpResponse.json(confirmed ? doneTask : pendingTask)),
  )
  renderProviders(
    <ImportExportDialog open wid={WID} tid={TID} fields={fields} onClose={() => { }} />,
  )
  uploadFile()
  // 首轮轮询（800ms）后进入预览
  await screen.findByText('待新增 (2)', {}, { timeout: 4000 })
  return { analyzeSpy, confirmed }
}

beforeEach(() => {
  // jsdom 未实现 createObjectURL/revokeObjectURL
  vi.stubGlobal('URL', Object.assign(URL, {
    createObjectURL: vi.fn(() => 'blob:fake'),
    revokeObjectURL: vi.fn(),
  }))
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('ImportExportDialog 导入/导出对话框', () => {
  it('open=false 时不渲染', () => {
    renderProviders(<ImportExportDialog open={false} wid={WID} tid={TID} onClose={() => { }} />)
    expect(screen.queryByText('更新 / 导出')).not.toBeInTheDocument()
  })

  it('open=true 渲染更新/导出/API 抓取三个 Tab', () => {
    renderProviders(<ImportExportDialog open wid={WID} tid={TID} onClose={() => { }} />)

    expect(screen.getByText('更新 / 导出')).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: /更新/ })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: /导出/ })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: /API 抓取/ })).toBeInTheDocument()
    expect(screen.getByText('点击或拖拽文件到此处')).toBeInTheDocument()
  })

  it('上传非法扩展名文件被拒绝', async () => {
    renderProviders(<ImportExportDialog open wid={WID} tid={TID} onClose={() => { }} />)

    uploadFile('data.txt')

    expect(await screen.findByText(/仅支持/)).toBeInTheDocument()
  })

  it('上传合法文件后轮询进入预览：展示待新增/待更新与确认按钮', async () => {
    const { analyzeSpy } = await openPreview()

    expect(analyzeSpy).toHaveBeenCalledTimes(1)
    expect(screen.getByRole('tab', { name: /待新增/ })).toBeInTheDocument()
    expect(screen.getByText('更新 (1)')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /确认导入/ })).toBeInTheDocument()
  })

  it('确认导入成功：提示完成并回调 onImported', async () => {
    const onImported = vi.fn()
    let confirmed = false
    vi.spyOn(importApi, 'previewAnalyze').mockResolvedValue(pendingTask as unknown as ImportTaskInfo)
    server.use(
      http.post(confirmUrl, () => {
        confirmed = true
        return HttpResponse.json({ task_id: 9, status: 'running', message: 'ok' })
      }),
      http.get(taskUrl, () => HttpResponse.json(confirmed ? doneTask : pendingTask)),
    )
    renderProviders(
      <ImportExportDialog open wid={WID} tid={TID} fields={fields} onClose={() => { }} onImported={onImported} />,
    )

    uploadFile()
    await screen.findByText('待新增 (2)', {}, { timeout: 4000 })
    fireEvent.click(screen.getByRole('button', { name: /确认导入/ }))

    expect(await screen.findByText(/导入完成：3 行/, {}, { timeout: 5000 })).toBeInTheDocument()
    expect(onImported).toHaveBeenCalledTimes(1)
  })

  it('确认导入失败：提示后端 detail 错误', async () => {
    vi.spyOn(importApi, 'previewAnalyze').mockResolvedValue(pendingTask as unknown as ImportTaskInfo)
    server.use(
      http.get(taskUrl, () => HttpResponse.json(pendingTask)),
      http.post(confirmUrl, () =>
        HttpResponse.json({ detail: '任务状态已失效' }, { status: 400 })),
    )
    renderProviders(
      <ImportExportDialog open wid={WID} tid={TID} fields={fields} onClose={() => { }} />,
    )

    uploadFile()
    await screen.findByText('待新增 (2)', {}, { timeout: 4000 })
    fireEvent.click(screen.getByRole('button', { name: /确认导入/ }))

    expect(await screen.findByText('任务状态已失效')).toBeInTheDocument()
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
      <ImportExportDialog open wid={WID} tid={TID} onClose={() => { }} viewId={200} viewName="全部数据" />,
    )

    fireEvent.click(screen.getByRole('tab', { name: /导出/ }))
    expect(await screen.findByText(/按当前视图「全部数据」筛选后导出/)).toBeInTheDocument()
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
    renderProviders(<ImportExportDialog open wid={WID} tid={TID} onClose={() => { }} />)

    fireEvent.click(screen.getByRole('tab', { name: /导出/ }))
    fireEvent.click(screen.getByRole('button', { name: /下\s*载$/ }))

    expect(await screen.findByText('导出配额已用尽')).toBeInTheDocument()
  })
})
