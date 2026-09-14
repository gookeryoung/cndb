import React from 'react'

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div style={{
      minHeight: '100vh',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      background: 'var(--cn-bg-page)',
      padding: 24,
    }}>
      <div style={{ width: 420, maxWidth: '100%' }}>{children}</div>
    </div>
  )
}
