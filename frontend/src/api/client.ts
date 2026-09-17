import axios from 'axios'

const TOKEN_KEY = 'cndb_access_token'

export function getToken(): string | null {
  try { return localStorage.getItem(TOKEN_KEY) } catch { return null }
}
export function setToken(token: string) {
  try { localStorage.setItem(TOKEN_KEY, token) } catch { /* noop */ }
}
export function clearToken() {
  try { localStorage.removeItem(TOKEN_KEY) } catch { /* noop */ }
}

const api = axios.create({
  baseURL: '/api',
  timeout: 30000,
  headers: { 'Content-Type': 'application/json' },
})

api.interceptors.request.use((config) => {
  const token = getToken()
  if (token) {
    config.headers = config.headers ?? {}
    ;(config.headers as Record<string, string>).Authorization = `Bearer ${token}`
  }
  if (config.headers?.['Content-Type'] === 'multipart/form-data') {
    delete (config.headers as Record<string, unknown>)['Content-Type']
  }
  return config
})

api.interceptors.response.use(
  (res) => res,
  (err) => {
    // 将 FastAPI 的 detail（字符串或校验错误数组）归一化进 err.message，
    // 各调用点的 `err.message` 展示即可拿到可读的后端文案
    const detail = err?.response?.data?.detail
    if (detail) {
      err.message =
        typeof detail === 'string'
          ? detail
          : Array.isArray(detail)
            ? detail.map((d: { msg?: string }) => d?.msg ?? JSON.stringify(d)).join('; ')
            : String(detail?.msg ?? JSON.stringify(detail))
    }
    if (err.response?.status === 401) {
      clearToken()
      try {
        const path = window.location.pathname
        if (!path.includes('/login') && !path.includes('/public')) {
          const returnTo = encodeURIComponent(path + window.location.search)
          window.location.href = `/login?return_to=${returnTo}`
        }
      } catch { /* noop */ }
    }
    return Promise.reject(err)
  },
)

export default api
