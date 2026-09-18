import React from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import { useAuthStore } from '@/store'
import { Spin } from 'antd'

export default function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const user = useAuthStore(s => s.user)
  const loading = useAuthStore(s => s.loading)
  const location = useLocation()

  if (loading) {
    return React.createElement(
      'div',
      { style: { display: 'flex', justifyContent: 'center', alignItems: 'center', height: '60vh' } },
      React.createElement(Spin, { size: 'large' }),
    )
  }

  if (!user) {
    const returnTo = encodeURIComponent(location.pathname + location.search)
    return React.createElement(Navigate, { to: `/login?return_to=${returnTo}`, replace: true })
  }

  return React.createElement(React.Fragment, null, children)
}
