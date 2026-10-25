import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ThemeProvider } from '@/theme/ThemeProvider'
import App from './App'
// 字体全部走 npm 运行时依赖（本地打包，不引 CDN）；只取 latin 子集四个字重
// 中文不由 web font 覆盖，交由浏览器按系统字体逐字回退
import '@fontsource/inter/latin-400.css'
import '@fontsource/inter/latin-500.css'
import '@fontsource/inter/latin-600.css'
import '@fontsource/inter/latin-700.css'
import '@fontsource/outfit/latin-400.css'
import '@fontsource/outfit/latin-500.css'
import '@fontsource/outfit/latin-600.css'
import '@fontsource/outfit/latin-700.css'
import '@fontsource/jetbrains-mono/latin-400.css'
import '@fontsource/jetbrains-mono/latin-500.css'
import '@fontsource/jetbrains-mono/latin-600.css'
import '@fontsource/jetbrains-mono/latin-700.css'
import './index.css'

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
