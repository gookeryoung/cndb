import React from 'react'

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div style={{
      minHeight: '100vh',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      background: 'linear-gradient(135deg, #eff6ff 0%, #e0f2fe 100%)',
      padding: 24,
    }}>
      <div style={{ width: 420, maxWidth: '100%' }}>{children}</div>
    </div>
  )
}
