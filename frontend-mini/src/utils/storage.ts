/** 本地存储封装 —— token + 用户信息. */
import Taro from '@tarojs/taro'

const TOKEN_KEY = 'cndb_access_token'
const USER_KEY = 'cndb_user_info'

export function getToken(): string | null {
  try {
    const v = Taro.getStorageSync(TOKEN_KEY)
    return v || null
  } catch {
    return null
  }
}
export function setToken(token: string) {
  Taro.setStorageSync(TOKEN_KEY, token)
}
export function clearToken() {
  Taro.removeStorageSync(TOKEN_KEY)
}

export interface StoredUser {
  id: number
  username: string
  nickname: string
  role: string
  is_superuser: boolean
}

export function getUser(): StoredUser | null {
  try {
    const raw = Taro.getStorageSync(USER_KEY)
    return raw ? (JSON.parse(raw) as StoredUser) : null
  } catch {
    return null
  }
}
export function setUser(user: StoredUser) {
  Taro.setStorageSync(USER_KEY, JSON.stringify(user))
}
export function clearUser() {
  Taro.removeStorageSync(USER_KEY)
}
