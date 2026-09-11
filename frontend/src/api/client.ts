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
