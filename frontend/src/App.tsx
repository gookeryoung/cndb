/** SPA 路由配置 — 按页面 lazy import 实现代码分包. */

import { Suspense, lazy, useEffect } from 'react'
import { Routes, Route, Navigate } from 'react-router-dom'
import { useAuthStore } from '@/store'
import ProtectedRoute from '@/components/ProtectedRoute'
import AuthLayout from '@/layouts/AuthLayout'
import PublicLayout from '@/layouts/PublicLayout'

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

  useEffect(() => {
    // 应用启动时恢复登录态（token 已由 persist 从 localStorage 恢复）
    refresh()
  }, [refresh])

  return <AuthenticatedApp />
}

export default App
