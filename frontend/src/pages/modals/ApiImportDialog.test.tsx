/**
 * ApiImportDialog 组件测试 —— API 抓取对话框（双模式）.
 *
 * 覆盖：open 开关 / create 模式初始渲染 / URL 校验 / 分析成功与失败 /
 * 建表导入成功 / 追加模式导入成功。
 */

import { describe, expect, it, vi } from 'vitest'
import { http, HttpResponse } from 'msw'
import { fireEvent, screen } from '@testing-library/react'
import ApiImportDialog from './ApiImportDialog'
import { renderProviders } from '@/test/render-providers'
import { server } from '@/test/msw'

const analyzeUrl = '/api/v1/workspaces/10/import-api/analyze'

const analyzeResult = {
  total_rows: 5,
  sample_row_keys: ['name', 'stars'],
  columns: [
    { name: 'name', field_type: 'text', non_null_count: 5, null_ratio: 0, samples: ['react', 'vue', 'antd'] },
    { name: 'stars', field_type: 'number', non_null_count: 4, null_ratio: 0.2, samples: [100, 200] },
  ],
}

/** 填写 API URL 输入框 */
function fillUrl(url = 'https://api.example.com/repos') {
  fireEvent.change(screen.getByTestId('api-url-input'), { target: { value: url } })
}

/** 填 URL 并点击「分析」，等待预览出现 */
async function runAnalyze() {
  server.use(http.post(analyzeUrl, () => HttpResponse.json(analyzeResult)))
  fillUrl()
  fireEvent.click(screen.getByRole('button', { name: /分\s*析$/ }))
  await screen.findByTestId('api-analyze-preview')
}

describe('ApiImportDialog API 抓取对话框', () => {
  it('open=false 时不渲染', () => {
    renderProviders(<ApiImportDialog open={false} wid="10" onClose={() => { }} />)

    expect(screen.queryByText('API 抓取 · 自动建表')).not.toBeInTheDocument()
  })

  it('create 模式：渲染标题/表单，未分析时导入按钮禁用', () => {
    renderProviders(<ApiImportDialog open wid="10" onClose={() => { }} />)

    expect(screen.getByText('API 抓取 · 自动建表')).toBeInTheDocument()
    expect(screen.getByTestId('api-url-input')).toBeInTheDocument()
    expect(screen.getByText('新表名称')).toBeInTheDocument()
    expect(screen.getByTestId('api-placeholder')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /建表并导入$/ })).toBeDisabled()
  })

  it('URL 为空时点击分析显示校验错误', async () => {
    renderProviders(<ApiImportDialog open wid="10" onClose={() => { }} />)

    fireEvent.click(screen.getByRole('button', { name: /分\s*析$/ }))

    expect(await screen.findByText('请输入 API URL')).toBeInTheDocument()
  })

  it('分析成功：显示结构预览并启用导入按钮', async () => {
    renderProviders(<ApiImportDialog open wid="10" onClose={() => { }} />)

    await runAnalyze()

    expect(screen.getByText('命中记录数')).toBeInTheDocument()
    expect(screen.getByText('name')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /建表并导入$/ })).toBeEnabled()
  })

  it('分析失败：显示请求失败与后端 detail 错误', async () => {
    server.use(
      http.post(analyzeUrl, () =>
        HttpResponse.json({ detail: '目标站点不可达' }, { status: 502 })),
    )
    renderProviders(<ApiImportDialog open wid="10" onClose={() => { }} />)

    fillUrl()
    fireEvent.click(screen.getByRole('button', { name: /分\s*析$/ }))

    expect(await screen.findByText('目标站点不可达')).toBeInTheDocument()
    expect(screen.getByText('请求失败')).toBeInTheDocument()
  })

  it('create 模式建表导入成功：提示统计并回调 onSuccess/onClose', async () => {
    const onSuccess = vi.fn()
    const onClose = vi.fn()
    server.use(
      http.post('/api/v1/workspaces/10/import-api', () =>
        HttpResponse.json({ table_id: 55, table_name: '仓库表', imported_rows: 5, field_count: 2, columns: [] })),
    )
    renderProviders(<ApiImportDialog open wid="10" onClose={onClose} onSuccess={onSuccess} />)

    await runAnalyze()
    fireEvent.change(screen.getByPlaceholderText('例如：GitHub 热门仓库 / 加密货币行情'), {
      target: { value: '仓库表' },
    })
    fireEvent.click(screen.getByRole('button', { name: /建表并导入$/ }))

    expect(await screen.findByText('已创建表 "仓库表"，导入 5 行')).toBeInTheDocument()
    expect(onSuccess).toHaveBeenCalledWith({ table_id: 55 })
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('append 模式追加成功：提示追加行数并回调 onSuccess', async () => {
    const onSuccess = vi.fn()
    server.use(
      http.post(analyzeUrl, () => HttpResponse.json(analyzeResult)),
      http.post('/api/v1/workspaces/10/tables/100/import-api', () =>
        HttpResponse.json({ table_id: 100, appended_rows: 4 })),
    )
    renderProviders(<ApiImportDialog open wid="10" tid="100" onSuccess={onSuccess} />)

    expect(screen.getByText('API 抓取 · 追加到当前表')).toBeInTheDocument()
    fillUrl()
    fireEvent.click(screen.getByRole('button', { name: /分\s*析$/ }))
    await screen.findByTestId('api-analyze-preview')
    fireEvent.click(screen.getByRole('button', { name: /追加到当前表$/ }))

    expect(await screen.findByText('已追加 4 行')).toBeInTheDocument()
    expect(onSuccess).toHaveBeenCalledWith({ appended_rows: 4 })
  })
})
