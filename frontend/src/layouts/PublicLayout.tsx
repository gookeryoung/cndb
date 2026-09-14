import { Outlet } from 'react-router-dom'

export default function PublicLayout() {
  return (
    <div style={{ minHeight: '100vh', background: 'var(--cn-bg-page)' }}>
      <header style={{
        padding: '12px 24px', background: 'var(--cn-bg-container)',
        borderBottom: '1px solid var(--cn-border)', fontWeight: 600,
      }}>
        cndb · 公开访问
      </header>
      <main style={{ padding: 24, maxWidth: 1200, margin: '0 auto' }}>
        <Outlet />
      </main>
    </div>
  )
}
