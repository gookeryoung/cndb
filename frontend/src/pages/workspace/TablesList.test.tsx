/**
 * TablesList 页面组件测试 —— 工作区数据表列表.
 *
 * 覆盖：加载态 / 标题与列表渲染 / 空态 / 访问级别筛选 / 新建表成功回调 / 创建失败错误态.
 * 注：组件用 useParams 取 wid，必须包在 Routes 内渲染。
 */

import { describe, expect, it } from 'vitest'
import { delay, http, HttpResponse } from 'msw'
import { Routes, Route, useLocation } from 'react-router-dom'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import TablesList from './TablesList'
import { renderProviders } from '@/test/render-providers'
import { server } from '@/test/msw'
import type { TableSummary } from '@/api'

function LocationProbe() {
  const loc = useLocation()
  return <span data-testid="location">{loc.pathname}</span>
}

const WORKSPACE = {
  id: 10, name: '研发部工作区', description: '团队数据资产', visibility: 'member', tags: [],
  allow_edit: true, created_by_id: 1, created_at: '', updated_at: '',
  owner: { id: 1, username: 'alice', nickname: null },
  table_count: 1, member_count: 1, view_count: 0, total_rows: 0,
  current_user_role: 'owner',
}

/** 两张不同访问级别的表（用于筛选用例） */
const TWO_TABLES: TableSummary[] = [
  { id: 100, name: '我方表', record_count: 1, field_count: 2, view_count: 1, my_access: 'owner' },
  { id: 101, name: '只读表', record_count: 0, field_count: 1, view_count: 0, my_access: 'read' },
]

function renderPage() {
  return renderProviders(
    <Routes>
      <Route path="/w/:wid/tables" element={<TablesList />} />
      <Route path="/w/:wid/tables/:tid" element={<LocationProbe />} />
    </Routes>,
    { route: '/w/10/tables' },
  )
}

function setupWorkspace() {
  server.use(http.get('/api/v1/workspaces/10', () => HttpResponse.json(WORKSPACE)))
}

describe('TablesList 工作区表列表页', () => {
  it('表列表请求未返回时表格显示加载态', async () => {
    setupWorkspace()
    server.use(
      http.get('/api/v1/workspaces/10/tables', async () => {
        await delay('infinite')
        return HttpResponse.json([])
      }),
    )
    renderPage()

    await waitFor(() => expect(document.querySelector('.ant-spin-spinning')).toBeInTheDocument())
  })

  it('渲染工作区标题与表列表', async () => {
    setupWorkspace()
    renderPage()

    expect(await screen.findByText('研发部工作区 · 数据资产')).toBeInTheDocument()
    expect(await screen.findByText('客户表')).toBeInTheDocument()
    expect(screen.getByText('共 1 / 1 张表')).toBeInTheDocument()
  })

  it('空列表显示空态提示', async () => {
    setupWorkspace()
    server.use(http.get('/api/v1/workspaces/10/tables', () => HttpResponse.json([])))
    renderPage()

    expect(await screen.findByText(/还没有表/)).toBeInTheDocument()
  })

  it('按访问级别筛选：切到"我拥有的"后仅剩 owner 表', async () => {
    setupWorkspace()
    server.use(http.get('/api/v1/workspaces/10/tables', () => HttpResponse.json(TWO_TABLES)))
    renderPage()

    expect(await screen.findByText('共 2 / 2 张表')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('radio', { name: '我拥有的' }))

    expect(await screen.findByText('共 1 / 2 张表')).toBeInTheDocument()
    expect(screen.queryByText('只读表')).not.toBeInTheDocument()
  })

  it('新建表：填写表名创建成功后提示并跳转新表', async () => {
    setupWorkspace()
    server.use(
      http.post('/api/v1/workspaces/10/tables', () =>
        HttpResponse.json({ id: 101, name: '订单表', description: '' }),
      ),
    )
    renderPage()

    fireEvent.click(await screen.findByRole('button', { name: /新\s*建\s*表/ }))
    await waitFor(() => expect(document.querySelector('.ant-modal-title')).toHaveTextContent('新建表'))

    fireEvent.change(screen.getByLabelText('表名'), { target: { value: '订单表' } })
    fireEvent.click(screen.getByRole('button', { name: /^创\s*建$/ }))

    // 全量并发下 mutation→message→navigate 链路可能超过默认 1s，放宽查找超时（断言语义不变）
    // message（portal）与 navigate（router）分属两套状态更新，先提示后跳转属正常时序，用 waitFor 等待
    expect(await screen.findByText(/已创建表/, {}, { timeout: 3000 })).toBeInTheDocument()
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/w/10/tables/101'))
  })

  it('创建失败时显示后端错误信息', async () => {
    setupWorkspace()
    server.use(
      http.post('/api/v1/workspaces/10/tables', () =>
        HttpResponse.json({ detail: '表名已存在' }, { status: 500 }),
      ),
    )
    renderPage()

    fireEvent.click(await screen.findByRole('button', { name: /新\s*建\s*表/ }))
    await waitFor(() => expect(document.querySelector('.ant-modal-title')).toHaveTextContent('新建表'))

    fireEvent.change(screen.getByLabelText('表名'), { target: { value: '订单表' } })
    fireEvent.click(screen.getByRole('button', { name: /^创\s*建$/ }))

    expect(await screen.findByText('表名已存在')).toBeInTheDocument()
  })
})
