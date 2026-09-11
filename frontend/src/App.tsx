import { Routes, Route, Navigate, Outlet } from 'react-router-dom'
import { AuthProvider } from '@/auth/AuthContext'
import ProtectedRoute from '@/components/ProtectedRoute'
import MainLayout from '@/layouts/MainLayout'
import AuthLayout from '@/layouts/AuthLayout'
import PublicLayout from '@/layouts/PublicLayout'
import LoginPage from '@/pages/auth/LoginPage'
import RegisterPage from '@/pages/auth/RegisterPage'
import WorkspaceList from '@/pages/workspace/WorkspaceList'
import GridPage from '@/pages/grid/GridPage'
import GraphPage from '@/pages/graph/GraphPage'
import TrashPanel from '@/pages/modals/TrashPanel'
import ReportsPage from '@/pages/reports/ReportsPage'
import PublicFormPage from '@/pages/public/PublicFormPage'
import PublicSharePage from '@/pages/public/PublicSharePage'

function AuthenticatedApp() {
  return (
    <Routes>
      <Route path="/login" element={<AuthLayout><LoginPage /></AuthLayout>} />
      <Route path="/register" element={<AuthLayout><RegisterPage /></AuthLayout>} />

      <Route path="/" element={<ProtectedRoute><MainLayout /></ProtectedRoute>}>
        <Route index element={<Navigate to="/w" replace />} />
        <Route path="w" element={<WorkspaceList />} />
        <Route path="w/:wid" element={<Navigate to="tables" replace />} />
        <Route path="w/:wid/tables" element={<WorkspaceList />} />
        <Route path="w/:wid/tables/:tid" element={<GridPage />} />
        <Route path="w/:wid/graph" element={<GraphPage />} />
        <Route path="w/:wid/trash" element={<TrashPanel embedded />} />
        <Route path="w/:wid/reports" element={<ReportsPage />} />
      </Route>

      <Route path="/public" element={<PublicLayout />}>
        <Route index element={<div style={{ padding: 24 }}>公开路由</div>} />
        <Route path="form/:slug" element={<PublicFormPage />} />
        <Route path="share/:slug" element={<PublicSharePage />} />
      </Route>

      <Route path="*" element={<Navigate to="/w" replace />} />
    </Routes>
  )
}

function App() {
  return (
    <AuthProvider>
      <AuthenticatedApp />
      <Outlet />
    </AuthProvider>
  )
}

export default App
