/** Axios 客户端 —— token 注入、错误归一化、401 优雅登出.
 *
 * 401 处理策略：
 *  1. 防抖 —— 同一时间窗口（500ms）内多个并发 401 只触发一次回调，
 *     避免页面加载时 records/views/table 多路请求同时过期造成连锁跳转。
 *  2. 解耦 —— client 只负责发出 auth:expired 事件，不直接操作路由或 store；
 *     应用层（App.tsx / MainLayout）在启动时订阅，决定何时展示提示、何时跳转。
 *  3. 留时 —— 不在拦截器里强制跳转，给正在编辑的用户（如新增行填写中）
 *     留出保存 / 复制草稿的机会；ProtectedRoute 在 user 变 null 后自然触发
 *     路由守卫重定向到 login。
 */

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

// ── auth:expired 事件总线 ──────────────────────────────────

/** 订阅 401/令牌过期事件。
 *
 *  返回取消订阅函数。回调会在拦截器确认 401 后同步触发（防抖窗口内只触发一次）。
 *  应用层应在订阅里执行：调用 auth store 的 notifyExpired + 弹友好提示 + 后续路由守卫自然跳转。
 */
type AuthExpiredCallback = () => void
const _expiredListeners = new Set<AuthExpiredCallback>()
let _expiredTimer: ReturnType<typeof setTimeout> | null = null
const EXPIRED_DEBOUNCE_MS = 500

export function onAuthExpired(cb: AuthExpiredCallback): () => void {
  _expiredListeners.add(cb)
  return () => { _expiredListeners.delete(cb) }
}

/** 防抖触发过期事件 —— 拦截器调用入口。 */
function _emitAuthExpired() {
  if (_expiredTimer) return
  _expiredTimer = setTimeout(() => {
    _expiredTimer = null
    for (const cb of [..._expiredListeners]) {
      try { cb() } catch { /* 单个回调异常不阻断其它 */ }
    }
  }, EXPIRED_DEBOUNCE_MS)
}

// ── 响应拦截器 ──────────────────────────────────────────

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
      // 防抖发出事件 —— 应用层订阅后负责更新 store + 友好提示 + 路由跳转
      _emitAuthExpired()
    }

    return Promise.reject(err)
  },
)

export default api
