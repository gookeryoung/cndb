/** 网络请求客户端 —— 基于 Taro.request，提供 axios 风格 API + 自动 token 注入 + 401 拦截. */
import Taro from '@tarojs/taro'
import { API_BASE_URL } from '../config/env'
import { clearToken, getToken } from '../utils/storage'

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public data?: unknown,
  ) {
    super(message)
  }
}

interface RequestOptions {
  url: string
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'
  data?: unknown
  params?: Record<string, unknown>
  headers?: Record<string, string>
  timeout?: number
}

let isRedirecting = false

/** 统一请求方法. */
export async function request<T = unknown>(opts: RequestOptions): Promise<T> {
  const token = getToken()
  const header: Record<string, string> = {
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...opts.headers,
  }

  // query string 拼接
  let url = API_BASE_URL + opts.url
  if (opts.params) {
    const qs = Object.entries(opts.params)
      .filter(([, v]) => v !== undefined && v !== null && v !== '')
      .map(([k, v]) => {
        const val = typeof v === 'string' ? v : JSON.stringify(v)
        return `${encodeURIComponent(k)}=${encodeURIComponent(val)}`
      })
      .join('&')
    if (qs) url += `?${qs}`
  }

  try {
    const res = await Taro.request({
      url,
      method: opts.method || 'GET',
      data: opts.data as Record<string, unknown>,
      header,
      timeout: opts.timeout ?? 30_000,
    })

    if (res.statusCode === 401) {
      if (!isRedirecting) {
        isRedirecting = true
        clearToken()
        Taro.reLaunch({ url: '/pages/login/index' }).finally(() => { isRedirecting = false })
      }
      throw new ApiError(401, '登录已过期，请重新登录')
    }

    if (res.statusCode >= 200 && res.statusCode < 300) {
      return (res.data ?? null) as T
    }

    const errMsg = extractErrorMsg(res.data)
    throw new ApiError(res.statusCode, errMsg, res.data)
  } catch (err) {
    if (err instanceof ApiError) throw err
    const msg = err instanceof Error ? err.message : String(err)
    throw new ApiError(0, msg)
  }
}

/** 提取后端返回的错误信息. */
function extractErrorMsg(data: unknown): string {
  if (!data || typeof data !== 'object') return `请求失败`
  const obj = data as { detail?: string; message?: string }
  return obj.detail || obj.message || `请求失败`
}

/** multipart 文件上传. */
export function upload(
  url: string,
  filePath: string,
  name: string,
  formData?: Record<string, string>,
): Promise<Record<string, unknown>> {
  const token = getToken()
  return new Promise((resolve, reject) => {
    Taro.uploadFile({
      url: API_BASE_URL + url,
      filePath,
      name,
      formData,
      header: token ? { Authorization: `Bearer ${token}` } : {},
      success: (res) => {
        try {
          const data = JSON.parse(res.data)
          if (res.statusCode >= 200 && res.statusCode < 300) resolve(data)
          else reject(new ApiError(res.statusCode, extractErrorMsg(data)))
        } catch {
          reject(new ApiError(res.statusCode, String(res.data)))
        }
      },
      fail: reject,
    })
  })
}
