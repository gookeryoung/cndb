/**
 * RegisterPage 组件测试 —— 注册三态 + 服务端错误分类.
 *
 * 覆盖：必填/长度/邮箱格式校验 / 注册成功自动登录并跳转 /
 * 服务端 400 去重错误内联到字段 / 网络异常 / 兜底 message。
 */

import { describe, expect, it } from 'vitest'
import { http, HttpResponse } from 'msw'
import { Routes, Route, useLocation } from 'react-router-dom'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import RegisterPage from './RegisterPage'
import { renderProviders } from '@/test/render-providers'
import { server } from '@/test/msw'

/** 工作区列表探针 —— 断言注册成功后跳转 */
function WorkspaceProbe() {
  const loc = useLocation()
  return <span data-testid="ws-probe">{loc.pathname}</span>
}

function renderRegister() {
  return renderProviders(
    <Routes>
      <Route path="/register" element={<RegisterPage />} />
      <Route path="/w" element={<WorkspaceProbe />} />
    </Routes>,
    { route: '/register' },
  )
}

async function fillAndSubmit(username: string, password: string, email?: string) {
  fireEvent.change(screen.getByPlaceholderText('用户名'), { target: { value: username } })
  fireEvent.change(screen.getByPlaceholderText('密码'), { target: { value: password } })
  if (email !== undefined) {
    fireEvent.change(screen.getByPlaceholderText('your@email.com'), { target: { value: email } })
  }
  // antd 两字按钮会自动插入空格（"注 册"），用正则兼容
  fireEvent.click(screen.getByRole('button', { name: /^注\s*册$/ }))
}

describe('RegisterPage 注册', () => {
  it('必填校验：空表单提交显示用户名与密码错误提示', async () => {
    renderRegister()
    fireEvent.click(screen.getByRole('button', { name: /^注\s*册$/ }))

    expect(await screen.findByText('请输入用户名')).toBeInTheDocument()
    expect(screen.getByText('请输入密码')).toBeInTheDocument()
    expect(screen.queryByTestId('ws-probe')).not.toBeInTheDocument()
  })

  it('长度校验：用户名 < 2 字符或密码 < 6 位显示最小长度提示', async () => {
    renderRegister()
    await fillAndSubmit('a', '123')

    expect(await screen.findByText('至少 2 个字符')).toBeInTheDocument()
    expect(screen.getByText('至少 6 位')).toBeInTheDocument()
  })

  it('注册成功自动登录并跳转 /w', async () => {
    server.use(
      http.post('/api/v1/accounts/auth/register', () =>
        HttpResponse.json({
          id: 2, username: 'bob', email: 'bob@example.com',
          nickname: null, role: 'user', is_active: true,
        })),
    )
    renderRegister()
    await fillAndSubmit('bob', 'secret123')

    await waitFor(() => expect(screen.getByTestId('ws-probe')).toHaveTextContent('/w'))
    expect(await screen.findByText('注册成功，欢迎加入')).toBeInTheDocument()
  })

  it('邮箱格式校验：非法邮箱提交显示格式错误提示，不发请求', async () => {
    server.use(
      http.post('/api/v1/accounts/auth/register', () => {
        throw new Error('不应发出注册请求')
      }),
    )
    renderRegister()
    await fillAndSubmit('bob', 'secret123', 'not-an-email')

    expect(await screen.findByText('邮箱格式不正确')).toBeInTheDocument()
    expect(screen.queryByTestId('ws-probe')).not.toBeInTheDocument()
  })

  it('服务端去重错误：重复用户名内联展示在用户名字段下方', async () => {
    server.use(
      http.post('/api/v1/accounts/auth/register', () =>
        HttpResponse.json({ detail: '用户名已被使用' }, { status: 400 })),
    )
    renderRegister()
    await fillAndSubmit('bob', 'secret123')

    expect(await screen.findByText('用户名已被使用')).toBeInTheDocument()
    expect(screen.queryByTestId('ws-probe')).not.toBeInTheDocument()
  })

  it('服务端去重错误：重复邮箱内联展示在邮箱字段下方', async () => {
    server.use(
      http.post('/api/v1/accounts/auth/register', () =>
        HttpResponse.json({ detail: '邮箱已被使用' }, { status: 400 })),
    )
    renderRegister()
    await fillAndSubmit('bob', 'secret123', 'bob@example.com')

    expect(await screen.findByText('邮箱已被使用')).toBeInTheDocument()
    expect(screen.queryByTestId('ws-probe')).not.toBeInTheDocument()
  })

  it('网络异常：无响应时提示网络错误，不发生跳转', async () => {
    server.use(
      http.post('/api/v1/accounts/auth/register', () => HttpResponse.error()),
    )
    renderRegister()
    await fillAndSubmit('bob', 'secret123')

    expect(await screen.findByText('网络异常，请检查网络后重试')).toBeInTheDocument()
    expect(screen.queryByTestId('ws-probe')).not.toBeInTheDocument()
  })

  it('注册失败展示后端错误消息，不发生跳转', async () => {
    server.use(
      http.post('/api/v1/accounts/auth/register', () =>
        HttpResponse.json({ detail: 'username taken' }, { status: 400 })),
    )
    renderRegister()
    await fillAndSubmit('bob', 'secret123')

    expect(await screen.findByText('username taken')).toBeInTheDocument()
    expect(screen.queryByTestId('ws-probe')).not.toBeInTheDocument()
  })
})
