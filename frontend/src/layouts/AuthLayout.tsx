import { lazy, Suspense, useCallback, useState, type ReactNode } from 'react'

import AuthBackgroundSwitcher from '@/components/auth-background/AuthBackgroundSwitcher'
import {
  loadAuthBackground,
  saveAuthBackground,
} from '@/components/auth-background/preference'
import type { AuthBackgroundVariant } from '@/components/auth-background/types'

// 背景引擎与 5 个变体独立成 chunk：AuthLayout 本身在主入口，静态引入会把体积抬进首屏（ADR 0016 D10）
const AuthBackground = lazy(() => import('@/components/auth-background/AuthBackground'))

export default function AuthLayout({ children }: { children: ReactNode }) {
  const [variant, setVariant] = useState<AuthBackgroundVariant>(loadAuthBackground)

  const handleChange = useCallback((next: AuthBackgroundVariant) => {
    setVariant(next)
    saveAuthBackground(next)
  }, [])

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
        <AuthBackground variant={variant} />
      </Suspense>
      <div className="auth-shell-body" style={{ width: 420, maxWidth: '100%' }}>
        {children}
      </div>
      <AuthBackgroundSwitcher value={variant} onChange={handleChange} />
    </div>
  )
}
