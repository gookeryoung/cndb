/**
 * MSW + renderProviders 冒烟测试：
 * 验证组件测试设施整体可用 —— Provider 栈渲染、MSW 数据拦截、未命中请求报错（TR-6.1）.
 */

import { describe, expect, it } from 'vitest'
import { screen } from '@testing-library/react'
import { useLocation } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { workspaceApi } from '@/api'
import api from '@/api/client'
import { renderProviders } from './render-providers'

// ─────────────── 冒烟组件：经 React Query + MSW 拉取工作区列表 ───────────────

function WorkspaceLabel() {
  const { data, isPending, isError } = useQuery({
    queryKey: ['smoke-workspaces'],
    queryFn: () => workspaceApi.list(),
  })
  if (isPending) return <span>加载中</span>
  if (isError) return <span>加载失败</span>
  return <ul>{data.map(w => <li key={w.id}>{w.name}</li>)}</ul>
}

describe('组件测试设施冒烟', () => {
  it('renderProviders + MSW：组件经拦截网络拿到工作区数据并渲染', async () => {
    renderProviders(<WorkspaceLabel />)

    // 先出现加载态，再被 MSW 返回的数据替换
    expect(await screen.findByText('测试工作区')).toBeInTheDocument()
    expect(screen.queryByText('加载中')).not.toBeInTheDocument()
  })

  it('renderProviders 可注入初始路由', () => {
    function PathProbe() {
      const location = useLocation()
      return <span data-testid="route">{location.pathname}</span>
    }
    // MemoryRouter 初始路由注入后，组件内 useLocation 读到该路由
    renderProviders(<PathProbe />, { route: '/w/10/t/100' })
    expect(screen.getByTestId('route')).toHaveTextContent('/w/10/t/100')
  })

  it('TR-6.1: 未命中 handler 的请求显式报错，不允许静默穿透', async () => {
    // 未在 handlers 中注册的端点 → onUnhandledRequest: 'error' → 请求 Promise reject
    // （MSW 在 stderr 打印拦截告警；axios XHR 层将错误归一为 "Network Error"）
    await expect(api.get('/v1/unknown-endpoint')).rejects.toThrow(/Network Error/i)
  })
})
