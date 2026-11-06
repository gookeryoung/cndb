import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ThemeProvider } from '@/theme/ThemeProvider'
import App from './App'
// 字体全部走 npm 运行时依赖（本地打包，不引 CDN）；只取 latin 子集、按实际使用字重裁剪：
// - Inter：正文/界面 400/500/600/700（bold 用于 Markdown strong 与统计数字，不裁）
// - Outfit：仅展示位（品牌/KPI/拉丁大标题）实际使用 600/700
// - JetBrains Mono：代码块只用常规字重
// 中文不由 web font 覆盖，交由浏览器按系统字体逐字回退
import '@fontsource/inter/latin-400.css'
import '@fontsource/inter/latin-500.css'
import '@fontsource/inter/latin-600.css'
import '@fontsource/inter/latin-700.css'
import '@fontsource/outfit/latin-600.css'
import '@fontsource/outfit/latin-700.css'
import '@fontsource/jetbrains-mono/latin-400.css'
import './index.css'
import { getToken } from '@/api/client'

/** 认证进行中并行预取外壳与落地页 chunk（ADR 0116 C3 / D4）.
 *
 * `ProtectedRoute` 在 `/auth/me` 返回前不渲染子路由，MainLayout 与页面 chunk 的下载
 * 会被串行推迟一个 RTT。这里在 createRoot().render() 之前按路径直接触发动态 import：
 * 浏览器并行下载 chunk，认证完成即可命中已下载模块。
 *
 * 边界：仅已登录（有 token）且路径在 `/w/*` 时预取；匿名用户零额外请求；
 * 预取失败静默（不影响认证与错误态）；动态 import 由 bundler 去重，正式渲染不会重复下载。
 */
function prefetchAuthedShell(): void {
  if (!getToken()) return
  const pathname = window.location.pathname
  if (!/^\/w(\/|$)/.test(pathname)) return

  const load = (loader: () => Promise<unknown>) => {
    void loader().catch(() => undefined)
  }
  load(() => import('@/layouts/MainLayout'))

  if (/^\/w\/?$/.test(pathname)) {
    load(() => import('@/pages/workspace/WorkspaceList'))
    return
  }
  const segments = pathname.split('/').filter(Boolean)
  const section = segments[2]
  if (section === 'tables') {
    if (segments[3]) load(() => import('@/pages/grid/GridPage'))
    else load(() => import('@/pages/workspace/TablesList'))
  } else if (section === 'documents') {
    load(() => import('@/pages/documents/DocumentsPage'))
  } else if (section === 'design') {
    load(() =>
      segments[3]
        ? import('@/pages/design/DesignEditorPage')
        : import('@/pages/design/DesignsPage'),
    )
  } else if (section === 'analytics') {
    load(() => import('@/pages/analytics/AnalyticsPage'))
  } else if (section === 'datasource') {
    load(() => import('@/pages/datasource/DatasourcePage'))
  }
}

prefetchAuthedShell()

// React Query 全局配置 —— 默认 30s staleTime，下方 setQueryDefaults 按 queryKey 前缀差异化覆盖
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      retry: 1,
      staleTime: 30_000,
    },
  },
})
queryClient.setQueryDefaults(['table-records'], { staleTime: 10_000 })
queryClient.setQueryDefaults(['row-audit'], { staleTime: 10_000 })
queryClient.setQueryDefaults(['row-references'], { staleTime: 10_000 })
queryClient.setQueryDefaults(['table-views'], { staleTime: 60_000 })
queryClient.setQueryDefaults(['table'], { staleTime: 60_000 })
queryClient.setQueryDefaults(['user-pref-active-view'], { staleTime: 60_000 })

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <BrowserRouter
          future={{ v7_relativeSplatPath: true, v7_startTransition: true }}
        >
          <App />
        </BrowserRouter>
      </ThemeProvider>
    </QueryClientProvider>
  </React.StrictMode>,
)

// Web Vitals 动态加载，独立 chunk，不占用首屏关键路径
void import('./utils/webVitals').then((m) => m.reportWebVitals())

// 运行时垫片：首次渲染后探测，只有旧内核才下载 flex-gap shim
void import('@/compat').then((m) => m.initCompat())
