import React, { createContext, useContext, useEffect, useMemo, useState, useCallback } from 'react'
import { Spin } from 'antd'
import { authApi } from '@/api'
import { getToken, setToken as persistToken, clearToken } from '@/api/client'
import type { UserResponse, LoginRequest, RegisterRequest } from '@/api'

interface AuthContextValue {
  user: UserResponse | null
  token: string | null
  loading: boolean
  login: (payload: LoginRequest) => Promise<void>
  register: (payload: RegisterRequest) => Promise<UserResponse>
  logout: () => void
  refresh: () => Promise<void>
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined)

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<UserResponse | null>(null)
  const [token, setTokenState] = useState<string | null>(getToken())
  const [loading, setLoading] = useState(true)

  const refresh = useCallback(async () => {
    const t = getToken()
    setTokenState(t)
    if (!t) {
      setUser(null)
      setLoading(false)
      return
    }
    try {
      const me = await authApi.me()
      setUser(me)
    } catch {
      clearToken()
      setTokenState(null)
      setUser(null)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { refresh() }, [refresh])

  const login = useCallback(async (payload: LoginRequest) => {
    const res = await authApi.login(payload)
    persistToken(res.access_token)
    setTokenState(res.access_token)
    const me = await authApi.me()
    setUser(me)
  }, [])

  const register = useCallback(async (payload: RegisterRequest) => {
    const u = await authApi.register(payload)
    return u
  }, [])

  const logout = useCallback(() => {
    clearToken()
    setTokenState(null)
    setUser(null)
  }, [])

  const value = useMemo<AuthContextValue>(
    () => ({ user, token, loading, login, register, logout, refresh }),
    [user, token, loading, login, register, logout, refresh],
  )

  return React.createElement(AuthContext.Provider, { value }, children)
}

export function AuthLoading({ children }: { children: React.ReactNode }) {
  const { loading } = useAuth()
  if (loading) {
    return React.createElement(
      'div',
      { style: { display: 'flex', justifyContent: 'center', alignItems: 'center', height: '60vh' } },
      React.createElement(Spin, { size: 'large' }),
    )
  }
  return React.createElement(React.Fragment, null, children)
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside <AuthProvider>')
  return ctx
}
