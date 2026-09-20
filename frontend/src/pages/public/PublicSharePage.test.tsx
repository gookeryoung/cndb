/**
 * PublicSharePage 组件测试 —— 公开分享只读页.
 *
 * 覆盖：加载态 / 正常渲染分享表格 / 无效 slug 错误态。
 */

import { describe, expect, it, vi } from 'vitest'
import { http, HttpResponse } from 'msw'
import { Routes, Route } from 'react-router-dom'
import { screen } from '@testing-library/react'
import PublicSharePage from './PublicSharePage'
import { renderProviders } from '@/test/render-providers'
import { server } from '@/test/msw'

const shareData = {
  view: { id: 1, name: '公开视图', view_type: 'grid', filters: null, sortings: null },
  table: {
    id: 100, name: '客户表', description: '对外的客户信息',
    fields: [
      { id: 1, name: '姓名', field_type: 'text', config: null },
      { id: 2, name: '年龄', field_type: 'number', config: null, hidden: true },
    ],
  },
  rows: [{ id: 1, 姓名: '张三' }],
  total: 1,
}

function renderShare(route = '/s/abc') {
  return renderProviders(
    <Routes>
      <Route path="/s/:slug" element={<PublicSharePage />} />
    </Routes>,
    { route },
  )
}

describe('PublicSharePage 公开分享页', () => {
  it('加载中渲染 Spin', async () => {
    server.use(
      http.get('/api/v1/public/share/:slug', async () => {
        await new Promise(() => { }) // 永不 resolve，维持加载态
      }),
    )
    renderShare()
    expect(document.querySelector('.ant-spin-spinning')).toBeInTheDocument()
  })

  it('正常渲染视图名、表名 Tag 与记录统计，hidden 字段不出列', async () => {
    server.use(http.get('/api/v1/public/share/:slug', () => HttpResponse.json(shareData)))
    renderShare()

    expect(await screen.findByText('公开视图')).toBeInTheDocument()
    expect(screen.getByText('客户表')).toBeInTheDocument()
    expect(screen.getByText('只读分享')).toBeInTheDocument()
    expect(screen.getByText('共 1 条记录 · 2 个字段')).toBeInTheDocument()
    // hidden 字段不出现在表头
    expect(screen.queryByText('年龄')).not.toBeInTheDocument()
    // 行数据通过 GridCell 渲染
    expect(screen.getByText('张三')).toBeInTheDocument()
  })

  it('请求失败时显示错误空态与返回首页链接', async () => {
    server.use(
      http.get('/api/v1/public/share/:slug', () =>
        HttpResponse.json({ detail: 'not found' }, { status: 404 })),
    )
    renderShare()

    expect(await screen.findByText('分享链接无效或已过期')).toBeInTheDocument()
    expect(screen.getByText('返回首页')).toBeInTheDocument()
  })

  it('无 slug 时不发请求且显示错误态', async () => {
    const spy = vi.fn(() => HttpResponse.json(shareData))
    server.use(http.get('/api/v1/public/share/:slug', spy))
    // 不包 Routes：useParams 返回空对象 → slug undefined → query enabled=false
    renderProviders(<PublicSharePage />)

    expect(await screen.findByText('分享链接无效或已过期')).toBeInTheDocument()
    expect(spy).not.toHaveBeenCalled()
  })
})
