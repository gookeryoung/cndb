/**
 * LoginPage 组件测试 —— 登录三态.
 *
 * 覆盖：必填校验 / 登录成功跳转 returnTo / 登录失败 message.error。
 */

import { describe, expect, it } from 'vitest'
import { http, HttpResponse } from 'msw'
import { Routes, Route, useLocation } from 'react-router-dom'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import LoginPage from './LoginPage'
import { renderProviders } from '@/test/render-providers'
import { server } from '@/test/msw'

/** 工作区列表探针 —— 断言登录成功后跳转 */
function WorkspaceProbe() {
  const loc = useLocation()
  return <span data-testid="ws-probe">{loc.pathname}</span>
}

function renderLogin() {
  return renderProviders(
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/w" element={<WorkspaceProbe />} />
    </Routes>,
    { route: '/login' },
  )
}

async function fillAndSubmit(login: string, password: string) {
  fireEvent.change(screen.getByPlaceholderText('用户名或邮箱'), { target: { value: login } })
  fireEvent.change(screen.getByPlaceholderText('密码'), { target: { value: password } })
  // antd 两字按钮会自动插入空格（"登 录"），用正则兼容
  fireEvent.click(screen.getByRole('button', { name: /^登\s*录$/ }))
}

describe('LoginPage 登录', () => {
  it('必填校验：空表单提交显示错误提示', async () => {
    renderLogin()
    fireEvent.click(screen.getByRole('button', { name: /^登\s*录$/ }))

    expect(await screen.findByText('请输入用户名或邮箱')).toBeInTheDocument()
    expect(screen.getByText('请输入密码')).toBeInTheDocument()
    expect(screen.queryByTestId('ws-probe')).not.toBeInTheDocument()
  })

  it('登录成功跳转到 returnTo（默认 /w）', async () => {
    renderLogin()
    await fillAndSubmit('alice', 'secret123')

    await waitFor(() => expect(screen.getByTestId('ws-probe')).toHaveTextContent('/w'))
    expect(await screen.findByText('登录成功')).toBeInTheDocument()
  })

  it('登录失败显示错误消息，不发生跳转', async () => {
    server.use(
      http.post('/api/v1/accounts/auth/login', () =>
        HttpResponse.json({ detail: 'bad credentials' }, { status: 401 })),
    )
    renderLogin()
    await fillAndSubmit('alice', 'wrong')

    expect(await screen.findByText('用户名或密码错误')).toBeInTheDocument()
    expect(screen.queryByTestId('ws-probe')).not.toBeInTheDocument()
  })
})
