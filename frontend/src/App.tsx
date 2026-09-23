/** SPA 路由配置 — 按页面 lazy import 实现代码分包. */

import { Suspense, lazy, useEffect, useRef } from 'react'
import { Routes, Route, Navigate, useLocation } from 'react-router-dom'
import { App as AntApp } from 'antd'
import { useAuthStore } from '@/store'
import ProtectedRoute from '@/components/ProtectedRoute'
import AuthLayout from '@/layouts/AuthLayout'
import PublicLayout from '@/layouts/PublicLayout'
import { onAuthExpired } from '@/api/client'

// 全部页面级组件 lazy load：主框架与登录页各自独立成 chunk，
// 未登录用户不再下载 MainLayout / 数据表列表等认证后代码
const MainLayout = lazy(() => import('@/layouts/MainLayout'))
const LoginPage = lazy(() => import('@/pages/auth/LoginPage'))
const RegisterPage = lazy(() => import('@/pages/auth/RegisterPage'))
const WorkspaceList = lazy(() => import('@/pages/workspace/WorkspaceList'))
const TablesList = lazy(() => import('@/pages/workspace/TablesList'))
const GridPage = lazy(() => import('@/pages/grid/GridPage'))
const ReportsPage = lazy(() => import('@/pages/reports/ReportsPage'))
const PublicFormPage = lazy(() => import('@/pages/public/PublicFormPage'))
const PublicSharePage = lazy(() => import('@/pages/public/PublicSharePage'))
const WorkspaceSettingsPage = lazy(() => import('@/pages/workspace/WorkspaceSettingsPage'))
const AdminPanel = lazy(() => import('@/pages/admin/AdminPanel'))

function PageFallback() {
  return (
    <div style={{
      display: 'flex', justifyContent: 'center', alignItems: 'center',
      height: '50vh', color: '#9ca3af', fontSize: 14,
    }}>加载中...</div>
  )
}

function AuthenticatedApp() {
  return (
    <Suspense fallback={<PageFallback />}>
      <Routes>
        <Route path="/login" element={<AuthLayout><LoginPage /></AuthLayout>} />
        <Route path="/register" element={<AuthLayout><RegisterPage /></AuthLayout>} />

        <Route path="/" element={<ProtectedRoute><MainLayout /></ProtectedRoute>}>
          <Route index element={<Navigate to="/w" replace />} />
          <Route path="w" element={<WorkspaceList />} />
          <Route path="w/:wid" element={<Navigate to="tables" replace />} />
          <Route path="w/:wid/tables" element={<TablesList />} />
          <Route path="w/:wid/settings" element={
            <Suspense fallback={<PageFallback />}><WorkspaceSettingsPage /></Suspense>
          } />
          <Route path="w/:wid/tables/:tid" element={
            <Suspense fallback={<PageFallback />}><GridPage /></Suspense>
          } />
          <Route path="w/:wid/reports" element={
            <Suspense fallback={<PageFallback />}><ReportsPage /></Suspense>
          } />
          <Route path="admin" element={
            <Suspense fallback={<PageFallback />}><AdminPanel /></Suspense>
          } />
        </Route>

        <Route path="/public" element={<PublicLayout />}>
          <Route index element={<div style={{ padding: 24 }}>公开路由</div>} />
          <Route path="form/:slug" element={
            <Suspense fallback={<PageFallback />}><PublicFormPage /></Suspense>
          } />
          <Route path="share/:slug" element={
            <Suspense fallback={<PageFallback />}><PublicSharePage /></Suspense>
          } />
        </Route>

        <Route path="*" element={<Navigate to="/w" replace />} />
      </Routes>
    </Suspense>
  )
}

function App() {
  const refresh = useAuthStore(s => s.refresh)
  const notifyExpired = useAuthStore(s => s.notifyExpired)
  const location = useLocation()
  const { message } = AntApp.useApp()

  // 应用启动时恢复登录态（token 已由 persist 从 localStorage 恢复）
  useEffect(() => {
    refresh()
  }, [refresh])

  /** 令牌过期事件订阅 —— axios 拦截器防抖触发后，统一在此处：
   *   1. 更新 auth store（置 expired 标志 + 清 user）
   *   2. 弹出友好提示
   *   3. ProtectedRoute 检测到 user=null 后自然重定向到 login
   *
   *  用 ref 做一次性保证 —— 500ms 防抖窗口内可能多次触发，但用户只看一条提示。
   *  公开 /login /register /public 页面不弹提示（用户自己在鉴权页或公开页，
   *  此时 401 要么无意义要么是公开接口权限问题，与登录过期无关）。
   */
  const notifiedExpiredRef = useRef(false)
  useEffect(() => {
    notifiedExpiredRef.current = false
    const unsubscribe = onAuthExpired(() => {
      notifyExpired()
      const isAuthOrPublic = location.pathname.startsWith('/login')
        || location.pathname.startsWith('/register')
        || location.pathname.startsWith('/public')
      if (!notifiedExpiredRef.current && !isAuthOrPublic) {
        notifiedExpiredRef.current = true
        message.warning('登录已过期，请重新登录', 3)
      }
    })
    return unsubscribe
  }, [notifyExpired, location.pathname, message])

  return <AuthenticatedApp />
}

export default App
