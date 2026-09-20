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
  async (err) => {
    // responseType: 'blob' 的请求失败时，响应体是 Blob 而非 JSON 对象；
    // 若实际是 JSON（FastAPI detail），先解析出来再走统一的 detail 提取，
    // 否则 blob 请求（备份下载/报告渲染）失败时用户只能看到英文状态码文案
    if (err?.response?.data instanceof Blob && err.response.data.type.includes('application/json')) {
      try {
        err.response.data = JSON.parse(
          await new Promise<string>((resolve, reject) => {
            const reader = new FileReader()
            reader.onload = () => resolve(String(reader.result))
            reader.onerror = () => reject(reader.error)
            reader.readAsText(err.response.data)
          }),
        )
      } catch { /* 非 JSON 内容，保持原样 */ }
    }
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
