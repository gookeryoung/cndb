import { lazy, Suspense, type ReactNode } from 'react'

// 背景引擎与流场动效独立成 chunk：AuthLayout 本身在主入口，静态引入会把体积抬进首屏（ADR 0016 D10）
const AuthBackground = lazy(() => import('@/components/auth-background/AuthBackground'))

export default function AuthLayout({ children }: { children: ReactNode }) {
  return (
    <div
      className="auth-shell"
      style={{
        minHeight: '100vh',
        position: 'relative',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: 24,
      }}
    >
      <Suspense fallback={null}>
        <AuthBackground />
      </Suspense>
      <div className="auth-shell-body" style={{ width: 420, maxWidth: '100%' }}>
        {children}
      </div>
    </div>
  )
}
