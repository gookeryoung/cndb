import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ThemeProvider } from '@/theme/ThemeProvider'
import App from './App'
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
queryClient.setQueryDefaults(['row-comments'], { staleTime: 10_000 })
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
