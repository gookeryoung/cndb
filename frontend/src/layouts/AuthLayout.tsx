import React from 'react'

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div
      className="auth-shell"
      style={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: 24,
      }}
    >
      <div style={{ width: 420, maxWidth: '100%', position: 'relative' }}>{children}</div>
    </div>
  )
}
