/**
 * ProtectedRoute 组件测试 —— 认证路由守卫三态：
 * loading → Spin；未登录 → 重定向 /login?return_to=<编码路径>；已登录 → 渲染 children.
 */

import { describe, expect, it } from 'vitest'
import { Routes, Route, useLocation } from 'react-router-dom'
import { screen } from '@testing-library/react'
import ProtectedRoute from './ProtectedRoute'
import { renderProviders } from '@/test/render-providers'

/** 登录页探针 —— 渲染当前 search 供断言 return_to 编码 */
function LoginProbe() {
  const location = useLocation()
  return <span data-testid="login-page">登录页{location.search}</span>
}

describe('ProtectedRoute 认证守卫三态', () => {
  it('loading=true 时渲染加载态 Spin，不渲染受保护内容', () => {
    renderProviders(
      <ProtectedRoute>
        <div>受保护内容</div>
      </ProtectedRoute>,
      { initialAuth: { user: null, loading: true } },
    )

    expect(document.querySelector('.ant-spin-spinning')).toBeInTheDocument()
    expect(screen.queryByText('受保护内容')).not.toBeInTheDocument()
  })

  it('未登录时重定向到 /login 并携带 return_to=<pathname+search 编码>', () => {
    renderProviders(
      <Routes>
        <Route path="/login" element={<LoginProbe />} />
        <Route
          path="/tables"
          element={
            <ProtectedRoute>
              <div>受保护内容</div>
            </ProtectedRoute>
          }
        />
      </Routes>,
      {
        route: '/tables?x=1',
        initialAuth: { user: null, loading: false },
      },
    )

    // encodeURIComponent('/tables?x=1') === '%2Ftables%3Fx%3D1'
    expect(screen.getByTestId('login-page')).toHaveTextContent('?return_to=%2Ftables%3Fx%3D1')
    expect(screen.queryByText('受保护内容')).not.toBeInTheDocument()
  })

  it('已登录时直接渲染 children', () => {
    renderProviders(
      <ProtectedRoute>
        <div>受保护内容</div>
      </ProtectedRoute>,
      {
        initialAuth: {
          user: {
            id: 1, username: 'alice', email: null, role: 'user',
          },
          loading: false,
        },
      },
    )

    expect(screen.getByText('受保护内容')).toBeInTheDocument()
  })
})
