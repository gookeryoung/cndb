/** AuthContext —— 登录态全局管理 + 自动恢复. */
import {
  createContext, useCallback, useContext, useEffect, useState,
  PropsWithChildren,
} from 'react'
import Taro from '@tarojs/taro'
import { authApi } from '../api/auth'
import {
  clearToken, clearUser, getToken, getUser,
  setToken, setUser, type StoredUser,
} from '../utils/storage'

interface AuthContextValue {
  user: StoredUser | null
  isLoading: boolean
  isAuthenticated: boolean
  loginWithPassword: (login: string, password: string) => Promise<void>
  loginWithWechat: () => Promise<void>
  logout: () => Promise<void>
  refresh: () => Promise<void>
}

const AuthContext = createContext<AuthContextValue | null>(null)

function toStoredUser(me: {
  id: number; username: string; nickname: string; role: string; is_superuser: boolean
}): StoredUser {
  return {
    id: me.id,
    username: me.username,
    nickname: me.nickname || me.username,
    role: me.role,
    is_superuser: me.is_superuser,
  }
}

export function AuthProvider({ children }: PropsWithChildren) {
  const [user, setUserState] = useState<StoredUser | null>(null)
  const [isLoading, setIsLoading] = useState(true)

  // 应用启动时尝试恢复登录态
  useEffect(() => {
    async function restore() {
      const savedUser = getUser()
      const token = getToken()
      if (savedUser && token) {
        try {
          const me = await authApi.me()
          const u = toStoredUser(me)
          setUserState(u); setUser(u)
        } catch {
          clearToken(); clearUser()
        }
      }
      setIsLoading(false)
    }
    restore()
  }, [])

  const loginWithPassword = useCallback(async (login: string, password: string) => {
    const res = await authApi.login(login, password)
    setToken(res.access_token)
    const me = await authApi.me()
    const u = toStoredUser(me)
    setUserState(u); setUser(u)
  }, [])

  const loginWithWechat = useCallback(async () => {
    const wxRes = await new Promise<Taro.login.SuccessCallbackResult>(
      (resolve, reject) => Taro.login({ success: resolve, fail: reject }),
    )
    if (!wxRes.code) throw new Error('微信登录失败：未获取到 code')

    let nickname: string | undefined
    let avatar_url: string | undefined
    try {
      const profile = await new Promise<Taro.getUserProfile.SuccessCallbackResult>(
        (resolve, reject) => Taro.getUserProfile({ desc: '用于完善资料', success: resolve, fail: reject }),
      )
      nickname = profile.userInfo.nickName
      avatar_url = profile.userInfo.avatarUrl
    } catch { /* 用户未授权，继续登录 */ }

    const res = await authApi.wechatLogin(wxRes.code, nickname, avatar_url)
    setToken(res.access_token)
    const u = toStoredUser(res.user)
    setUserState(u); setUser(u)
  }, [])

  const logout = useCallback(async () => {
    clearToken(); clearUser(); setUserState(null)
  }, [])

  const refresh = useCallback(async () => {
    const me = await authApi.me()
    const u = toStoredUser(me)
    setUserState(u); setUser(u)
  }, [])

  return (
    <AuthContext.Provider value={{
      user, isLoading, isAuthenticated: !!user,
      loginWithPassword, loginWithWechat, logout, refresh,
    }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth 必须在 AuthProvider 内使用')
  return ctx
}
