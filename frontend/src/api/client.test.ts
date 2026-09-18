/** api/client 单元测试 —— token 存取、拦截器注入、detail 归一化、401 重定向 */
import { AxiosError, type AxiosHeaders, type InternalAxiosRequestConfig } from 'axios'
import { afterEach, describe, expect, it, vi } from 'vitest'
import api, { clearToken, getToken, setToken } from './client'

const TOKEN_KEY = 'cndb_access_token'

// ── token 存取 ──────────────────────────────────────────

describe('getToken / setToken / clearToken', () => {
  it('setToken 后 getToken 返回同值，clearToken 后为 null', () => {
    setToken('abc123')
    expect(getToken()).toBe('abc123')
    expect(localStorage.getItem(TOKEN_KEY)).toBe('abc123')
    clearToken()
    expect(getToken()).toBeNull()
  })

  it('localStorage.getItem 抛异常时 getToken 返回 null 而不抛出', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('access denied')
    })
    expect(getToken()).toBeNull()
  })

  it('localStorage.setItem 抛异常时 setToken 静默失败', () => {
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('quota exceeded')
    })
    expect(() => setToken('x')).not.toThrow()
  })

  it('localStorage.removeItem 抛异常时 clearToken 静默失败', () => {
    vi.spyOn(Storage.prototype, 'removeItem').mockImplementation(() => {
      throw new Error('access denied')
    })
    expect(() => clearToken()).not.toThrow()
  })
})

// ── 请求拦截器 ──────────────────────────────────────────

/** 安装自定义 adapter 捕获最终发出的请求配置 */
function installCaptureAdapter() {
  const captured: InternalAxiosRequestConfig[] = []
  api.defaults.adapter = async (config) => {
    captured.push(config)
    return {
      data: {},
      status: 200,
      statusText: 'OK',
      headers: {},
      config,
    } as never
  }
  return captured
}

/** 大小写不敏感地读取捕获到的请求头（axios AxiosHeaders 内部键名大小写不确定） */
function headerAt(headers: unknown, name: string): unknown {
  const entries = Object.entries((headers as AxiosHeaders)?.toJSON?.() ?? headers ?? {})
  const hit = entries.find(([k]) => k.toLowerCase() === name.toLowerCase())
  return hit?.[1]
}

describe('请求拦截器', () => {
  afterEach(() => {
    // 还原默认 adapter，避免影响其它用例
    delete api.defaults.adapter
  })

  it('有 token 时注入 Authorization: Bearer <token>', async () => {
    setToken('tok-1')
    const captured = installCaptureAdapter()
    await api.get('/ping')
    expect(captured).toHaveLength(1)
    expect(headerAt(captured[0].headers, 'Authorization')).toBe('Bearer tok-1')
  })

  it('无 token 时不注入 Authorization', async () => {
    clearToken()
    const captured = installCaptureAdapter()
    await api.get('/ping')
    expect(headerAt(captured[0].headers, 'Authorization')).toBeUndefined()
  })

  it('multipart 请求删除 Content-Type（交由浏览器生成 boundary）', () => {
    // 直接调用请求拦截器验证删除行为：真实请求链路上 axios 对 FormData 会自行
    // 处理 Content-Type，端到端捕获无法归因到本拦截器
    const handlers = api.interceptors.request.handlers ?? []
    const interceptor = handlers[0]!
    // 拦截器 fulfilled 的返回类型含 Promise 分支，此处同步调用必为配置对象
    const config = interceptor.fulfilled!({
      headers: { 'Content-Type': 'multipart/form-data' },
    } as InternalAxiosRequestConfig) as InternalAxiosRequestConfig
    expect((config.headers as Record<string, unknown>)['Content-Type']).toBeUndefined()
  })
})

// ── 响应拦截器：detail 归一化 + 401 重定向 ──────────────

/** 安装返回指定错误响应的 adapter.
 *
 * axios 不为自定义 adapter 执行 settle：非 2xx 必须显式 reject（构造 AxiosError），
 * 与内置 adapter 的 settle 行为一致。
 */
function installErrorAdapter(status: number, data: unknown) {
  api.defaults.adapter = async (config) => {
    const response = {
      data,
      status,
      statusText: 'Error',
      headers: {},
      config,
    }
    if (status >= 200 && status < 300) return response as never
    throw new AxiosError(
      `Request failed with status code ${status}`,
      AxiosError.ERR_BAD_REQUEST,
      config,
      null,
      response as never,
    )
  }
}

/** 替换 window.location 为可控 stub（jsdom 的 location 属性可 delete 后重定义） */
function stubLocation(pathname: string, search = '') {
  const original = window.location
  Reflect.deleteProperty(window, 'location')
  const stub = { pathname, search, href: `http://localhost${pathname}${search}` }
  Object.defineProperty(window, 'location', { value: stub, writable: true, configurable: true })
  return {
    stub,
    restore() {
      Reflect.deleteProperty(window, 'location')
      Object.defineProperty(window, 'location', {
        value: original, writable: false, configurable: true,
      })
    },
  }
}

describe('响应拦截器 detail 归一化', () => {
  afterEach(() => {
    delete api.defaults.adapter
  })

  it('detail 为字符串时 err.message 为该字符串', async () => {
    installErrorAdapter(400, { detail: '字段名重复' })
    await expect(api.get('/x')).rejects.toMatchObject({ message: '字段名重复' })
  })

  it('detail 为校验错误数组时合并各 msg', async () => {
    installErrorAdapter(422, {
      detail: [{ msg: 'name 必填' }, { msg: 'type 非法' }],
    })
    await expect(api.get('/x')).rejects.toMatchObject({ message: 'name 必填; type 非法' })
  })

  it('detail 为对象时取其 msg', async () => {
    installErrorAdapter(400, { detail: { msg: '对象形态错误' } })
    await expect(api.get('/x')).rejects.toMatchObject({ message: '对象形态错误' })
  })

  it('无 detail 时保留 axios 原始 message', async () => {
    installErrorAdapter(500, { foo: 'bar' })
    await expect(api.get('/x')).rejects.toMatchObject({ message: 'Request failed with status code 500' })
  })
})

describe('响应拦截器 401 重定向', () => {
  afterEach(() => {
    delete api.defaults.adapter
  })

  it('401 时清除 token 并跳转 /login?return_to=<path+query>', async () => {
    setToken('will-be-cleared')
    const { stub, restore } = stubLocation('/grid/1', '?view=2')
    try {
      installErrorAdapter(401, { detail: '未认证' })
      await expect(api.get('/x')).rejects.toBeTruthy()
      expect(getToken()).toBeNull()
      expect(stub.href).toBe(`/login?return_to=${encodeURIComponent('/grid/1?view=2')}`)
    } finally {
      restore()
    }
  })

  it('当前已在 /login 页面时不重定向', async () => {
    setToken('t')
    const { stub, restore } = stubLocation('/login')
    try {
      installErrorAdapter(401, {})
      await expect(api.get('/x')).rejects.toBeTruthy()
      expect(getToken()).toBeNull()
      expect(stub.href).toBe('http://localhost/login')
    } finally {
      restore()
    }
  })

  it('当前在 /public 路径时不重定向', async () => {
    setToken('t')
    const { stub, restore } = stubLocation('/public/share/abc')
    try {
      installErrorAdapter(401, {})
      await expect(api.get('/x')).rejects.toBeTruthy()
      expect(stub.href).toBe('http://localhost/public/share/abc')
    } finally {
      restore()
    }
  })

  it('非 401 错误不触发重定向', async () => {
    setToken('t')
    const { stub, restore } = stubLocation('/grid')
    try {
      installErrorAdapter(403, {})
      await expect(api.get('/x')).rejects.toBeTruthy()
      expect(getToken()).toBe('t')
      expect(stub.href).toBe('http://localhost/grid')
    } finally {
      restore()
    }
  })
})
