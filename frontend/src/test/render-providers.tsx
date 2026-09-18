/**
 * 组件测试统一 render 工具 —— 对齐应用真实 Provider 结构：
 * QueryClientProvider（retry=false，用例间独立）+ ThemeProvider（antd ConfigProvider zhCN）
 * + MemoryRouter（可注入初始路由）。
 *
 * zustand store 为单例，通过 initialAuth 选项在渲染前注入 auth store 状态。
 */

import React from 'react'
import { render, renderHook, type RenderOptions, type RenderResult, type RenderHookResult } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { UserResponse } from '@/api'
import { ThemeProvider } from '@/theme/ThemeProvider'
import { useAuthStore } from '@/store/auth'

export interface RenderProvidersOptions extends Omit<RenderOptions, 'wrapper'> {
  /** MemoryRouter 初始路由（如 '/tables' 或 '/w/10/t/100?view=grid'） */
  route?: string
  /** 注入 auth store 的初始状态（loading 默认 false，即非登录中态） */
  initialAuth?: {
    user?: UserResponse | null
    token?: string | null
    loading?: boolean
  }
}

/** 创建用例独立的 QueryClient —— 关闭重试避免失败用例拖慢，gc 保留便于断言 */
export function createTestQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, refetchOnWindowFocus: false, staleTime: 0, gcTime: 0 },
      mutations: { retry: false },
    },
  })
}

/** 应用 Provider 栈（不含 auth —— store 为单例，经 initialAuth 注入） */
function buildWrapper(route: string, queryClient: QueryClient) {
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>
        <ThemeProvider>
          <MemoryRouter initialEntries={[route]}>{children}</MemoryRouter>
        </ThemeProvider>
      </QueryClientProvider>
    )
  }
}

/** 统一 render —— 自动注入 QueryClient / 主题 / 路由 / auth store 初始状态 */
export function renderProviders(
  ui: React.ReactElement,
  { route = '/', initialAuth, ...renderOptions }: RenderProvidersOptions = {},
): RenderResult & { queryClient: QueryClient } {
  const queryClient = createTestQueryClient()
  useAuthStore.setState({
    user: initialAuth?.user ?? null,
    token: initialAuth?.token ?? null,
    loading: initialAuth?.loading ?? false,
  })
  const utils = render(ui, { wrapper: buildWrapper(route, queryClient), ...renderOptions })
  return { ...utils, queryClient }
}

/** 统一 renderHook —— Provider 栈与 renderProviders 一致 */
export function renderHookProviders<TResult>(
  callback: () => TResult,
  { route = '/', initialAuth, ...renderOptions }: RenderProvidersOptions = {},
): RenderHookResult<TResult, RenderProvidersOptions> {
  const queryClient = createTestQueryClient()
  useAuthStore.setState({
    user: initialAuth?.user ?? null,
    token: initialAuth?.token ?? null,
    loading: initialAuth?.loading ?? false,
  })
  return renderHook(callback, { wrapper: buildWrapper(route, queryClient), ...renderOptions })
}
