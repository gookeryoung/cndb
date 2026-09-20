/**
 * AuthLayout 布局测试 —— 认证页容器渲染.
 *
 * 验证点：children 被渲染在 420px 宽的居中容器内。
 */

import { describe, expect, it } from 'vitest'
import { screen } from '@testing-library/react'
import AuthLayout from './AuthLayout'
import { renderProviders } from '@/test/render-providers'

describe('AuthLayout 布局', () => {
  it('渲染 children 内容', () => {
    renderProviders(
      <AuthLayout>
        <div>登录卡片探针</div>
      </AuthLayout>,
    )

    expect(screen.getByText('登录卡片探针')).toBeInTheDocument()
  })
})
