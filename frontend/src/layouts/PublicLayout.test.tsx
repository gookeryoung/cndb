/**
 * PublicLayout 布局测试 —— 公开访问容器渲染.
 *
 * 验证点：
 * 1. 顶栏渲染"cndb · 公开访问"标题
 * 2. Outlet 正确渲染子路由内容
 */

import { describe, expect, it } from 'vitest'
import { Routes, Route } from 'react-router-dom'
import { screen } from '@testing-library/react'
import PublicLayout from './PublicLayout'
import { renderProviders } from '@/test/render-providers'

describe('PublicLayout 布局', () => {
    it('渲染顶栏标题并显示子路由 Outlet 内容', () => {
        renderProviders(
            <Routes>
                <Route path="/" element={<PublicLayout />}>
                    <Route index element={<div>公开内容探针</div>} />
                </Route>
            </Routes>,
        )

        expect(screen.getByText('cndb · 公开访问')).toBeInTheDocument()
        expect(screen.getByText('公开内容探针')).toBeInTheDocument()
    })
})
