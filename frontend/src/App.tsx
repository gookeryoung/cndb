/** SPA 路由配置 — 按页面 lazy import 实现代码分包. */

import { Suspense, lazy, useEffect, useRef } from 'react'
import { Routes, Route, Navigate, useLocation, useParams } from 'react-router-dom'
import { App as AntApp } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { useAuthStore } from '@/store'
import { workspaceApi } from '@/api'
import { workspaceLandingSegment } from '@/utils/workspaceType'
import ProtectedRoute from '@/components/ProtectedRoute'
import ErrorBoundary from '@/components/ErrorBoundary'
import AuthLayout from '@/layouts/AuthLayout'
import { onAuthExpired } from '@/api/client'

// 全部页面级组件 lazy load：主框架与登录页各自独立成 chunk，
// 未登录用户不再下载 MainLayout / 数据表列表等认证后代码
const MainLayout = lazy(() => import('@/layouts/MainLayout'))
const LoginPage = lazy(() => import('@/pages/auth/LoginPage'))
const RegisterPage = lazy(() => import('@/pages/auth/RegisterPage'))
const WorkspaceList = lazy(() => import('@/pages/workspace/WorkspaceList'))
const TablesList = lazy(() => import('@/pages/workspace/TablesList'))
const GridPage = lazy(() => import('@/pages/grid/GridPage'))
const IssuesPage = lazy(() => import('@/pages/issues/IssuesPage'))
const IssueDetailPage = lazy(() => import('@/pages/issues/IssueDetailPage'))
const ChangeRequestsPage = lazy(() => import('@/pages/changeRequests/ChangeRequestsPage'))
const ChangeRequestDetailPage = lazy(() => import('@/pages/changeRequests/ChangeRequestDetailPage'))
const ChangeRequestRowMergePage = lazy(() => import('@/pages/changeRequests/ChangeRequestRowMergePage'))
const TableSettingsPage = lazy(() => import('@/pages/settings/TableSettingsPage'))
const WorkspaceSettingsPage = lazy(() => import('@/pages/workspace/WorkspaceSettingsPage'))
const AdminPanel = lazy(() => import('@/pages/admin/AdminPanel'))
const DocumentsLayout = lazy(() => import('@/pages/documents/DocumentsLayout'))
const DocumentsPage = lazy(() => import('@/pages/documents/DocumentsPage'))
const DocumentsChangeRequestsPage = lazy(() => import('@/pages/documents/DocumentsChangeRequestsPage'))
const DocumentsIssuesPage = lazy(() => import('@/pages/documents/DocumentsIssuesPage'))
const DocumentEditorPage = lazy(() => import('@/pages/documents/DocumentEditorPage'))
const AnalyticsPage = lazy(() => import('@/pages/analytics/AnalyticsPage'))
const DatasourcePage = lazy(() => import('@/pages/datasource/DatasourcePage'))
const PipelinesPage = lazy(() => import('@/pages/pipelines/PipelinesPage'))
const PipelineRunDetail = lazy(() => import('@/pages/pipelines/PipelineRunDetail'))
const PublicSharePage = lazy(() => import('@/pages/public/PublicSharePage'))
const HelpDocsPage = lazy(() => import('@/pages/help/HelpDocsPage'))

/** 页面级骨架占位 —— 与内容区同形状，替代居中文字，避免切换时高度跳动 */
function PageFallback() {
  return (
    <div style={{ padding: 24 }} aria-label="页面加载中">
      <div style={{ height: 28, width: 220, borderRadius: 6, background: 'var(--cn-border)', marginBottom: 16 }} />
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} style={{ height: 40, borderRadius: 8, background: 'var(--cn-border)', opacity: 0.5 }} />
        ))}
      </div>
    </div>
  )
}

/** 工作区根路由落地页 —— 按工作区类型决定进入「数据表」还是「文档」.
 *
 * 复用 MainLayout 已缓存的 workspaces 列表（同一 queryKey），不额外发请求；
 * 列表未就绪时先按默认（数据表）落地，类型到达后自动纠正。
 */
function WorkspaceLanding() {
  const { wid } = useParams<{ wid: string }>()
  const { data: workspaces = [] } = useQuery({
    queryKey: ['workspaces'],
    queryFn: () => workspaceApi.list(),
  })
  const ws = workspaces.find(w => String(w.id) === wid)
  return <Navigate to={workspaceLandingSegment(ws?.workspace_type)} replace />
}

function AuthenticatedApp() {
  return (
    <ErrorBoundary>
      <Suspense fallback={<PageFallback />}>
        <Routes>
        <Route path="/login" element={<AuthLayout><LoginPage /></AuthLayout>} />
        <Route path="/register" element={<AuthLayout><RegisterPage /></AuthLayout>} />
        {/* 公开分享页（ADR 0017）：免登录只读，注册在 ProtectedRoute 之外 */}
        <Route path="/public/share/:token" element={<PublicSharePage />} />

        <Route path="/" element={<ProtectedRoute><MainLayout /></ProtectedRoute>}>
          <Route index element={<Navigate to="/w" replace />} />
          <Route path="w" element={<WorkspaceList />} />
          <Route path="w/:wid" element={<WorkspaceLanding />} />
          <Route path="w/:wid/tables" element={<TablesList />} />
          <Route path="w/:wid/analytics" element={
            <Suspense fallback={<PageFallback />}><AnalyticsPage /></Suspense>
          } />
          <Route path="w/:wid/datasource" element={
            <Suspense fallback={<PageFallback />}><DatasourcePage /></Suspense>
          } />
          <Route path="w/:wid/pipelines" element={
            <Suspense fallback={<PageFallback />}><PipelinesPage /></Suspense>
          } />
          <Route path="w/:wid/pipelines/:rid" element={
            <Suspense fallback={<PageFallback />}><PipelineRunDetail /></Suspense>
          } />
          <Route path="w/:wid/settings" element={
            <Suspense fallback={<PageFallback />}><WorkspaceSettingsPage /></Suspense>
          } />
          <Route path="w/:wid/tables/:tid" element={
            <Suspense fallback={<PageFallback />}><GridPage /></Suspense>
          } />
          <Route path="w/:wid/tables/:tid/change-requests" element={
            <Suspense fallback={<PageFallback />}><ChangeRequestsPage /></Suspense>
          } />
          <Route path="w/:wid/tables/:tid/change-requests/rows/:rowId/merge" element={
            <Suspense fallback={<PageFallback />}><ChangeRequestRowMergePage /></Suspense>
          } />
          <Route path="w/:wid/tables/:tid/change-requests/:requestId" element={
            <Suspense fallback={<PageFallback />}><ChangeRequestDetailPage /></Suspense>
          } />
          <Route path="w/:wid/tables/:tid/issues" element={
            <Suspense fallback={<PageFallback />}><IssuesPage /></Suspense>
          } />
          <Route path="w/:wid/tables/:tid/issues/:issueId" element={
            <Suspense fallback={<PageFallback />}><IssueDetailPage /></Suspense>
          } />
          <Route path="w/:wid/tables/:tid/settings" element={
            <Suspense fallback={<PageFallback />}><TableSettingsPage /></Suspense>
          } />
          <Route path="w/:wid/documents" element={
            <Suspense fallback={<PageFallback />}><DocumentsLayout /></Suspense>
          }>
            <Route index element={
              <Suspense fallback={<PageFallback />}><DocumentsPage /></Suspense>
            } />
            {/* 文档区二级页（静态段优先于 :docId，不会被编辑器路由吞掉） */}
            <Route path="change-requests" element={
              <Suspense fallback={<PageFallback />}><DocumentsChangeRequestsPage /></Suspense>
            } />
            <Route path="issues" element={
              <Suspense fallback={<PageFallback />}><DocumentsIssuesPage /></Suspense>
            } />
            <Route path=":docId" element={
              <Suspense fallback={<PageFallback />}><DocumentEditorPage /></Suspense>
            } />
          </Route>
          <Route path="admin" element={
            <Suspense fallback={<PageFallback />}><AdminPanel /></Suspense>
          } />
          {/* 帮助文档（ADR 0029）：整页两级导航，选中态由 URL 驱动 */}
          <Route path="help" element={<HelpDocsPage />} />
          <Route path="help/:sectionKey/:topicKey" element={<HelpDocsPage />} />
        </Route>

        <Route path="*" element={<Navigate to="/w" replace />} />
        </Routes>
      </Suspense>
    </ErrorBoundary>
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
