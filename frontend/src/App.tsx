import { Routes, Route, Navigate } from 'react-router-dom'
import MainLayout from './layouts/MainLayout'
import Dashboard from './pages/dashboard/Dashboard'
import HealthPage from './pages/health/HealthPage'
import UserList from './pages/crud-demo/UserList'
import AppCenter from './pages/apps/AppCenter'

function App() {
  return (
    <Routes>
      <Route path="/" element={<MainLayout />}>
        <Route index element={<Navigate to="/dashboard" replace />} />
        <Route path="dashboard" element={<Dashboard />} />
        <Route path="health" element={<HealthPage />} />
        <Route path="crud-demo/users" element={<UserList />} />
        <Route path="apps" element={<AppCenter />} />
      </Route>
    </Routes>
  )
}

export default App
