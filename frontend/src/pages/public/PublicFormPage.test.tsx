/**
 * PublicFormPage 组件测试 —— 公开表单匿名提交.
 *
 * 覆盖：加载态 / 表单不存在 / 字段类型渲染（select/options 提取）/ 必填校验 / 提交成功与失败。
 */

import { describe, expect, it, vi } from 'vitest'
import { http, HttpResponse } from 'msw'
import { Routes, Route } from 'react-router-dom'
import { fireEvent, screen } from '@testing-library/react'
import PublicFormPage from './PublicFormPage'
import { renderProviders } from '@/test/render-providers'
import { server } from '@/test/msw'

const formData = {
  view: { id: 1, name: '报名表单', view_type: 'form' },
  table: {
    id: 100, name: '报名表', description: '活动报名',
    fields: [
      { id: 1, name: '姓名', field_type: 'text', config: null, required: true },
      { id: 2, name: '备注', field_type: 'long_text', config: null },
      { id: 3, name: '级别', field_type: 'select', config: { options: ['高', '中', '低'] } },
    ],
  },
}

function renderForm(route = '/f/abc') {
  return renderProviders(
    <Routes>
      <Route path="/f/:slug" element={<PublicFormPage />} />
    </Routes>,
    { route },
  )
}

describe('PublicFormPage 公开表单页', () => {
  it('加载中渲染 Spin', () => {
    server.use(
      http.get('/api/v1/public/forms/:slug', async () => {
        await new Promise(() => { }) // 永不 resolve
      }),
    )
    renderForm()
    expect(document.querySelector('.ant-spin-spinning')).toBeInTheDocument()
  })

  it('请求失败显示"表单不存在或已下线"', async () => {
    server.use(
      http.get('/api/v1/public/forms/:slug', () =>
        HttpResponse.json({ detail: 'not found' }, { status: 404 })),
    )
    renderForm()
    expect(await screen.findByText('表单不存在或已下线')).toBeInTheDocument()
  })

  it('正常渲染表头信息与各类型字段控件', async () => {
    server.use(http.get('/api/v1/public/forms/:slug', () => HttpResponse.json(formData)))
    renderForm()

    expect(await screen.findByText('报名表单')).toBeInTheDocument()
    expect(screen.getByText('报名表')).toBeInTheDocument()
    // long_text 渲染 TextArea
    expect(document.querySelector('textarea')).not.toBeNull()
  })

  it('必填字段空提交显示校验错误', async () => {
    server.use(http.get('/api/v1/public/forms/:slug', () => HttpResponse.json(formData)))
    renderForm()

    await screen.findByText('报名表单')
    fireEvent.click(screen.getByRole('button', { name: /^提\s*交$/ }))

    expect(await screen.findByText('请填写 姓名')).toBeInTheDocument()
  })

  it('提交成功显示成功消息', async () => {
    const submitSpy = vi.fn(() => HttpResponse.json({ id: 1, status: 'ok' }))
    server.use(
      http.get('/api/v1/public/forms/:slug', () => HttpResponse.json(formData)),
      http.post('/api/v1/public/forms/:slug', submitSpy),
    )
    renderForm()

    await screen.findByText('报名表单')
    fireEvent.change(screen.getByLabelText('姓名'), { target: { value: '张三' } })
    fireEvent.click(screen.getByRole('button', { name: /^提\s*交$/ }))

    expect(await screen.findByText('提交成功，感谢！')).toBeInTheDocument()
    expect(submitSpy).toHaveBeenCalledTimes(1)
  })

  it('提交失败显示错误消息', async () => {
    server.use(
      http.get('/api/v1/public/forms/:slug', () => HttpResponse.json(formData)),
      http.post('/api/v1/public/forms/:slug', () =>
        HttpResponse.json({ detail: 'boom' }, { status: 500 })),
    )
    renderForm()

    await screen.findByText('报名表单')
    fireEvent.change(screen.getByLabelText('姓名'), { target: { value: '张三' } })
    fireEvent.click(screen.getByRole('button', { name: /^提\s*交$/ }))

    expect(await screen.findByText('提交失败，请稍后重试')).toBeInTheDocument()
  })
})
