/** 小程序入口 —— 注入 QueryClient + AuthProvider. */
import { PropsWithChildren } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { AuthProvider } from './store/auth'
import './app.scss'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      gcTime: 5 * 60_000,
      retry: 2,
      retryDelay: (i) => 1000 * Math.pow(2, i),
      refetchOnMount: 'always',
    },
    mutations: { retry: 0 },
  },
})

function App({ children }: PropsWithChildren) {
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>{children}</AuthProvider>
    </QueryClientProvider>
  )
}

export default App
