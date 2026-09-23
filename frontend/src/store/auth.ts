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
  /** 会话是否因 token 过期而失效（true 时 ProtectedRoute 展示友好过期提示） */
  expired: boolean
  login: (payload: LoginRequest) => Promise<void>
  register: (payload: RegisterRequest) => Promise<UserResponse>
  logout: () => void
  refresh: () => Promise<void>
  /** 外部（如 axios 401 拦截器）通知会话过期 —— 清 token + 置 expired 标志 */
  notifyExpired: () => void
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      user: null,
      token: getToken(),
      loading: true,
      expired: false,

      refresh: async () => {
        const t = getToken()
        if (!t) {
          set({ token: null, user: null, loading: false })
          return
        }
        set({ token: t, loading: true })
        try {
          const me = await authApi.me()
          set({ user: me, loading: false, expired: false })
        } catch {
          // me 请求也走 axios 拦截器，token 过期时拦截器已经调过 notifyExpired
          // 这里兜底：无论什么原因 me 失败，都视为会话失效
          clearToken()
          set({ token: null, user: null, loading: false, expired: true })
        }
      },

      login: async (payload) => {
        const res = await authApi.login(payload)
        persistToken(res.access_token)
        const me = await authApi.me()
        set({ token: res.access_token, user: me, expired: false })
      },

      register: async (payload) => {
        const u = await authApi.register(payload)
        // 注册成功后自动登录
        const res = await authApi.login({ login: payload.username, password: payload.password })
        persistToken(res.access_token)
        set({ token: res.access_token, user: u, expired: false })
        return u
      },

      logout: () => {
        clearToken()
        set({ token: null, user: null, expired: false })
      },

      notifyExpired: () => {
        /** axios 拦截器捕获 401 时调用，统一登出入口。
         *
         *  expired 标志与 logout 的 false 区分：ProtectedRoute 会据此展示
         *  "登录已过期" 提示文案，而 logout() 对应"用户主动退出"。
         */
        clearToken()
        set({ token: null, user: null, expired: true })
      },
    }),
    {
      name: 'cndb_auth',
      // 只持久化 token，user/loading 由 refresh 重建
      partialize: (state) => ({ token: state.token }),
    },
  ),
)
