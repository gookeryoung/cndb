/** 认证状态 store —— 替代原 AuthContext (React Context).
 *
 * token 通过 persist 中间件持久化到 localStorage，
 * user/loading 由 refresh 流程驱动，不持久化。
 */

import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import { authApi } from '@/api'
import { clearToken, getToken, setToken as persistToken } from '@/api/client'
import type { LoginRequest, RegisterRequest, UserResponse } from '@/api'

interface AuthState {
  user: UserResponse | null
  token: string | null
  loading: boolean
  login: (payload: LoginRequest) => Promise<void>
  register: (payload: RegisterRequest) => Promise<UserResponse>
  logout: () => void
  refresh: () => Promise<void>
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      user: null,
      token: getToken(),
      loading: true,

      refresh: async () => {
        const t = getToken()
        if (!t) {
          set({ token: null, user: null, loading: false })
          return
        }
        set({ token: t, loading: true })
        try {
          const me = await authApi.me()
          set({ user: me, loading: false })
        } catch {
          clearToken()
          set({ token: null, user: null, loading: false })
        }
      },

      login: async (payload) => {
        const res = await authApi.login(payload)
        persistToken(res.access_token)
        const me = await authApi.me()
        set({ token: res.access_token, user: me })
      },

      register: async (payload) => {
        const u = await authApi.register(payload)
        // 注册成功后自动登录
        const res = await authApi.login({ login: payload.username, password: payload.password })
        persistToken(res.access_token)
        set({ token: res.access_token, user: u })
        return u
      },

      logout: () => {
        clearToken()
        set({ token: null, user: null })
      },
    }),
    {
      name: 'cndb_auth',
      // 只持久化 token，user/loading 由 refresh 重建
      partialize: (state) => ({ token: state.token }),
    },
  ),
)
